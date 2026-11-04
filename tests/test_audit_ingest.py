# -*- coding: utf-8 -*-
"""audit_ingest 测试（v2 ts 草稿模式——v1 facts 审核路径已随一波换彻底退役 2026-11-04，
对应测试同批删除）。"""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "opt"

DRAFT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "opt" / "ts_draft_v2_case.json"


def _draft(**over):
    import copy
    d = json.loads(DRAFT_FIXTURE.read_text(encoding="utf-8"))
    d["_reverse"]["self_check"] = {"verdict": "pass", "structural_count": 0, "noise_count": 0}
    d.update(over)
    return d


class TestTsDraftMode:
    def test_pass_verdict_passes(self):
        from audit_ingest import audit_ts_draft
        errs, warns, lines = audit_ts_draft(_draft(), "dws.dwb_cust_asset_d", None)
        assert not errs and any("目标表字段" in l for l in lines)

    def test_review_verdict_blocked(self):
        from audit_ingest import audit_ts_draft
        d = _draft()
        d["_reverse"]["self_check"] = {"verdict": "review", "structural_count": 2, "noise_count": 7}
        errs, _, _ = audit_ts_draft(d, "dws.dwb_cust_asset_d", None)
        assert [e["code"] for e in errs] == ["structural_review"]

    def test_contract_v21_query_sql_required(self):
        from audit_ingest import audit_ts_draft
        d = _draft()
        d["rules"]["R0001"].pop("query_sql")
        errs, _, _ = audit_ts_draft(d, "dws.dwb_cust_asset_d", None)
        assert errs[0]["code"] == "contract_violation"
        assert any("query_sql" in str(e) for e in errs[0]["detail"])

    def test_asset_mismatch_rejected(self):
        from audit_ingest import audit_ts_draft
        errs, _, _ = audit_ts_draft(_draft(), "dws.dwb_other_d", None)
        assert [e["code"] for e in errs] == ["asset_mismatch"]

    def test_main_routes_by_self_description(self, tmp_path):
        """CLI 按产物自描述路由：草稿（spec_type=ts/version 2.x）走 v2 审核。"""
        from audit_ingest import main
        fp = tmp_path / "ts_draft.json"
        fp.write_text(json.dumps(_draft(), ensure_ascii=False), encoding="utf-8")
        assert main(["--facts", str(fp), "--asset", "dws.dwb_cust_asset_d"]) == 0
