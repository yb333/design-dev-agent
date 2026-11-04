# -*- coding: utf-8 -*-
"""assemble_ts_baseline 测试（v2 ts 草稿建档——v1 facts 组装路径已随一波换彻底退役
2026-11-04，v1 组装/拓扑/kind 词表/渲染测试同批删除；消费链测试用冻结 v2 形态
baseline 夹具 baseline_ts_dwb_trade_order_d.json）。"""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"

import argparse as _argparse
from assemble_ts_baseline import _archive_ts_draft

DRAFT_FIXTURE = FIXTURES / "ts_draft_v2_case.json"


def _draft_pass():
    d = json.loads(DRAFT_FIXTURE.read_text(encoding="utf-8"))
    d["_reverse"]["self_check"] = {"verdict": "pass", "structural_count": 0, "noise_count": 0}
    return d


def _args(tmp_path, asset="dws.dwb_cust_asset_d"):
    return _argparse.Namespace(baseline="x", archive_dir=str(tmp_path / "archive"),
                               internal_dir=str(tmp_path / "internal"),
                               manifest=None, asset=asset)


class TestV2DraftArchive:
    def test_verbatim_archive(self, tmp_path):
        """建档=逐字 copy（零解析零变换）：ts.json 内容等、etl=query_sql 逐字、
        MANIFEST 首条、_reverse 随档（单文件自足）。"""
        d = _draft_pass()
        assert _archive_ts_draft(d, _args(tmp_path)) == 0
        arc = tmp_path / "archive"
        assert json.loads((arc / "ts.json").read_text(encoding="utf-8")) == d
        assert (arc / "etl" / "R0001.sql").read_text(encoding="utf-8") \
            == d["rules"]["R0001"]["query_sql"]
        assert "ts 草稿 v2 契约" in (arc / "MANIFEST.md").read_text(encoding="utf-8")
        assert (tmp_path / "internal" / "baseline_view.md").exists()   # 消费点渲染留档
        # 首档 ts.md 成对（2026-11-04 档案成对契约——不留空窗）：逆向形态降级渲染，
        # design 段占位（待首轮优化还原），结构/规则段完整
        md = arc / "dwb_cust_asset_d_ts.md"
        assert md.exists(), "首档 ts.md 未成对产出"
        _md_text = md.read_text(encoding="utf-8")
        assert "设计思路待补" in _md_text
        assert "dwb_cust_asset_d" in _md_text
        assert "## 4. 规则详情" in _md_text

    def test_guard_rejects_rearchive(self, tmp_path):
        d = _draft_pass()
        assert _archive_ts_draft(d, _args(tmp_path)) == 0
        assert _archive_ts_draft(d, _args(tmp_path)) == 2            # 守门：确认档拒绝覆盖

    def test_contract_gate_and_asset_gate(self, tmp_path):
        d = _draft_pass()
        d["rules"]["R0001"].pop("query_sql")                          # v2.1 契约拦
        assert _archive_ts_draft(d, _args(tmp_path)) == 2
        d2 = _draft_pass()
        assert _archive_ts_draft(d2, _args(tmp_path, asset="dws.other_d")) == 2

    def test_v2_archive_consumption_direct(self, tmp_path):
        """消费直连：v2 档天然标准三桶——normalize 幂等直通、rule_output_fields
        直接可用、别名对照 ts 直读（无需 SQL 重解析）。"""
        from ts_compat import normalize_ts
        from run_ut import rule_output_fields
        from preprocess_opt import build_alias_map
        d = _draft_pass()
        _archive_ts_draft(d, _args(tmp_path))
        archived = json.loads((tmp_path / "archive" / "ts.json").read_text(encoding="utf-8"))
        assert normalize_ts(archived) == archived                    # 幂等（已是标准形态）
        assert rule_output_fields(archived["rules"]["R0001"])         # 三桶直读
        rows = build_alias_map({}, archived)                          # 无 SQL 文件——ts 直读
        by = {(r["rule"], r["table"]): r for r in rows}
        assert by[("R0001", "ods_acct_balance_di")]["sql_alias"] == ""
        assert "以 ts 声明为准" in by[("R0001", "ods_acct_balance_di")]["note"]
