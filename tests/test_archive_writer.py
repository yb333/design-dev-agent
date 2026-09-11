"""archive_writer 测试：档案两动作——adopt 交付建档（含 ddl）/ advance 三步全量替换
（tmp 整体上位+MANIFEST 追加+清过程产物+可恢复性）。目录模型 2026-09-07 终态。"""
import json

import pytest

from archive_writer import adopt, advance, main


def _mk(p, files: dict):
    p.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        f = p / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")


class TestAdopt:
    def test_adopt_extracts_including_ddl(self, tmp_path):
        """建档：ts/etl/dq/ddl/export + decisions 入档案（DDL 归档：可信基线=完整可用资产）；MANIFEST 首建。"""
        ddlc = tmp_path / "ddlc"
        build = ddlc / "build"
        _mk(build, {"ts.json": "{}", "ts.md": "# ts", "etl/R0001.sql": "SELECT 1",
                    "ddl/create_table_t.sql": "CREATE...", "dq/dq_01.sql": "SELECT 2",
                    "export/制品.xlsx": "bin", "ut_report.md": "# ut",
                    "_internal/design_decisions.yaml": "grain: ..."})
        dest = adopt(build)
        assert dest == ddlc / "archive"
        assert (dest / "ddl/create_table_t.sql").exists(), "DDL 入档（完整可重建资产）"
        assert (dest / "export/制品.xlsx").exists() and (dest / "decisions.yaml").exists()
        assert (build / "_internal/design_decisions.yaml").exists(), "过程产物留 build"
        # 复制不移动（2026-09-07 定调）：build 保留完整交付现场（全量部署内容）
        assert (build / "ts.json").exists() and (build / "etl/R0001.sql").exists()
        assert (build / "ddl/create_table_t.sql").exists() and (build / "export/制品.xlsx").exists()
        assert (build / "ut_report.md").exists(), "报告留交付现场"
        mf = (dest / "MANIFEST.md").read_text(encoding="utf-8")
        assert "v1" in mf and "建造" in mf

    def test_adopt_twice_rejected(self, tmp_path):
        build = tmp_path / "ddlc" / "build"
        _mk(build, {"ts.json": "{}", "_internal/design_decisions.yaml": "d: 1"})
        adopt(build)
        with pytest.raises(ValueError, match="已存在"):
            adopt(build)


class TestAdvance:
    def _site(self, tmp_path):
        """有档资产 + 增量现场 + 临时档案（进度态全量：新 ts/新 SQL/patched 制品/MANIFEST）。"""
        ddlc = tmp_path / "ddlc"
        _mk(ddlc, {"archive/ts.json": '{"v": 1}', "archive/etl/R0001.sql": "OLD",
                   "archive/etl/R0002.sql": "KEEP",
                   "archive/export/shujia.xlsx": "old-bin",
                   "archive/MANIFEST.md": "# idx\n\n| 版本 | 内容 |\n|------|------|\n| v1 | 建造 |\n"})
        arc_tmp = ddlc / "archive_tmp"
        _mk(arc_tmp, {"ts.json": '{"v": 2}',
                      "etl/R0001.sql": "NEW", "etl/R0002.sql": "KEEP",
                      "export/shujia.xlsx": "new-bin",
                      "_internal/diagnose/plan_R0001.txt": "PLAN-LEAK",
                      "MANIFEST.md": "# idx\n\n| 版本 | 内容 |\n|------|------|\n| v1 | 建造 |\n"})
        build = ddlc / "build"
        _mk(build, {"_internal/change_request.json": json.dumps(
            {"version": "202609", "change_log_summary": {"desc": "优化版本：新增渠道字段"},
             "fields": [{"field": "channel_name"}, {"field": "shop_type"}]},
            ensure_ascii=False)})
        return ddlc, arc_tmp, build

    def test_full_replacement_and_manifest(self, tmp_path):
        ddlc, arc_tmp, build = self._site(tmp_path)
        dest = advance(ddlc / "archive", arc_tmp, build)
        assert dest == ddlc / "archive"
        assert json.loads((dest / "ts.json").read_text())["v"] == 2, "tmp 整体上位"
        assert (dest / "etl/R0001.sql").read_text() == "NEW"
        assert not (dest / "_internal").exists(), "过程产物不随替换进档案（清掉）"
        mf = (dest / "MANIFEST.md").read_text(encoding="utf-8")
        assert "| 202609 |" in mf and "+2 字段" in mf and "| v1 |" in mf
        assert not (ddlc / "archive_tmp").exists(), "tmp 已上位"
        assert not (ddlc / "archive.replaced").exists(), "旧档残留已清"

    def test_no_partial_state_on_missing_tmp(self, tmp_path):
        """tmp 缺产物 → 拒绝替换且旧档完好（原子性：要么旧要么新）。"""
        ddlc, arc_tmp, build = self._site(tmp_path)
        (arc_tmp / "ts.json").unlink()
        with pytest.raises(ValueError, match="ts.json"):
            advance(ddlc / "archive", arc_tmp, build)
        assert json.loads((ddlc / "archive/ts.json").read_text())["v"] == 1, "旧档未动"

    def test_main(self, tmp_path):
        ddlc, arc_tmp, build = self._site(tmp_path)
        rc = main(["advance", "--archive", str(ddlc / "archive"),
                   "--tmp", str(arc_tmp), "--build", str(build)])
        assert rc == 0
        assert json.loads((ddlc / "archive/ts.json").read_text())["v"] == 2
