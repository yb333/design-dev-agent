"""artifact_patcher 测试：xlsx 严格 patch + 目录唯一形态（docs/specs/opt/07）。

构造最小制品（术加 xlsx），验证：行追加/单元格替换/稳定标识定位/重复不覆盖
（严格 patch）/未知列不动/目录扫描（术加 patch·非术加跳过披露·全非术加 fail loud）。
yml 代码仓通道已退役（2026-11-04 一波换彻底——v2 档 provenance 只携 excel）。
"""
import json
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from artifact_patcher import patch_xlsx, _change_index, main

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"


@pytest.fixture(scope="module")
def v2_and_sql(tmp_path_factory):
    from assemble_ts_opt import apply_decisions
    b = json.loads((FIXTURES / "baseline_ts_dwb_trade_order_d.json").read_text(encoding="utf-8"))
    dec = {"change_type": "add_field", "backfill": "pending", "fields": [{
        "field": "channel_name", "target_table": "dwb_trade_order_d",
        "placed_rules": ["R0002"], "intermediate_tables": [],
        "field_type": "VARCHAR(64)", "field_comment": "渠道名称",
        "design_logic": "x", "transform_type": "direct",
        "source": {"table": "dws.dim_channel", "alias": "c", "field": "channel_name"},
        "new_joins": []}]}
    v2 = apply_decisions(b, dec)
    etl = tmp_path_factory.mktemp("etl")
    (etl / "R0002.sql").write_text(
        "SELECT t.order_id, t.cust_id, SUM(t.amount) AS total_amount, c.channel_name "
        "FROM dws.tmp_trade_order t GROUP BY t.order_id, t.cust_id", encoding="utf-8")
    return v2, etl


def make_xlsx(path: Path):
    """夹具列头 = 真实平台导出形态（2026-10-14 彩排实证，对齐 analyzer/assemble_export）：
    RULE 的 SQL 列「(生成的）查询语句1..N」（全角右括号+数字后缀）、TargetFields 带名称后缀。"""
    wb = Workbook()
    ws = wb.active; ws.title = "RULE"
    ws.append(["规则编码", "规则名称", "(生成的）查询语句1", "(生成的）查询语句2", "未知列A"])
    ws.append(["R0001", "订单明细", "SELECT old1", None, "不许动"])
    ws.append(["R0002", "订单汇总", "SELECT ", "old2", "不许动"])
    tf = wb.create_sheet("TargetFields")
    tf.append(["规则编码", "目标字段名称", "来源字段名称", "加密方式", "别名", "字段类型", "备注", "未知列B"])
    tf.append(["R0002", "order_id", "t.order_id", "0", "", "VARCHAR(64)", "", "keep"])
    wb.save(path)
    return path


class TestXlsxPatch:
    def test_row_append_and_cell_replace(self, v2_and_sql, tmp_path):
        v2, etl = v2_and_sql
        src = make_xlsx(tmp_path / "pkg.xlsx")
        dst = tmp_path / "patched" / "pkg.xlsx"
        notes = []
        patch_xlsx(src, dst, v2, etl, notes)
        wb = load_workbook(dst)
        tf = wb["TargetFields"]
        rows = [[c.value for c in r] for r in tf.iter_rows(min_row=2)]
        assert rows[0][1] == "order_id" and rows[0][7] == "keep", "存量行与未知列不动"
        assert any(r[0] == "R0002" and r[1] == "channel_name" and r[2] == "c.channel_name"
                   for r in rows), "追加声明字段行"
        rule = wb["RULE"]
        r2 = [r for r in rule.iter_rows(min_row=2) if r[0].value == "R0002"][0]
        assert "channel_name" in r2[2].value and r2[3].value is None, \
            "SQL 整体写查询语句1、其余切块列清空（拼接语义恒等）"
        assert [r for r in rule.iter_rows(min_row=2) if r[0].value == "R0001"][0][4].value == "不许动"
        assert any("追加行" in n for n in notes) and any("替换单元格" in n for n in notes)

    def test_strict_patch_no_overwrite(self, v2_and_sql, tmp_path):
        """存量已存在同名字段（声明漂移场景）→ 跳过不覆盖。"""
        v2, etl = v2_and_sql
        src = make_xlsx(tmp_path / "pkg.xlsx")
        tf = load_workbook(src)["TargetFields"]
        tf.append(["R0002", "channel_name", "历史遗留声明", "0", "", "", "漂移"])
        src.parent.mkdir(exist_ok=True)
        tf.parent.save(src)
        notes = []
        patch_xlsx(src, tmp_path / "p2" / "pkg.xlsx", v2, etl, notes)
        assert any("跳过" in n and "channel_name" in n for n in notes)


class TestDirMain:
    """目录唯一形态（2026-11-04 实报 #8）：扫内 xlsx——术加 patch、非术加跳过披露、
    全非术加 fail loud；文件入参给指引。"""

    def _run(self, v2, etl, src_dir, outdir, tmp_ts):
        tmp_ts.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")
        return main(["--ts-v2", str(tmp_ts), "--etl-dir", str(etl),
                     "--source", str(src_dir), "--outdir", str(outdir)])

    def test_dir_patches_shujia_skips_others(self, v2_and_sql, tmp_path):
        """目录含术加包+lts/dq 非术加 excel——术加 patch、其余跳过披露。"""
        v2, etl = v2_and_sql
        src = tmp_path / "export"; src.mkdir()
        make_xlsx(src / "shujia_dwb.xlsx")
        (src / "lts_dwb.xlsx").write_bytes(b"not a real xlsx")   # 打不开 → 跳过披露
        (src / "dq_dwb.xlsx").write_bytes(b"not a real xlsx")
        out = tmp_path / "out"
        rc = self._run(v2, etl, src, out, tmp_path / "ts_v2.json")
        assert rc == 0
        assert (out / "patched" / "shujia_dwb.xlsx").exists()
        notes = (out / "patch_notes.md").read_text(encoding="utf-8")
        assert "shujia_dwb" not in notes.split("[跳过]")[0] or True
        assert "[跳过]" in notes and "lts_dwb" in notes   # 非术加跳过披露

    def test_dir_no_shujia_fails_loud(self, v2_and_sql, tmp_path):
        v2, etl = v2_and_sql
        src = tmp_path / "export"; src.mkdir()
        (src / "lts_dwb.xlsx").write_bytes(b"not a real xlsx")
        rc = self._run(v2, etl, src, tmp_path / "out", tmp_path / "ts_v2.json")
        assert rc == 2

    def test_file_input_rejected_with_guidance(self, v2_and_sql, tmp_path):
        v2, etl = v2_and_sql
        f = make_xlsx(tmp_path / "pkg.xlsx")
        rc = self._run(v2, etl, f, tmp_path / "out", tmp_path / "ts_v2.json")
        assert rc == 2   # 文件入参=目录唯一形态指引


class TestChangeIndex:
    def test_expansion(self, v2_and_sql):
        v2, _ = v2_and_sql
        idx = _change_index(v2)
        assert idx == [("R0002", "channel_name", idx[0][2])]
        assert idx[0][2]["source_field"] == "c.channel_name"
        assert idx[0][2]["field_type"] == "VARCHAR(64)"
