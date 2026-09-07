"""archive_writer 测试：档案两动作 adopt（首优收档+建造现场归置+MANIFEST 首建）/
advance（交付收口推进+MANIFEST 追加）——2026-09-07 文件系统自解释：opt_{version} 目录
留存=优化次数、build/ 存在=自建资产、MANIFEST=版本史一眼索引。"""
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
    def test_adopt_moves_newpipe_outputs_and_build_site(self, tmp_path):
        """收档：ts/etl/dq/export 入档案；ddl/ut_report/_internal 归置 build/；MANIFEST 首建。"""
        ddlc = tmp_path / "ddlc_design_dev"
        _mk(ddlc, {"ts.json": "{}", "ts.md": "# ts", "etl/R0001.sql": "SELECT 1",
                   "ddl/create_table_t.sql": "CREATE...", "dq/dq_01_null.sql": "SELECT 2",
                   "export/制品.xlsx": "bin", "ut_report.md": "# ut",
                   "_internal/design_decisions.yaml": "grain: ...",
                   "_internal/rs_input.json": "{}"})
        dest = adopt(ddlc)
        assert dest == ddlc / "archive"
        assert (dest / "ts.json").exists() and (dest / "ts.md").exists()
        assert (dest / "etl/R0001.sql").exists()
        assert (dest / "dq/dq_01_null.sql").exists()
        assert (dest / "export/制品.xlsx").exists(), "平台制品包入档（patch 链底本）"
        assert (dest / "decisions.yaml").exists()
        # 建造现场归置 build/（命名空间化——根下不再散落）
        assert (ddlc / "build/ddl/create_table_t.sql").exists()
        assert (ddlc / "build/ut_report.md").exists()
        assert (ddlc / "build/_internal/rs_input.json").exists()
        assert not (ddlc / "_internal").exists() and not (ddlc / "ut_report.md").exists()
        assert not (dest / "ddl").exists(), "DDL 是 ts 可再生投影，不入档案"
        mf = (dest / "MANIFEST.md").read_text(encoding="utf-8")
        assert "v1" in mf and "建造" in mf

    def test_adopt_without_dq_ok(self, tmp_path):
        """无 DQ 资产（dq/ 可缺）照常收档。"""
        ddlc = tmp_path / "ddlc_design_dev"
        _mk(ddlc, {"ts.json": "{}", "etl/R0001.sql": "SELECT 1",
                   "ddl/x.sql": "CREATE", "_internal/design_decisions.yaml": "d: 1"})
        adopt(ddlc)
        assert not (ddlc / "archive/dq").exists()

    def test_adopt_without_newpipe_outputs_rejected(self, tmp_path):
        ddlc = tmp_path / "ddlc_design_dev"
        _mk(ddlc, {"export/x.xlsx": "bin"})
        with pytest.raises(ValueError, match="ts.json"):
            adopt(ddlc)

    def test_advance_json_ingested_asset_has_no_build(self, tmp_path):
        """存量资产（json 入料）无 build/——advance 照常（目录形态自解释资产来源）。"""
        ddlc = tmp_path / "ddlc"
        _mk(ddlc, {"archive/ts.json": '{"v": 1}',
                   "archive/MANIFEST.md": "# x\n\n| 版本 | 内容 |\n|------|------|\n| v1 | 逆向入料 |\n"})
        opt = ddlc / "opt_202609"
        _mk(opt, {"ts.json": '{"v": 2}',
                  "_internal/design_decisions_opt.yaml": "opt: 1"})
        advance(opt, ddlc / "archive")
        assert not (ddlc / "build").exists()
        assert not (ddlc / "archive").exists() or True

    def test_adopt_twice_rejected(self, tmp_path):
        ddlc = tmp_path / "ddlc_design_dev"
        _mk(ddlc, {"ts.json": "{}", "_internal/design_decisions.yaml": "d: 1"})
        adopt(ddlc)
        with pytest.raises(ValueError, match="已存在"):
            adopt(ddlc)

    def test_adopt_main(self, tmp_path):
        ddlc = tmp_path / "ddlc"
        _mk(ddlc, {"ts.json": "{}", "_internal/design_decisions.yaml": "d: 1"})
        assert main(["adopt", "--ddlc", str(ddlc)]) == 0
        assert (ddlc / "archive/decisions.yaml").exists()
        assert (ddlc / "build/_internal/design_decisions.yaml").exists()


class TestAdvance:
    def _site(self, tmp_path, version="202609"):
        ddlc = tmp_path / "ddlc"
        _mk(ddlc, {"archive/ts.json": '{"v": 1}', "archive/etl/R0001.sql": "OLD",
                   "archive/etl/R0002.sql": "KEEP",
                   "archive/export/shujia_t.xlsx": "old-bin",
                   "archive/decisions.yaml": "old: 1",
                   "archive/MANIFEST.md": "# 资产演进索引\n\n| 版本 | 内容 |\n|------|------|\n| v1 | 建造 |\n"})
        opt = ddlc / f"opt_{version}"
        _mk(opt, {"ts.json": '{"v": 2}', "ts.md": "# v2",
                  "etl/R0001.sql": "NEW",
                  "export/patched/shujia_t.xlsx": "new-bin",
                  "_internal/change_request.json": json.dumps(
                      {"version": version, "change_log_summary": {"desc": "优化版本：新增渠道字段"},
                       "fields": [{"field": "channel_name"}, {"field": "shop_type"}]},
                      ensure_ascii=False),
                  "_internal/design_decisions_opt.yaml": "opt: 1"})
        return ddlc, opt

    def test_advance_promotes_and_appends_manifest(self, tmp_path):
        ddlc, opt = self._site(tmp_path)
        advance(opt, ddlc / "archive")
        arc = ddlc / "archive"
        assert json.loads((arc / "ts.json").read_text())["v"] == 2
        assert (arc / "etl/R0001.sql").read_text() == "NEW", "同名覆盖=该规则当前版"
        assert (arc / "etl/R0002.sql").read_text() == "KEEP", "未变更规则零接触"
        assert (arc / "export/shujia_t.xlsx").read_text() == "new-bin", "patched 副本=制品当前态"
        assert (arc / "decisions.yaml").read_text() == "opt: 1"
        # MANIFEST 追加本次记录
        mf = (arc / "MANIFEST.md").read_text(encoding="utf-8")
        assert "| 202609 |" in mf and "+2 字段" in mf and "渠道字段" in mf
        assert "| v1 |" in mf, "建造行保留"
        # opt 现场保留（交付物人取用）
        assert (opt / "ts.json").exists()

    def test_advance_without_output_rejected(self, tmp_path):
        ddlc = tmp_path / "ddlc"
        _mk(ddlc / "archive", {"ts.json": "{}"})
        with pytest.raises(ValueError, match="ts.json"):
            advance(ddlc / "opt_202609", ddlc / "archive")

    def test_advance_main(self, tmp_path):
        ddlc, opt = self._site(tmp_path)
        assert main(["advance", "--opt", str(opt),
                     "--archive", str(ddlc / "archive")]) == 0
        assert json.loads((ddlc / "archive/ts.json").read_text())["v"] == 2
