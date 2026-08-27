"""pick_fields 桶化查询测试（fields 三桶：processed/assign/direct）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "dws-coding" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "design-dev-shared" / "scripts"))

from pick_fields import query_list, query_alias, query_field


def _sliced(fields=None, sources=None):
    """桶形态切片 fixture。"""
    return {
        "rule_code": "R0001", "rule_name": "测试规则",
        "fields": fields or {
            "processed": [{"target": "total_amt", "logic": "按 a.amt 汇总", "refs": ["a.amt"]}],
            "assign": [{"target": "crt_cycle_id", "value": "'${P_CYCLE_ID}'"},
                       {"target": "dw_last_update_date", "value": "CURRENT_TIMESTAMP"},
                       {"target": "del_flag", "value": "'N'"}],
            "direct": ["t.contract_no", "t.cust_id AS user_id", "u.delete_flag"],
        },
        "source_tables": sources or [
            {"schema": "ods", "table": "ods_a", "alias": "t"},
            {"schema": "ods", "table": "ods_u", "alias": "u"},
        ],
    }


class TestQueryList:
    def test_direct_distribution_by_alias(self):
        out = query_list(_sliced())
        assert "t" in out and "(ods.ods_a)" in out and "2 个" in out
        assert "u" in out and "1 个" in out

    def test_processed_listed(self):
        assert "total_amt" in query_list(_sliced())

    def test_summary_counts(self):
        out = query_list(_sliced())
        assert "直取 3" in out and "加工 1" in out and "含审计 3" in out

    def test_no_direct_note(self):
        fields = {"processed": [{"target": "x", "logic": "l", "refs": []}],
                  "assign": [], "direct": []}
        assert "无直取字段" in query_list(_sliced(fields))


class TestQueryAlias:
    def test_returns_pasteable_lines(self):
        out = query_alias(_sliced(), "t")
        assert "t.contract_no," in out and "t.cust_id AS user_id," in out
        assert "u.delete_flag" not in out  # 别名隔离

    def test_unknown_alias_hints(self):
        out = query_alias(_sliced(), "zz")
        assert "未找到" in out and "t" in out and "u" in out

    def test_alias_exists_no_direct(self):
        fields = {"processed": [{"target": "p", "logic": "l", "refs": []}],
                  "assign": [], "direct": []}
        assert "存在但无直取字段" in query_alias(_sliced(fields), "t")


class TestQueryField:
    def test_processed_shows_logic_and_refs(self):
        out = query_field(_sliced(), "total_amt")
        assert "加工" in out and "按 a.amt 汇总" in out and "a.amt" in out

    def test_assign_shows_value(self):
        out = query_field(_sliced(), "crt_cycle_id")
        assert "赋值" in out and "${P_CYCLE_ID}" in out

    def test_direct_shows_line(self):
        assert "t.cust_id AS user_id" in query_field(_sliced(), "user_id")

    def test_case_insensitive(self):
        assert "汇总" in query_field(_sliced(), "TOTAL_AMT")

    def test_unknown_fuzzy_hint(self):
        out = query_field(_sliced(), "contract")
        assert "未找到" in out and "contract_no" in out
