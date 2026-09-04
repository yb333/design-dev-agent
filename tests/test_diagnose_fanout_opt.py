"""diagnose_fanout_opt 测试：逐表键唯一性主判据 + join_safety 断言对照（fake executor，不连库）。"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "opt-pipe" / "scripts"))
sys.path.insert(0, str(REPO / "skills" / "design-dev-shared" / "scripts"))

from diagnose_fanout_opt import check_rule, render


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


class TestRender:
    def test_render_contains_verdict_and_axiom(self):
        ex = FakeEx([("COUNT(DISTINCT order_id)", [{"total": 10, "dist": 8}]),
                     ("GROUP BY order_id", [{"order_id": "O1", "n": 2}])])
        text = render("R0001", check_rule(ex, "R0001", mk_rule()))
        assert "不唯一" in text and "证伪" in text
        assert "任何数据不膨胀" in text, "判据口径要亮给人"
