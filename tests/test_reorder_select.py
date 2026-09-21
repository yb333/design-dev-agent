"""reorder_select 测试（fake，不连库）。

核心契约：
- 期望序与 INSERT 列清单同函数同源（_resolve_insert_columns：结构源序∩规则产出列）；
- 纯 permutation：各项表达式原文保持不动只换顺序（case when 多行/函数嵌套随项走）；
- 未命中项（多列/无名/重名后续）原相对序收尾——对错归 check_sql/6a，本工具只管序；
- 幂等：已按序零改动；拒改形态（SELECT *）原样返回+披露。
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skills" / "dws-coding" / "scripts" / "reorder_select.py"
sys.path.insert(0, str(REPO / "skills" / "dws-coding" / "scripts"))
sys.path.insert(0, str(REPO / "skills" / "design-dev-shared" / "scripts"))

from reorder_select import reorder  # noqa: E402


def _ts(produced=("order_no", "cust_code", "amount", "dw_last_update_date")):
    """结构源序=fields 顺序；规则产出列=produced。"""
    fields = [{"target_field": f} for f in
              ["order_no", "prod_code", "cust_code", "amount", "dw_last_update_date"]]
    rule = {"target_table": "dws.dwb_test_f",
            "fields": {
                "direct": ["s.order_no AS order_no", "s.cust_code AS cust_code"],
                "processed": [{"target": "amount", "logic": "s.pay + s.discount"}],
                "assign": [{"target": "dw_last_update_date", "value": "${ETL_DATE}"}],
            }}
    return {"tables": {"dwb_test_f": {"fields": fields}}, "rules": {"R0001": rule}}


_SQL = """SELECT
    s.cust_code,
    case when nvl(s.del_flag, 'N') = 'N' then 'N' else 'Y' end AS amount,
    s.order_no,
    '${ETL_DATE}' AS dw_last_update_date
FROM ods.ods_test_f s
WHERE s.dt = '${BIZ_DATE}'"""


class TestReorder:
    def test_reordered_to_insert_list_order(self):
        """乱序 SQL → 重排为 INSERT 清单序；表达式项原文零加工。"""
        new_sql, notes = reorder(_SQL, ["order_no", "cust_code", "amount", "dw_last_update_date"])
        from sql_parse import split_top_projection_items
        assert [n for n, _ in split_top_projection_items(new_sql)] \
            == ["order_no", "cust_code", "amount", "dw_last_update_date"]
        # 表达式原文零加工（case when 整项随序走）
        assert "case when nvl(s.del_flag, 'N') = 'N' then 'N' else 'Y' end AS amount" in new_sql
        # FROM/WHERE 保持
        assert "FROM ods.ods_test_f s" in new_sql and "${BIZ_DATE}" in new_sql

    def test_idempotent_when_already_ordered(self):
        ordered = """SELECT
    s.order_no,
    s.cust_code,
    s.pay + s.discount AS amount,
    '${ETL_DATE}' AS dw_last_update_date
FROM ods.ods_test_f s"""
        new_sql, notes = reorder(ordered, ["order_no", "cust_code", "amount", "dw_last_update_date"])
        assert new_sql == ordered
        assert any("零改动" in n for n in notes)

    def test_extra_column_kept_at_tail_with_note(self):
        """多列（不在期望序）保持原相对序收尾，不被丢。"""
        sql = ("SELECT s.cust_code, s.order_no, s.extra_col FROM ods.ods_test_f s")
        new_sql, notes = reorder(sql, ["order_no", "cust_code"])
        names = [n for n, _ in __import__("sql_parse").split_top_projection_items(new_sql)]
        assert names == ["order_no", "cust_code", "extra_col"]

    def test_select_star_refused(self):
        sql = "SELECT * FROM ods.ods_test_f"
        new_sql, notes = reorder(sql, ["order_no"])
        assert new_sql == sql and any("SELECT \*" in n or "SELECT *" in n for n in notes)

    def test_cte_prefix_preserved(self):
        """WITH 段（CTE）保持不动，只重排主查询投影。"""
        sql = ("WITH base AS (SELECT id, rn FROM ods.t1 WHERE rn = 1)\n"
               "SELECT s.cust_code, s.order_no FROM base s")
        new_sql, _ = reorder(sql, ["order_no", "cust_code"])
        assert new_sql.startswith("WITH base AS (SELECT id, rn FROM ods.t1 WHERE rn = 1)")
        from sql_parse import split_top_projection_items
        assert [n for n, _ in split_top_projection_items(new_sql)] == ["order_no", "cust_code"]

    def test_scalar_subquery_item_moves_intact(self):
        """投影项含 FROM 的标量子查询：整项保持参与重排（2026-09-21 修——旧版段定位
        取第一个 FROM 把子查询切开、后续项全丢）。"""
        sql = ("SELECT s.cust_code,\n"
               "    (SELECT max(p.pay_time) FROM ods.pay p WHERE p.order_no = s.order_no) AS amount,\n"
               "    s.order_no\n"
               "FROM ods.ods_test_f s")
        new_sql, _ = reorder(sql, ["order_no", "cust_code", "amount"])
        from sql_parse import split_top_projection_items
        assert [n for n, _ in split_top_projection_items(new_sql)] == ["order_no", "cust_code", "amount"]
        assert "(SELECT max(p.pay_time) FROM ods.pay p WHERE p.order_no = s.order_no) AS amount" in new_sql

    def test_from_subquery_supported(self):
        sql = "SELECT s.cust_code, s.order_no FROM (SELECT order_no, cust_code FROM ods.t) s"
        new_sql, _ = reorder(sql, ["order_no", "cust_code"])
        from sql_parse import split_top_projection_items
        assert [n for n, _ in split_top_projection_items(new_sql)] == ["order_no", "cust_code"]
        assert "FROM (SELECT order_no, cust_code FROM ods.t) s" in new_sql

    def test_union_refused(self):
        """UNION（多支按位对齐）拒改——只重排第一支会破坏两支对齐。"""
        sql = ("SELECT s.cust_code, s.order_no FROM ods.t1 s "
               "UNION ALL SELECT t.cust_code, t.order_no FROM ods.t2 t")
        new_sql, notes = reorder(sql, ["order_no", "cust_code"])
        assert new_sql == sql and any("UNION" in n for n in notes)


class TestCli:
    def test_end_to_end_write_back_and_dry_run(self, tmp_path):
        ts = _ts()
        ts_path = tmp_path / "ts.json"
        ts_path.write_text(json.dumps(ts), encoding="utf-8")
        sql_path = tmp_path / "R0001.sql"
        sql_path.write_text(_SQL, encoding="utf-8")
        # dry-run 不改文件
        r = subprocess.run([sys.executable, str(SCRIPT), "--sql", str(sql_path),
                            "--ts", str(ts_path), "--rule", "R0001", "--dry-run"],
                           capture_output=True, text=True)
        assert r.returncode == 0 and "未写回" in r.stdout
        assert "s.cust_code," in sql_path.read_text(encoding="utf-8")   # 原文未动
        # 写回
        r2 = subprocess.run([sys.executable, str(SCRIPT), "--sql", str(sql_path),
                             "--ts", str(ts_path), "--rule", "R0001"],
                            capture_output=True, text=True)
        assert r2.returncode == 0 and "已写回" in r2.stdout
        written = sql_path.read_text(encoding="utf-8")
        from sql_parse import split_top_projection_items
        assert [n for n, _ in split_top_projection_items(written)] \
            == ["order_no", "cust_code", "amount", "dw_last_update_date"]
        # 幂等：再跑零改动
        r3 = subprocess.run([sys.executable, str(SCRIPT), "--sql", str(sql_path),
                             "--ts", str(ts_path), "--rule", "R0001"],
                            capture_output=True, text=True)
        assert "零改动" in r3.stdout

    def test_unknown_rule_fails_loud(self, tmp_path):
        ts_path = tmp_path / "ts.json"
        ts_path.write_text(json.dumps(_ts()), encoding="utf-8")
        (tmp_path / "x.sql").write_text(_SQL, encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), "--sql", str(tmp_path / "x.sql"),
                            "--ts", str(ts_path), "--rule", "NOPE"],
                           capture_output=True, text=True)
        assert r.returncode == 2 and "没有规则" in r.stderr
