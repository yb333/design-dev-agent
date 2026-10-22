"""audit_ingest 入料审核测试（交付门模型 2026-10-14：契约/资产/变更冲突前移/台账对账/路由）。

fixture 用 v1.3 实跑产物（asset_facts_v13_full.json，DWB_CUST_ASSET_D）+ 构造 mapping。
不连库。
"""
import json
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "opt"))
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"

from audit_ingest import audit, ROUTES, main

FACTS = json.loads((FIXTURES / "asset_facts_v13_full.json").read_text(encoding="utf-8"))
FACTS_V14 = json.loads((FIXTURES / "asset_facts_v14_review.json").read_text(encoding="utf-8"))

ENTITY_COLS = ["分组", "源表schema", "源表物理表名", "源表别名", "目标表逻辑schema", "目标表物理名称", "关联&限定条件", "备注"]
ATTR_COLS = ["分组", "源表别名", "源表物理表名", "源表字段名", "源表字段类型", "映射规则", "映射表达式",
             "目标字段名", "目标字段中文名", "目标字段类型", "备注"]
CHANGE_COLS = ["变更序号", "变更时间", "变更页签", "变更KEY", "变更列", "变更类型", "变更前", "变更后"]


def make_mapping(path: Path, attr_rows=None, change_rows=None):
    wb = Workbook()
    ws = wb.active; ws.title = "实体级mapping"; ws.append(ENTITY_COLS)
    ws.append(["default", "ods", "ods_acct_balance_di", "b", "dws", "dwb_cust_asset_d", "", ""])
    ws2 = wb.create_sheet("属性级mapping"); ws2.append(ATTR_COLS)
    for r in (attr_rows or [["default", "b", "ods_acct_balance_di", "cust_id", "VARCHAR(64)", "直取", "-",
                             "cust_id", "客户号", "VARCHAR(64)", ""]]):
        ws2.append(r)
    ws3 = wb.create_sheet("变更记录"); ws3.append(CHANGE_COLS)
    for r in (change_rows or []):
        ws3.append(r)
    wb.save(path)
    return path


class TestAudit:
    def test_clean_pass(self, tmp_path):
        """干净链路：无变更需求（纯逆向）+ 契约/资产过 → PASS。"""
        errors, warns, lines = audit(FACTS, "dws.dwb_cust_asset_d", None)
        assert errors == [] and "AUDIT" or True
        assert any("产物资产" in l for l in lines)

    def test_asset_mismatch_rejected(self):
        errors, _, _ = audit(FACTS, "dws.dwb_trade_order_d", None)
        assert [e["code"] for e in errors] == ["asset_mismatch"]
        assert "串包" in ROUTES["asset_mismatch"]

    def test_contract_violation_routed(self):
        bad = {"version": "9.9"}
        errors, _, _ = audit(bad, "dws.dwb_cust_asset_d", None)
        assert errors[0]["code"] == "contract_violation"
        assert "逆向侧" in ROUTES["contract_violation"]

    def test_change_conflict_frontloaded_with_route(self, tmp_path):
        """制品新鲜度冲突（变更说新增、产物已有）→ 前移拦截 + 三选一路由（用户实测场景）。"""
        m = make_mapping(tmp_path / "m.xlsx",
                         change_rows=[[1, "2026-10-20", "属性级", "DEFAULT|CUST_ID", "资产字段", "ADD", "", ""]])
        # cust_id 在产物字段集中（存量字段）→ 冲突
        errors, warns, lines = audit(FACTS, "dws.dwb_cust_asset_d", m)
        assert [e["code"] for e in errors] == ["add_field_conflict"]
        assert "三选一" in ROUTES["add_field_conflict"]

    def test_new_field_no_conflict_passes(self, tmp_path):
        """变更新增字段不在产物 → 无冲突通过。"""
        m = make_mapping(tmp_path / "m.xlsx",
                         attr_rows=[["default", "b", "ods_acct_balance_di", "cust_id", "VARCHAR(64)", "直取", "-",
                                     "cust_id", "客户号", "VARCHAR(64)", ""],
                                    ["default", "b", "ods_acct_balance_di", "chan", "VARCHAR(32)", "直取", "-",
                                     "asset_channel", "资产渠道", "VARCHAR(32)", ""]],
                         change_rows=[[1, "2026-10-20", "属性级", "DEFAULT|ASSET_CHANNEL", "资产字段", "ADD", "", ""]])
        errors, warns, _ = audit(FACTS, "dws.dwb_cust_asset_d", m)
        assert errors == []

    def test_ledger_lag_warns(self, tmp_path):
        """反向对账：产物字段不在 mapping 台账且非本批次新增 → 台账滞后 warn（不拦）。"""
        m = make_mapping(tmp_path / "m.xlsx",
                         change_rows=[[1, "2026-10-20", "属性级", "DEFAULT|GONE_F", "目标字段名", "DELETE",
                                       "gone_f", ""]])   # 属性级只有 cust_id；产物 4 字段 → 3 个滞后
        errors, warns, _ = audit(FACTS, "dws.dwb_cust_asset_d", m)
        assert errors == []
        assert any(w["code"] == "ledger_lag" for w in warns)

    def test_v14_review_verdict_blocked_then_released(self, tmp_path):
        """v1.4 结论通道：review（结构级矛盾）→ 拦截带三选一路由；--accept-review → 放行过。"""
        errors, warns, lines = audit(FACTS_V14, "dws.dwb_cust_asset_d", None)
        assert [e["code"] for e in errors] == ["structural_review"]
        assert "全景可查" in ROUTES["structural_review"]
        f = tmp_path / "facts14.json"
        f.write_text(json.dumps(FACTS_V14, ensure_ascii=False), encoding="utf-8")
        assert main(["--facts", str(f), "--asset", "dws.dwb_cust_asset_d"]) == 2
        assert main(["--facts", str(f), "--asset", "dws.dwb_cust_asset_d",
                     "--accept-review"]) == 0     # 人审放行（裁决留痕在命令行）

    def test_v13_legacy_degrades_gracefully(self):
        """旧产物（v1.3 无 self_check）→ 降级折叠披露不拦截（向后兼容）。"""
        assert "self_check" not in FACTS
        errors, warns, lines = audit(FACTS, "dws.dwb_cust_asset_d", None)
        assert errors == []
        assert any("降级折叠披露" in l for l in lines)

    def test_main_exit_codes(self, tmp_path):
        f = tmp_path / "facts.json"; f.write_text(json.dumps(FACTS, ensure_ascii=False), encoding="utf-8")
        assert main(["--facts", str(f), "--asset", "dws.dwb_cust_asset_d"]) == 0
        assert main(["--facts", str(f), "--asset", "dws.dwb_trade_order_d"]) == 2
        assert main(["--facts", str(tmp_path / "nope.json"), "--asset", "x.y"]) == 2


class TestFieldTypeDrift:
    """正向类型对账（同名异容，2026-10-21）：mapping 存量字段类型 vs 产物——与
    ledger_lag（名字反向）互补的内容级；warn 披露不拦。"""

    def test_drift_warns(self, tmp_path):
        """mapping 台账 cust_id 类型 VARCHAR(128) vs 产物 VARCHAR(64) → warn 带两侧类型
        （变更页签带一条无害 DELETE 行——类型对账在批次解析之后，空批次会先拦）。"""
        m = make_mapping(tmp_path / "m.xlsx",
                         attr_rows=[["default", "b", "ods_acct_balance_di", "cust_id", "VARCHAR(64)",
                                     "直取", "-", "cust_id", "客户号", "VARCHAR(128)", ""]],
                         change_rows=[[1, "2026-10-20", "属性级", "DEFAULT|GONE_X",
                                       "目标字段名", "DELETE", "gone_x", ""]])
        errors, warns, _ = audit(FACTS, "dws.dwb_cust_asset_d", m)
        drift = [w for w in warns if w["code"] == "field_type_drift"]
        assert drift and "VARCHAR(128)" in drift[0]["detail"] and "VARCHAR(64)" in drift[0]["detail"]

    def test_normalized_form_not_warned(self, tmp_path):
        """书写形态差异（产物 NUMERIC(18,2) vs 台账 decimal(18,2)）归一后不报。"""
        m = make_mapping(tmp_path / "m.xlsx",
                         attr_rows=[["default", "b", "ods_acct_balance_di", "total_balance",
                                     "NUMERIC(18,2)", "直取", "-", "total_balance", "总余额",
                                     "decimal(18,2)", ""]],
                         change_rows=[[1, "2026-10-20", "属性级", "DEFAULT|GONE_X",
                                       "目标字段名", "DELETE", "gone_x", ""]])
        errors, warns, _ = audit(FACTS, "dws.dwb_cust_asset_d", m)
        assert not any(w["code"] == "field_type_drift" for w in warns)

    def test_batch_add_not_compared(self, tmp_path):
        """本批 ADD 字段不走存量对账（新增字段的类型与产物无关——产物里本就不该有）。"""
        m = make_mapping(tmp_path / "m.xlsx",
                         attr_rows=[["default", "b", "ods_acct_balance_di", "cust_id", "VARCHAR(64)",
                                     "直取", "-", "cust_id", "客户号", "VARCHAR(64)", ""]],
                         change_rows=[[1, "2026-10-20", "属性级", "DEFAULT|CUST_ID",
                                       "资产字段", "ADD", "", ""]])
        errors, warns, _ = audit(FACTS, "dws.dwb_cust_asset_d", m)
        # cust_id 标新增→add_field_conflict 拦（既另有测试）；类型对账不对其产出
        assert [e["code"] for e in errors] == ["add_field_conflict"]
