"""gate_summary_opt 测试：闸口①' 材料一屏（确定性产出）。"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "opt-pipe" / "scripts"))
sys.path.insert(0, str(REPO / "skills" / "design-dev-shared" / "scripts"))

from gate_summary_opt import render


def _v2():
    return {"meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_x_d"}}},
            "change": {"change_type": "add_field", "backfill": "pending", "fields": [
                {"field": "channel_name", "field_type": "VARCHAR(64)",
                 "placed_rules": ["R0002"], "design_logic": "a.order 关联取 c.name",
                 "intermediate_tables": [],
                 "new_joins": [{"rule": "R0002", "schema": "dws", "table": "dim_channel",
                                "alias": "c", "join_type": "LEFT", "on": "t.id = c.id",
                                "join_safety": {"join_key_unique": True,
                                                "strategy": "直接关联", "reason": "主键"}}],
                 "decision": "原始输入='直接复制'，已人定"}]}}


def _cr():
    return {"version": "202608", "change_type": "add_field",
            "change_log_summary": {"date": "2026-08-21", "ver": "v2.0", "desc": "优化：新增渠道字段"},
            "fields": [{"field": "channel_name", "source": {"table": "dim_channel"},
                        "new_source_table": True}],
            "backfill": "pending", "unsupported_changes": [],
            "join_type_decisions": [{"condition": "t.id=c.id", "decision": "转换",
                                     "reason": ""}]}


def test_renders_all_sections():
    text = render(_v2(), {}, _cr())
    assert "闸口①' 材料摘要" in text and "dwb_x_d" in text
    assert "channel_name" in text and "R0002" in text
    assert "新来源" in text and "dim_channel" in text
    assert "新 JOIN" in text and "t.id = c.id" in text
    assert "✔已人定" in text, "决策标记要亮给人"
    assert "回刷" in text and "pending" in text
    assert "关联键" in text and "转换" in text


def test_no_join_no_section():
    v2 = _v2()
    v2["change"]["fields"][0]["new_joins"] = []
    text = render(v2, {}, _cr())
    assert "新 JOIN" not in text



class TestChangeEntriesAndRenames:
    """2026-11-12 #4 处置：change_entries 逐条并排渲染（兑现闸口材料承诺）+renames 登记。"""

    def test_change_entries_table_rendered(self):
        import gate_summary_opt as g
        v2 = {"change": {"fields": [], "backfill": "no"}, "tables": {}}
        baseline = {"tables": {}}
        cr = {"version": "202611", "change_type": "add_field", "fields": [],
              "change_entries": [
                  {"seq": 1, "time": "202611", "page": "attr", "group": "g1",
                   "key": "channel_name", "column": "映射表达式", "ctype": "MODIFY",
                   "before": "旧口径", "after": "新口径"}],
              "renames": [{"kind": "rename", "group": "g1", "old": "x1",
                           "new": "x2", "seq": "3+4", "after_raw": "x2"}]}
        text = g.render(v2, baseline, cr)
        assert "变更条目并排" in text and "旧口径 → 新口径" in text
        assert "改名合成对" in text and "x1 → x2" in text
