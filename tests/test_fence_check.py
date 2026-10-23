"""fence_check 测试：声明驱动的冻结层比对（docs/specs/opt/03 §三，add_field 矩阵）。

不连库。baseline 用 assemble_ts_baseline 现场组装 demo fixture；ts_v2 用
copy.deepcopy(baseline) + 显式施加声明变更构造——测试的就是"恰好等于"双向性。
"""
import copy
import json
from pathlib import Path

import pytest

from assemble_ts_baseline import build_ts_baseline
from fence_check import check, decompose_diff, main

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"


@pytest.fixture(scope="module")
def baseline():
    demo = json.loads((FIXTURES / "baseline_v1_demo_full.json").read_text(encoding="utf-8"))
    ts, _ = build_ts_baseline(demo)
    return ts


def make_cr(fields=("channel_name",)):
    return {"change_type": "add_field", "asset": "dws.dwb_trade_order_d",
            "fields": [{"field": f, "cn": f, "type": "VARCHAR(64)",
                        "source": {"table": "dim_channel", "alias": "c", "field": f},
                        "new_source_table": True} for f in fields],
            "backfill": "pending"}


def apply_declared_change(v2: dict, *, field="channel_name", table="dwb_trade_order_d",
                          placed=("R0002",), intermediates=(), new_joins=(),
                          with_change_section=True, with_field=True, with_targets=True):
    """往 deepcopy 的 baseline 上施加一个'合规'的声明变更。"""
    if with_field:
        v2["tables"][table]["fields"].append({
            "target_field": field, "field_type": "VARCHAR(64)", "field_comment": field,
            "transform_type": "direct",
            "source_fields": [{"table": "dim_channel", "field": field, "alias": "c"}],
            "design_logic": ""})
        v2["meta"]["field_count"] = {  # 派生计数随动
            "business": v2["meta"]["field_count"]["business"] + 1,
            "audit": 0, "total": v2["meta"]["field_count"]["total"] + 1}
    for t in intermediates:
        v2["tables"][t]["fields"].append({
            "target_field": field, "field_type": "", "field_comment": "",
            "transform_type": "direct", "source_fields": [], "design_logic": ""})
    for r in placed:
        if with_targets:
            v2["rules"][r]["field_targets"] = sorted(set(v2["rules"][r]["field_targets"]) | {field})
    for j in new_joins:
        r = j["rule"]
        v2["rules"][r]["source_tables"].append(
            {"schema": j.get("schema", "dws"), "table": j["table"], "alias": j["alias"]})
        v2["rules"][r]["joins"].append(
            {"alias": j["alias"], "type": "LEFT", "condition": j.get("on", ""), "filter": ""})
    declared_tables = {j["table"] for j in new_joins}
    if declared_tables:
        v2["meta"]["source_tables"].append(
            {"schema": "dws", "table": sorted(declared_tables)[0], "table_cn": "", "alias": ""})
        v2["data_flow"]["tables"].append(
            {"schema": "dws", "name": sorted(declared_tables)[0],
             "role": "source", "layer": "DIM", "is_view": False})
    if with_change_section:
        v2["change"] = {"change_type": "add_field", "fields": [{
            "field": field, "target_table": table, "placed_rules": list(placed),
            "intermediate_tables": list(intermediates), "new_joins": list(new_joins)}]}
    return v2


class TestDecompose:
    def test_identical_yields_empty(self, baseline):
        d = decompose_diff(baseline, copy.deepcopy(baseline))
        assert d["added_fields"] == [] and d["rule_changes"] == {} and d["meta_changes"] == []

    def test_addition_detected(self, baseline):
        v2 = apply_declared_change(copy.deepcopy(baseline))
        d = decompose_diff(baseline, v2)
        assert ("dwb_trade_order_d", "channel_name") in d["added_fields"]
        assert set(d["rule_changes"]) == {"R0002"}


class TestFencePass:
    def test_same_source_direct_pass(self, baseline):
        """A 形态合规：直挂 R0002、无新 JOIN。"""
        v2 = apply_declared_change(copy.deepcopy(baseline))
        assert check(baseline, v2, make_cr()) == []

    def test_new_join_pass(self, baseline):
        """B 形态合规：新 JOIN dim_channel 挂 R0002。"""
        v2 = apply_declared_change(copy.deepcopy(baseline),
                                   new_joins=[{"rule": "R0002", "table": "dim_channel",
                                               "alias": "c", "on": "t.order_id=c.order_id"}])
        assert check(baseline, v2, make_cr()) == []

    def test_intermediate_chain_pass(self, baseline):
        """C 形态合规：穿中间表（R0001 写 tmp、R0002 读）。"""
        v2 = apply_declared_change(copy.deepcopy(baseline), placed=("R0001", "R0002"),
                                   intermediates=("tmp_trade_order",),
                                   new_joins=[{"rule": "R0001", "table": "dim_channel",
                                               "alias": "c", "on": "a.order_id=c.order_id"}])
        assert check(baseline, v2, make_cr()) == []

    def test_main_pass(self, baseline, tmp_path):
        v2 = apply_declared_change(copy.deepcopy(baseline))
        b = tmp_path / "b.json"; v = tmp_path / "v.json"; c = tmp_path / "cr.json"
        b.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
        v.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")
        c.write_text(json.dumps(make_cr(), ensure_ascii=False), encoding="utf-8")
        assert main(["--ts-baseline", str(b), "--ts-v2", str(v),
                     "--change-request", str(c)]) == 0


class TestOverreach:
    def test_undeclared_field(self, baseline):
        v2 = apply_declared_change(copy.deepcopy(baseline), field="channel_name")
        # 再偷加一个未声明字段
        v2["tables"]["dwb_trade_order_d"]["fields"].append(
            {"target_field": "secret_col", "field_type": "INT", "field_comment": "",
             "transform_type": "direct", "source_fields": [], "design_logic": ""})
        v2["rules"]["R0002"]["field_targets"].append("secret_col")
        vs = check(baseline, v2, make_cr())
        assert any("secret_col" in v["message"] and v["type"] == "overreach" for v in vs)

    def test_modify_existing_field(self, baseline):
        v2 = apply_declared_change(copy.deepcopy(baseline))
        f = next(x for x in v2["tables"]["dwb_trade_order_d"]["fields"]
                 if x["target_field"] == "total_amount")
        f["field_comment"] = "顺手改了注释"
        vs = check(baseline, v2, make_cr())
        assert any("total_amount" in v["message"] and "存量字段定义被修改" in v["message"] for v in vs)

    def test_remove_existing_field(self, baseline):
        v2 = apply_declared_change(copy.deepcopy(baseline))
        v2["tables"]["dwb_trade_order_d"]["fields"] = [
            x for x in v2["tables"]["dwb_trade_order_d"]["fields"]
            if x["target_field"] != "cust_id"]
        vs = check(baseline, v2, make_cr())
        assert any("cust_id" in v["message"] and "删除存量字段" in v["message"] for v in vs)

    def test_frozen_rule_aspect(self, baseline):
        v2 = apply_declared_change(copy.deepcopy(baseline))
        v2["rules"]["R0002"]["load_mode"] = "merge_into"   # 顺手改写入方式
        vs = check(baseline, v2, make_cr())
        assert any("R0002.load_mode" in v["message"] for v in vs)

    def test_unplaced_rule_touched(self, baseline):
        """未落位规则（R0001）被改——白名单槽位也不行（它没有声明）。"""
        v2 = apply_declared_change(copy.deepcopy(baseline))
        v2["rules"]["R0001"]["field_targets"].append("channel_name")
        vs = check(baseline, v2, make_cr())
        assert any("R0001" in v["message"] and "field_targets" in v["message"] for v in vs)

    def test_undeclared_join(self, baseline):
        v2 = apply_declared_change(copy.deepcopy(baseline))
        v2["rules"]["R0002"]["joins"].append(
            {"alias": "x", "type": "LEFT", "condition": "t.id=x.id", "filter": ""})
        v2["rules"]["R0002"]["source_tables"].append(
            {"schema": "dws", "table": "dim_x", "alias": "x"})
        vs = check(baseline, v2, make_cr())
        assert any("dim_x" in v["message"] or "joins" in v["message"] for v in vs)

    def test_rule_added(self, baseline):
        v2 = apply_declared_change(copy.deepcopy(baseline))
        v2["rules"]["R0009"] = dict(v2["rules"]["R0002"])
        vs = check(baseline, v2, make_cr())
        assert any("R0009" in v["message"] and "规则被新增" in v["message"] for v in vs)

    def test_dq_added_blocked_with_note(self, baseline):
        v2 = apply_declared_change(copy.deepcopy(baseline))
        v2["dq_rules"].append({"scope": "字段级", "check_type": "空值检查",
                               "rule_name": "x", "rule_desc": "y"})
        vs = check(baseline, v2, make_cr())
        assert any("DQ" in v["message"] for v in vs)

    def test_init_changed(self, baseline):
        v2 = apply_declared_change(copy.deepcopy(baseline))
        v2["init"]["mode"] = "derive"
        vs = check(baseline, v2, make_cr())
        assert any("init" in v["message"] for v in vs)

    def test_main_exit_1(self, baseline, tmp_path, capsys):
        v2 = apply_declared_change(copy.deepcopy(baseline))
        v2["rules"]["R0002"]["load_mode"] = "merge_into"
        b = tmp_path / "b.json"; v = tmp_path / "v.json"; c = tmp_path / "cr.json"
        b.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
        v.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")
        c.write_text(json.dumps(make_cr(), ensure_ascii=False), encoding="utf-8")
        assert main(["--ts-baseline", str(b), "--ts-v2", str(v),
                     "--change-request", str(c)]) == 1
        assert "FENCE_BLOCKED" in capsys.readouterr().err


class TestMissing:
    def test_declared_field_not_landed(self, baseline):
        """声明了但没加进目标表——漏改。"""
        v2 = apply_declared_change(copy.deepcopy(baseline), with_field=False)
        vs = check(baseline, v2, make_cr())
        assert any(v["type"] == "missing" and "channel_name" in v["message"] for v in vs)

    def test_declared_not_in_targets(self, baseline):
        v2 = apply_declared_change(copy.deepcopy(baseline), with_targets=False)
        vs = check(baseline, v2, make_cr())
        assert any(v["type"] == "missing" and "field_targets" in v["message"] for v in vs)

    def test_cr_field_not_picked_up(self, baseline):
        """change_request 两个字段，change 段只落位一个——漏接。"""
        v2 = apply_declared_change(copy.deepcopy(baseline))
        vs = check(baseline, v2, make_cr(fields=("channel_name", "extra_flag")))
        assert any(v["type"] == "missing" and "extra_flag" in v["message"] for v in vs)

    def test_change_smuggling(self, baseline):
        """change 段声明了 change_request 里没有的字段——设计夹带。"""
        v2 = apply_declared_change(copy.deepcopy(baseline))
        vs = check(baseline, v2, make_cr(fields=()))   # cr 为空
        assert any("设计夹带" in v["message"] for v in vs)


class TestUnsupported:
    def test_unsupported_change_type(self, baseline):
        v2 = apply_declared_change(copy.deepcopy(baseline))
        v2["change"]["change_type"] = "drop_field"
        vs = check(baseline, v2, make_cr())
        assert any(v["type"] == "unsupported" for v in vs)


def _cr_mod():
    """纯类型修改场景的 change_request（与 _mod 的声明一致）。"""
    return {"change_type": "add_field", "asset": "dws.dwb_trade_order_d", "fields": [],
            "modify_type_fields": [{"field": "order_id", "old_type": "VARCHAR(64)",
                                    "new_type": "VARCHAR(128)"}], "backfill": "pending"}


class TestModifyTypeFence:
    """场景 B（2026-10-22 第二刀）：类型修改恰好性——声明的(表,字段)允许
    field_type 变且恰好=声明新类型；非类型键变仍冻结；未声明照拦；漏改=missing。"""

    def _mod(self, v2, field="order_id", new_type="VARCHAR(128)", also_comment=False):
        for f in v2["tables"]["dwb_trade_order_d"]["fields"]:
            if f["target_field"] == field:
                f["field_type"] = new_type
                if also_comment:
                    f["field_comment"] = "被顺手改了"
        v2["change"] = {"change_type": "add_field", "backfill": "no", "fields": [],
                        "modify_types": [{"field": field, "target_table": "dwb_trade_order_d",
                                          "old_type": "VARCHAR(64)", "new_type": new_type}]}

    def test_declared_type_change_passes(self, baseline):
        v2 = copy.deepcopy(baseline)
        self._mod(v2)
        violations = check(baseline, v2, _cr_mod())
        assert not [v for v in violations if "order_id" in v["message"]], violations

    def test_comment_also_changed_blocks(self, baseline):
        v2 = copy.deepcopy(baseline)
        self._mod(v2, also_comment=True)
        violations = check(baseline, v2, _cr_mod())
        assert any("非类型键" in v["message"] for v in violations), violations

    def test_undeclared_type_change_blocks(self, baseline):
        v2 = copy.deepcopy(baseline)
        self._mod(v2)
        v2["change"]["modify_types"] = []  # 撤声明
        violations = check(baseline, v2, _cr_mod())
        assert any("存量字段定义被修改" in v["message"] and "order_id" in v["message"]
                   for v in violations), violations

    def test_declared_no_landing_missing(self, baseline):
        v2 = copy.deepcopy(baseline)
        v2["change"] = {"change_type": "add_field", "backfill": "no", "fields": [],
                        "modify_types": [{"field": "order_id", "target_table": "dwb_trade_order_d",
                                          "old_type": "VARCHAR(64)", "new_type": "VARCHAR(128)"}]}
        violations = check(baseline, v2, _cr_mod())
        assert any(v["type"] == "missing" and "order_id" in v["message"] for v in violations)

    def test_landing_type_differs_from_declaration_blocks(self, baseline):
        v2 = copy.deepcopy(baseline)
        self._mod(v2, new_type="VARCHAR(256)")
        v2["change"]["modify_types"][0]["new_type"] = "VARCHAR(128)"  # 落地 256 ≠ 声明 128
        violations = check(baseline, v2, _cr_mod())
        assert any("恰好性" in v["message"] for v in violations), violations


class TestModifyLogicFence:
    """第三刀（2026-10-22）：口径修改围栏——声明字段 logic 许变/桶归属许迁；未声明
    的口径被改=越界；双向对账 ts.change ↔ change_request。"""

    def _pair(self, baseline):
        """(带桶的 baseline, 它的 deepcopy v2)——两侧同源，diff 只显施加的变更。"""
        b = copy.deepcopy(baseline)
        b["rules"]["R0002"]["fields"] = {
            "processed": [{"target": "order_amt", "logic": "a.order_amt",
                           "refs": ["a.order_amt"]}],
            "assign": [], "direct": ["a.order_id AS order_id"]}
        return b, copy.deepcopy(b)

    def _cr(self, fields=("channel_name",), mlogics=("order_amt",)):
        cr = make_cr(fields)
        cr["modify_logic_fields"] = [{"field": f, "old_expr": "", "new_expr": "",
                                      "rules": ["R0002"]} for f in mlogics]
        return cr

    def test_declared_logic_change_passes(self, baseline):
        b, v2 = self._pair(baseline)
        v2["rules"]["R0002"]["fields"]["processed"][0]["logic"] = "nvl(a.order_amt, 0)"
        v2["change"] = {"change_type": "add_field", "backfill": "no", "fields": [],
                        "modify_logics": [{"field": "order_amt", "target_table": "dwb_trade_order_d",
                                           "old_logic": "a.order_amt", "new_logic": "nvl(a.order_amt, 0)",
                                           "rules": ["R0002"]}]}
        violations = check(b, v2, self._cr())
        assert not [v for v in violations if "order_amt" in v["message"]], violations

    def test_undeclared_logic_change_blocks(self, baseline):
        b, v2 = self._pair(baseline)
        v2["rules"]["R0002"]["fields"]["processed"][0]["logic"] = "偷偷改了"
        v2["change"] = {"change_type": "add_field", "backfill": "no", "fields": []}
        violations = check(b, v2, self._cr(mlogics=()))
        assert any("口径（logic）被修改" in v["message"] for v in violations), violations

    def test_declared_direct_migration_passes(self, baseline):
        b, v2 = self._pair(baseline)
        bf = v2["rules"]["R0002"]["fields"]
        bf["direct"] = [d for d in bf["direct"] if d != "a.order_id AS order_id"]
        bf["processed"].append({"target": "order_id", "logic": "nvl(a.order_id,0)", "refs": []})
        v2["change"] = {"change_type": "add_field", "backfill": "no", "fields": [],
                        "modify_logics": [{"field": "order_id", "target_table": "dwb_trade_order_d",
                                           "old_logic": "a.order_id AS order_id",
                                           "new_logic": "nvl(a.order_id,0)", "rules": ["R0002"]}]}
        cr = self._cr()
        cr["modify_logic_fields"].append({"field": "order_id", "old_expr": "",
                                          "new_expr": "", "rules": ["R0002"]})
        violations = check(b, v2, cr)
        assert not [v for v in violations if "order_id" in v["message"]], violations

    def test_design_smuggling_blocks(self, baseline):
        """ts.change 的 modify_logics 声明了 cr 没有的字段=设计夹带。"""
        b, v2 = self._pair(baseline)
        v2["change"] = {"change_type": "add_field", "backfill": "no", "fields": [],
                        "modify_logics": [{"field": "ghost", "target_table": "dwb_trade_order_d",
                                           "old_logic": "", "new_logic": "x", "rules": []}]}
        violations = check(b, v2, self._cr(mlogics=()))
        assert any("设计夹带" in v["message"] for v in violations)
