"""assemble_ts_opt 测试：ts_baseline + 增量 decisions → ts_v2（docs/specs/opt/04 §二）。

集成验证闭环：产出 ts_v2 必须过 fence_check（组装器与围栏是同一契约的两端）。
不连库；baseline 由 demo fixture 现场组装。
"""
import copy
import json
from pathlib import Path

import pytest
import yaml

from assemble_ts_baseline import build_ts_baseline
from assemble_ts_opt import load_decisions, validate_decisions, apply_decisions, main
from fence_check import check

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"


@pytest.fixture(scope="module")
def baseline():
    demo = json.loads((FIXTURES / "baseline_v1_demo_full.json").read_text(encoding="utf-8"))
    ts, _ = build_ts_baseline(demo)
    return ts


def dec_direct():
    return {
        "change_type": "add_field", "backfill": "pending",
        "fields": [{
            "field": "pay_channel", "target_table": "dwb_trade_order_d",
            "placed_rules": ["R0002"], "intermediate_tables": [],
            "field_type": "VARCHAR(64)", "field_comment": "支付渠道",
            "design_logic": "支付渠道编码直取", "transform_type": "direct",
            "source": {"table": "ods.ods_trade_order_di", "alias": "a", "field": "pay_channel"},
            "new_joins": [],
        }],
    }


def dec_new_join():
    d = dec_direct()
    d["fields"][0] = {
        "field": "channel_name", "target_table": "dwb_trade_order_d",
        "placed_rules": ["R0002"], "intermediate_tables": [],
        "field_type": "VARCHAR(64)", "field_comment": "渠道名称",
        "design_logic": "按订单关联渠道维表取渠道名称", "transform_type": "direct",
        "source": {"table": "dws.dim_channel", "alias": "c", "field": "channel_name"},
        "new_joins": [{
            "rule": "R0002", "schema": "dws", "table": "dim_channel", "alias": "c",
            "join_type": "LEFT", "on": "t.order_id = c.order_id",
            "join_safety": {"join_key_unique": True, "strategy": "直接关联",
                            "join_filter": "", "reason": "维表主键关联不发散"},
        }],
    }
    return d


def cr_for(*fields):
    return {"change_type": "add_field", "asset": "dws.dwb_trade_order_d",
            "fields": [{"field": f, "cn": f, "type": "VARCHAR(64)",
                        "source": {"table": "dim_channel", "alias": "c", "field": f},
                        "new_source_table": True} for f in fields],
            "backfill": "pending"}


class TestApplyAndFenceIntegration:
    def test_direct_passes_fence(self, baseline):
        v2 = apply_decisions(baseline, dec_direct())
        assert check(baseline, v2, cr_for("pay_channel")) == []

    def test_new_join_passes_fence(self, baseline):
        v2 = apply_decisions(baseline, dec_new_join())
        assert check(baseline, v2, cr_for("channel_name")) == []

    def test_baseline_not_mutated(self, baseline):
        snap = json.dumps(baseline, sort_keys=True)
        apply_decisions(baseline, dec_new_join())
        assert json.dumps(baseline, sort_keys=True) == snap, "组装不得污染 baseline"

    def test_change_section_shape(self, baseline):
        v2 = apply_decisions(baseline, dec_new_join())
        ch = v2["change"]
        assert ch["change_type"] == "add_field"
        f = ch["fields"][0]
        assert f["field"] == "channel_name" and f["placed_rules"] == ["R0002"]
        assert f["new_joins"][0]["table"] == "dim_channel"
        assert "join_safety" not in f["new_joins"][0], "change 段不带 safety 细节（落 ts 规则里）"

    def test_join_safety_landed_on_rule(self, baseline):
        v2 = apply_decisions(baseline, dec_new_join())
        js = v2["rules"]["R0002"]["join_safety"]
        assert any(x["table"] == "dim_channel" and x["join_key_unique"] for x in js)

    def test_intermediate_chain(self, baseline):
        d = dec_new_join()
        f = d["fields"][0]
        f["placed_rules"] = ["R0001", "R0002"]
        f["intermediate_tables"] = ["tmp_trade_order"]
        f["new_joins"][0]["rule"] = "R0001"
        v2 = apply_decisions(baseline, d)
        assert "channel_name" in {x["target_field"]
                                  for x in v2["tables"]["tmp_trade_order"]["fields"]}
        assert check(baseline, v2, cr_for("channel_name")) == []


class TestValidationFailLoud:
    def test_existing_field_rejected(self, baseline, tmp_path):
        d = dec_direct()
        d["fields"][0]["field"] = "order_id"
        p = tmp_path / "d.yaml"
        p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p), baseline)

    def test_join_safety_required(self, baseline, tmp_path):
        d = dec_new_join()
        d["fields"][0]["new_joins"][0].pop("join_safety")
        p = tmp_path / "d.yaml"
        p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p), baseline)

    def test_join_safety_reason_required(self, baseline, tmp_path):
        """批2 断言对齐（2026-10-23）：reason 空=只有声明没有依据句——硬拦
        （与新建评估层同款：先取证后断言，实测数字/输入声明/未实测标注）。"""
        d = dec_new_join()
        d["fields"][0]["new_joins"][0]["join_safety"]["reason"] = ""
        p = tmp_path / "d.yaml"
        p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p), baseline)

    def test_join_safety_key_verdict_required(self, baseline, tmp_path):
        """批2：join_key_unique 缺失=断言无结论——硬拦（true/false 必须有）。"""
        d = dec_new_join()
        d["fields"][0]["new_joins"][0]["join_safety"].pop("join_key_unique")
        p = tmp_path / "d.yaml"
        p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p), baseline)

    def test_join_on_unplaced_rule_rejected(self, baseline, tmp_path):
        d = dec_new_join()
        d["fields"][0]["new_joins"][0]["rule"] = "R0001"   # 不在 placed_rules
        p = tmp_path / "d.yaml"
        p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p), baseline)

    def test_missing_required_key(self, baseline, tmp_path):
        d = dec_direct()
        d["fields"][0].pop("design_logic")
        p = tmp_path / "d.yaml"
        p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p), baseline)


class TestMain:
    def test_main_end_to_end(self, baseline, tmp_path):
        d = dec_new_join()
        dp = tmp_path / "d.yaml"
        dp.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        bp = tmp_path / "ts_baseline.json"
        bp.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "ts_v2.json"
        assert main(["--ts-baseline", str(bp), "--decisions", str(dp),
                     "--output", str(out)]) == 0
        v2 = json.loads(out.read_text(encoding="utf-8"))
        assert v2["generated_by"] == "assemble_ts_opt"
        assert check(baseline, v2, cr_for("channel_name")) == [], \
            "main 产出的 ts_v2 必须过围栏（组装器与围栏同契约）"

    def test_main_produces_ts_md_pair(self, baseline, tmp_path):
        """ts.md 成对产出（2026-10-14 彩排实证：_short 提取 str() 包错位导致
        ts.md 渲染自上线起静默失败——档案 ts.json/ts.md 成对是定调，必须断言产物）。"""
        d = dec_new_join()
        dp = tmp_path / "d.yaml"
        dp.write_text(yaml.safe_dump(d), encoding="utf-8")
        bp = tmp_path / "ts_baseline.json"
        bp.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "sub" / "ts_v2.json"
        assert main(["--ts-baseline", str(bp), "--decisions", str(dp),
                     "--output", str(out)]) == 0
        v2 = json.loads(out.read_text(encoding="utf-8"))
        _f = ((v2.get("meta", {}) or {}).get("target", {}) or {}).get("f_table") or {}
        short = _f.get("table") or "ts"
        md = out.parent / f"{short}_ts.md"
        assert md.exists(), f"ts.md 未成对产出: {md}"
        assert "dwb_trade_order_d" in md.read_text(encoding="utf-8")


# ============================================================
# 包2 补强（2026-09-04）：引用门禁（N36 等价）+ 新 JOIN 键类型比对（N_JOIN2 等价）
# ============================================================
class TestLogicRefGate:
    def test_unqualified_identifier_rejected(self, baseline, tmp_path):
        d = dec_direct()
        d["fields"][0]["design_logic"] = "channel_name 直取（渠道编码）"
        p2 = tmp_path / "d.yaml"; p2.write_text(yaml.dump(d, allow_unicode=True))
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p2), baseline)

    def test_three_part_ref_rejected(self, baseline, tmp_path):
        d = dec_direct()
        d["fields"][0]["design_logic"] = "dws.ods_order.pay_channel 直取"
        p2 = tmp_path / "d.yaml"; p2.write_text(yaml.dump(d, allow_unicode=True))
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p2), baseline)

    def test_qualified_and_chinese_pass(self, baseline, tmp_path):
        d = dec_direct()
        d["fields"][0]["design_logic"] = "a.pay_channel 直取（渠道编码，NULL 保留）"
        p2 = tmp_path / "d.yaml"; p2.write_text(yaml.dump(d, allow_unicode=True))
        validate_decisions(load_decisions(p2), baseline)  # 不炸

    def test_fullwidth_note_words_not_flagged(self, baseline, tmp_path):
        d = dec_direct()
        d["fields"][0]["design_logic"] = "NVL(a.pay_channel, '未知')（空值给默认）"
        p2 = tmp_path / "d.yaml"; p2.write_text(yaml.dump(d, allow_unicode=True))
        validate_decisions(load_decisions(p2), baseline)


CACHE_CROSS = {("dws", "dim_channel"): {"order_id": "varchar(20)"},
               ("ods", "ods_trade_order_di"): {"order_id": "numeric(10)"}}

class TestJoinTypeCheck:
    def _dec_with_on(self, on):
        d = dec_new_join()
        d["fields"][0]["new_joins"][0]["on"] = on
        return d

    def _baseline_with_t_alias(self, baseline):
        b = copy.deepcopy(baseline)
        for r in b["rules"].values():
            for s in r.get("source_tables") or []:
                if s.get("alias"):
                    s["alias"] = "t"
                    s["schema"], s["table"] = "ods", "ods_trade_order_di"
        return b

    def test_cross_category_without_cast_rejected(self, baseline, tmp_path):
        d = self._dec_with_on("t.order_id = c.order_id")
        p2 = tmp_path / "d.yaml"; p2.write_text(yaml.dump(d, allow_unicode=True))
        with pytest.raises(SystemExit):
            validate_decisions(load_decisions(p2), self._baseline_with_t_alias(baseline),
                               CACHE_CROSS)

    def test_inline_cast_passes(self, baseline, tmp_path):
        d = self._dec_with_on("t.order_id::varchar(20) = c.order_id")
        p2 = tmp_path / "d.yaml"; p2.write_text(yaml.dump(d, allow_unicode=True))
        validate_decisions(load_decisions(p2), self._baseline_with_t_alias(baseline),
                           CACHE_CROSS)  # 不炸

    def test_same_type_passes(self, baseline, tmp_path):
        cache = {("dws", "dim_channel"): {"order_id": "numeric(10)"},
                 ("ods", "ods_trade_order_di"): {"order_id": "numeric(10)"}}
        d = self._dec_with_on("t.order_id = c.order_id")
        p2 = tmp_path / "d.yaml"; p2.write_text(yaml.dump(d, allow_unicode=True))
        validate_decisions(load_decisions(p2), self._baseline_with_t_alias(baseline), cache)

    def test_no_cache_degrades_silently(self, baseline, tmp_path):
        d = self._dec_with_on("t.order_id = c.order_id")
        p2 = tmp_path / "d.yaml"; p2.write_text(yaml.dump(d, allow_unicode=True))
        validate_decisions(load_decisions(p2), self._baseline_with_t_alias(baseline), None)


class TestStableOrdering:
    def test_field_targets_append_preserves_baseline_order(self, baseline):
        """保序追加（行级 diff 友好）：baseline 乱序 field_targets 不被重排，新字段尾部追加。"""
        import copy
        from assemble_ts_opt import apply_decisions as _apply
        b = copy.deepcopy(baseline)
        # 人为把 baseline 的 field_targets 改成非 sorted 序（模拟 new-pipe designer 手写序）
        for r in b["rules"].values():
            ft = list(r.get("field_targets") or [])
            if len(ft) >= 2:
                r["field_targets"] = list(reversed(ft))
        dec = {"change_type": "add_field", "backfill": "none", "fields": [{
            "field": "channel_name", "target_table": "dwb_trade_order_d",
            "placed_rules": ["R0002"], "intermediate_tables": [],
            "field_type": "VARCHAR(64)", "field_comment": "渠道",
            "design_logic": "x", "transform_type": "direct", "source": {},
            "new_joins": []}]}
        v2 = _apply(b, dec)
        for code, r in v2["rules"].items():
            base_ft = list(b["rules"][code].get("field_targets") or [])
            got = list(r.get("field_targets") or [])
            if "channel_name" in got:
                assert got[:-1] == base_ft, f"{code}: 存量序被重排（diff 噪音）"
                assert got[-1] == "channel_name", "新字段固定尾部追加"


class TestModifyTypes:
    """场景 B（2026-10-22 第二刀）：decisions.modify_types → tables 终态类型更新 +
    change.modify_types 声明 + fence 集成（组装器与围栏同一契约两端）。"""

    def _dec_mod(self):
        d = dec_direct()
        d["modify_types"] = [{"field": "order_id", "target_table": "dwb_trade_order_d",
                              "old_type": "VARCHAR(64)", "new_type": "VARCHAR(128)",
                              "decision": "扩容/兼容方向，ALTER 自动转换即可"}]
        return d

    def test_apply_lands_type_and_change_section(self, baseline):
        d = self._dec_mod()
        validate_decisions(d, baseline)
        from assemble_ts_opt import validate_modify_types
        validate_modify_types(d, baseline)
        v2 = apply_decisions(baseline, d)
        f = next(x for x in v2["tables"]["dwb_trade_order_d"]["fields"]
                 if x["target_field"] == "order_id")
        assert f["field_type"] == "VARCHAR(128)"
        assert v2["change"]["modify_types"][0]["field"] == "order_id"
        # fence 集成：声明与落地恰好 → 零违规
        cr = {"change_type": "add_field", "asset": "dws.dwb_trade_order_d",
              "fields": [{"field": "pay_channel", "cn": "", "type": "VARCHAR(64)",
                          "source": {"table": "ods.ods_trade_order_di", "alias": "a",
                                     "field": "pay_channel"}, "new_source_table": False}],
              "modify_type_fields": [{"field": "order_id", "old_type": "VARCHAR(64)",
                                      "new_type": "VARCHAR(128)"}], "backfill": "pending"}
        assert not check(baseline, v2, cr), "声明与落地恰好应零违规"

    def test_old_type_mismatch_blocks(self, baseline):
        from assemble_ts_opt import validate_modify_types
        d = self._dec_mod()
        d["modify_types"][0]["old_type"] = "numeric(10,2)"  # baseline 是 varchar
        with pytest.raises(SystemExit):
            validate_modify_types(d, baseline)

    def test_same_type_blocks(self, baseline):
        from assemble_ts_opt import validate_modify_types
        d = self._dec_mod()
        d["modify_types"][0]["new_type"] = "varchar(64)"  # 归一同类型
        with pytest.raises(SystemExit):
            validate_modify_types(d, baseline)


class TestModifyLogics:
    """第三刀（2026-10-22）：口径修改落地——桶条目自动定位（processed 替换 /
    direct→processed 迁移）+ 引用门禁 + fence 集成。"""

    def _baseline_with_bucket(self, baseline):
        """demo 桶为空——给 R0002 注入 order_id 的 direct 条目（测迁移路径）。"""
        b = copy.deepcopy(baseline)
        b["rules"]["R0002"].setdefault("fields", {"processed": [], "assign": [], "direct": []})
        b["rules"]["R0002"]["fields"]["direct"].append("a.order_id AS order_id")
        b["rules"]["R0002"]["fields"]["direct"].append("a.cust_id AS cust_id")
        return b

    def test_direct_migrates_to_processed(self, baseline):
        from assemble_ts_opt import validate_modify_logics, apply_decisions
        b = self._baseline_with_bucket(baseline)
        d = {"change_type": "add_field", "backfill": "pending", "fields": [],
             "modify_logics": [{"field": "order_id", "target_table": "dwb_trade_order_d",
                                "new_logic": "nvl(a.order_id, 0)（空按0）"}]}
        validate_modify_logics(d, b)
        v2 = apply_decisions(b, d)
        buckets = v2["rules"]["R0002"]["fields"]
        assert "a.order_id AS order_id" not in buckets["direct"]  # direct 条目迁走
        assert any(p["target"] == "order_id" and "nvl" in p["logic"]
                   for p in buckets["processed"])
        assert "a.cust_id AS cust_id" in buckets["direct"]  # 其他字段不动
        assert v2["change"]["modify_logics"][0]["rules"] == ["R0002"]

    def test_no_bucket_entry_blocks(self, baseline):
        from assemble_ts_opt import validate_modify_logics
        d = {"modify_logics": [{"field": "order_id", "target_table": "dwb_trade_order_d",
                                "new_logic": "nvl(a.order_id, 0)"}]}
        with pytest.raises(SystemExit):  # demo 桶空 → 无落点
            validate_modify_logics(d, baseline)

    def test_unqualified_logic_blocks(self, baseline):
        from assemble_ts_opt import validate_modify_logics
        b = self._baseline_with_bucket(baseline)
        d = {"modify_logics": [{"field": "order_id", "target_table": "dwb_trade_order_d",
                                "new_logic": "nvl(order_id, 0)"}]}  # 裸引用
        with pytest.raises(SystemExit):
            validate_modify_logics(d, b)
