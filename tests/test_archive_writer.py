"""archive_writer 测试：档案两动作 adopt（首优收档）/ advance（交付收口推进）——
目录定调 2026-08-31：档案=ddlc_design_dev/archive/ 单目录当前态，演进史=git 提交历史。"""
import json

from archive_writer import adopt, advance, main


def _mk(p, files: dict):
    p.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        f = p / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")


class TestAdopt:
    def test_adopt_moves_newpipe_outputs(self, tmp_path):
        """平铺产出收档：ts/etl/ddl/dq 移入 archive/，decisions 拷入（_internal 原位不动）。"""
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
        assert not (dest / "ddl").exists(), "DDL 是 ts 可再生投影，不入档案（2026-09-04 裁决）"
        assert (ddlc / "ddl/create_table_t.sql").exists(), "new-pipe 的 ddl 留交付现场"
        assert (dest / "decisions.yaml").exists()
        # 平铺原件移走（mv）；交付现场与过程产物留原位
        assert not (ddlc / "ts.json").exists() and not (ddlc / "etl").exists()
        assert not (ddlc / "export").exists(), "export 随收档入档"
        assert (ddlc / "ut_report.md").exists()
        assert (ddlc / "_internal/design_decisions.yaml").exists()

    def test_adopt_without_dq_ok(self, tmp_path):
        """无 DQ 资产（dq/ 可缺）照常收档。"""
        ddlc = tmp_path / "ddlc_design_dev"
        _mk(ddlc, {"ts.json": "{}", "etl/R0001.sql": "SELECT 1",
                   "ddl/x.sql": "CREATE", "_internal/design_decisions.yaml": "d: 1"})
        adopt(ddlc)
        assert not (ddlc / "archive/dq").exists()

    def test_adopt_twice_rejected(self, tmp_path):
        """已有档案再收档 → 拒（幂等保护）。"""
        ddlc = tmp_path / "ddlc_design_dev"
        _mk(ddlc, {"ts.json": "{}", "_internal/design_decisions.yaml": "d: 1"})
        adopt(ddlc)
        try:
            adopt(ddlc)
            assert False, "应拒绝重复收档"
        except ValueError as e:
            assert "已存在" in str(e)

    def test_adopt_without_newpipe_outputs_rejected(self, tmp_path):
        ddlc = tmp_path / "ddlc_design_dev"
        _mk(ddlc, {"export/x.xlsx": "bin"})
        try:
            adopt(ddlc)
            assert False
        except ValueError as e:
            assert "ts.json" in str(e)

    def test_adopt_main(self, tmp_path):
        ddlc = tmp_path / "ddlc"
        _mk(ddlc, {"ts.json": "{}", "_internal/design_decisions.yaml": "d: 1"})
        assert main(["adopt", "--ddlc", str(ddlc)]) == 0
        assert (ddlc / "archive/decisions.yaml").exists()


class TestAdvance:
    def _site(self, tmp_path):
        """已建档资产 + 一次优化现场。"""
        ddlc = tmp_path / "ddlc"
        _mk(ddlc, {"archive/ts.json": '{"v": 1}', "archive/etl/R0001.sql": "OLD",
                   "archive/etl/R0002.sql": "KEEP",
                   "archive/export/shujia_t.xlsx": "old-bin",
                   "archive/decisions.yaml": "old: 1"})
        _mk(ddlc / "opt", {"ts_v2.json": '{"v": 2}', "ts.md": "# v2",
                           "etl/R0001.sql": "NEW",
                           "export/patched/shujia_t.xlsx": "new-bin",
                           "_internal/design_decisions_opt.yaml": "opt: 1"})
        return ddlc

    def test_advance_promotes_current_state(self, tmp_path):
        ddlc = self._site(tmp_path)
        advance(ddlc / "opt", ddlc / "archive")
        arc = ddlc / "archive"
        assert json.loads((arc / "ts.json").read_text())["v"] == 2
        assert (arc / "ts.md").read_text() == "# v2"
        assert (arc / "etl/R0001.sql").read_text() == "NEW", "同名覆盖=该规则当前版"
        assert (arc / "etl/R0002.sql").read_text() == "KEEP", "未变更规则零接触"
        assert (arc / "decisions.yaml").read_text() == "opt: 1"
        assert (arc / "export/shujia_t.xlsx").read_text() == "new-bin", "patched 副本=制品当前态"
        # opt 现场保留（交付物人取用）
        assert (ddlc / "opt/ts_v2.json").exists()

    def test_advance_without_output_rejected(self, tmp_path):
        ddlc = tmp_path / "ddlc"
        _mk(ddlc / "archive", {"ts.json": "{}"})
        try:
            advance(ddlc / "opt", ddlc / "archive")
            assert False
        except ValueError as e:
            assert "ts_v2" in str(e)

    def test_advance_main(self, tmp_path):
        ddlc = self._site(tmp_path)
        assert main(["advance", "--opt", str(ddlc / "opt"),
                     "--archive", str(ddlc / "archive")]) == 0
        assert json.loads((ddlc / "archive/ts.json").read_text())["v"] == 2
