"""diagnose_fanout_opt 测试：逐表键唯一性主判据 + join_safety 断言对照（fake executor，不连库）。"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "opt-pipe" / "scripts"))
sys.path.insert(0, str(REPO / "skills" / "design-dev-shared" / "scripts"))

from diagnose_fanout_opt import check_rule, render, placed_rule_codes


def mk_rule():
    return {
        "source_tables": [
            {"schema": "ods", "table": "ods_order", "alias": "a"},
            {"schema": "dws", "table": "dim_channel", "alias": "c"},
        ],
        "joins": [
            {"alias": "c", "type": "LEFT", "condition": "a.order_id = c.order_id", "filter": ""},
        ],
        "join_safety": [
            {"table": "dim_channel", "join_key_unique": True,
             "strategy": "直接关联", "reason": "维表主键"},
        ],
    }


class FakeEx:
    def __init__(self, results):
        self.results = results  # [(match_substr, rows)]

    def fetch_all(self, sql):
        for key, rows in self.results:
            if key in sql:
                return rows
        return []


class TestCheckRule:
    def test_unique_passes(self):
        ex = FakeEx([("COUNT(DISTINCT order_id)", [{"total": 100, "dist": 100}])])
        entries = check_rule(ex, "R0001", mk_rule())
        assert entries and entries[0]["status"] == "UNIQUE"
        assert "不发散" in entries[0]["detail"]

    def test_dup_falsifies_declaration(self):
        ex = FakeEx([
            ("COUNT(DISTINCT order_id)", [{"total": 100, "dist": 80}]),
            ("GROUP BY order_id", [{"order_id": "O1", "n": 20}]),
        ])
        entries = check_rule(ex, "R0001", mk_rule())
        e = entries[0]
        assert e["status"] == "DUP" and e["dup"] == 20
        assert "证伪 join_safety 声明" in e["detail"]
        assert e["samples"]

    def test_filter_from_safety_applied(self):
        """声明 join_filter 的按条件过滤（维表有效记录语义）。"""
        rule = mk_rule()
        rule["join_safety"][0]["join_filter"] = "del_flag = 'N'"
        ex = FakeEx([("WHERE del_flag", [{"total": 50, "dist": 50}])])
        entries = check_rule(ex, "R0001", rule)
        assert entries[0]["status"] == "UNIQUE"

    def test_query_error_reported(self):
        class ErrEx:
            def fetch_all(self, sql):
                raise RuntimeError("relation does not exist")
        entries = check_rule(ErrEx(), "R0001", mk_rule())
        assert entries[0]["status"] == "ERROR"
        assert "does not exist" in entries[0]["detail"]


class TestAssertionKeys:
    def test_alias_keyed_declaration_falsified(self):
        """adopt 档 join_safety 按 alias 键（new-pipe 关联级化形态）——断言对照双键皆认。"""
        rule = mk_rule()
        rule["join_safety"] = [{"alias": "c", "join_key_unique": True,
                                "strategy": "直接关联", "reason": "维表主键"}]
        ex = FakeEx([
            ("COUNT(DISTINCT order_id)", [{"total": 100, "dist": 80}]),
            ("GROUP BY order_id", [{"order_id": "O1", "n": 20}]),
        ])
        entries = check_rule(ex, "R0001", rule)
        assert "证伪 join_safety 声明" in entries[0]["detail"]


class TestPlacedScope:
    """--placed 断言对照（批2）：增量血缘路径规则集——新字段落位 ∪ 中间表产出 ∪ 口径修改所在；
    其余存量规则冻结不测（按需点亮，不全量重测）。"""

    def test_placed_rule_codes_union(self):
        ts = {
            "rules": {
                "R0001": {"target_table": "dws.tmp_x"},
                "R0002": {"target_table": "dws.t_f"},
                "R0003": {"target_table": "dws.t_f",
                          "fields": {"processed": [{"target": "amt", "logic": "nvl(a.amt,0)"}]}},
                "R0004": {"target_table": "dws.t_other"},
            },
            "change": {
                "fields": [{"placed_rules": ["R0002"], "intermediate_tables": ["tmp_x"]}],
                "modify_logics": [{"field": "amt"}],
            },
        }
        assert placed_rule_codes(ts) == ["R0001", "R0002", "R0003"]   # R0004 冻结不测

    def test_placed_empty_when_no_change(self):
        assert placed_rule_codes({"rules": {"R0001": {"target_table": "t"}}, "change": {}}) == []


class TestRender:
    def test_render_contains_verdict_and_axiom(self):
        ex = FakeEx([("COUNT(DISTINCT order_id)", [{"total": 10, "dist": 8}]),
                     ("GROUP BY order_id", [{"order_id": "O1", "n": 2}])])
        text = render("R0001", check_rule(ex, "R0001", mk_rule()))
        assert "不唯一" in text and "证伪" in text
        assert "任何数据不膨胀" in text, "判据口径要亮给人"
