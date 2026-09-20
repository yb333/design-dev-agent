"""dq_impact（opt DQ 影响分析）测试——2026-09-14 DQ 拆分块三。

覆盖：锚定命中/比对来源命中/未命中继承/旧形态兜底（无锚定从 violation_condition 粗提）/
baseline 无 DQ 空清单 + CLI 端到端。assemble_dq 的 opt 参数（--dq-dir/--no-rs-contract）同文件。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "skills/opt-pipe/scripts")
sys.path.insert(0, "skills/new-pipe/scripts")

from dq_impact import analyze, load_dq_rules_anywhere, _collect_change_sets  # noqa: E402


def _rule(idx, anchor=None, comps=None, vc="", mode="assertion"):
    return {"idx": idx, "rule_name": f"规则{idx}", "check_type": "空值检查", "mode": mode,
            "anchored_fields": anchor or [], "compare_sources": comps or [],
            "violation_condition": vc}


class TestAnalyze:
    def test_anchor_hit(self):
        rules = [_rule(1, anchor=["order_amount"]), _rule(2, anchor=["prod_code"])]
        result = analyze(rules, changed_fields=["order_amount"], changed_sources=[])
        assert [r["idx"] for r in result["rebuild"]] == [1]
        assert "锚定字段被变更" in result["rebuild"][0]["reasons"][0]
        assert [r["idx"] for r in result["keep"]] == [2]

    def test_compare_source_hit(self):
        rules = [_rule(1, comps=["ods_pay_f"], mode="compare"), _rule(2, comps=["ods_user_f"], mode="compare")]
        result = analyze(rules, changed_fields=[], changed_sources=["ods_pay_f"])
        assert [r["idx"] for r in result["rebuild"]] == [1]

    def test_new_source_hits_all_comparing_it(self):
        """新增来源：凡比对对象涉及该来源的对比式都进重做清单（讨论定的真实场景）。"""
        rules = [_rule(1, anchor=["a"], comps=["ods_old_f"], mode="compare"),
                 _rule(2, anchor=["b"], comps=[])]
        result = analyze(rules, changed_fields=[], changed_sources=["ods_old_f"])
        assert [r["idx"] for r in result["rebuild"]] == [1]

    def test_legacy_rule_guesses_anchor_from_vc(self):
        """旧形态条目（无锚定声明）：从 violation_condition 粗提兜底。"""
        legacy = {"idx": 1, "rule_name": "旧", "violation_condition": "t.order_amount IS NULL"}
        result = analyze([legacy], changed_fields=["order_amount"], changed_sources=[])
        assert [r["idx"] for r in result["rebuild"]] == [1]

    def test_no_hits_all_keep(self):
        rules = [_rule(1, anchor=["a"]), _rule(2, anchor=["b"])]
        result = analyze(rules, changed_fields=["totally_new_col"], changed_sources=[])
        assert result["rebuild"] == [] and len(result["keep"]) == 2


class TestLoad:
    def test_load_dq_json(self, tmp_path):
        p = tmp_path / "dq.json"
        p.write_text(json.dumps({"rules": [_rule(1)]}, ensure_ascii=False), encoding="utf-8")
        assert len(load_dq_rules_anywhere(p)) == 1

    def test_load_legacy_ts(self, tmp_path):
        p = tmp_path / "ts.json"
        p.write_text(json.dumps({"dq_rules": [{"rule_name": "旧"}]}, ensure_ascii=False), encoding="utf-8")
        assert len(load_dq_rules_anywhere(p)) == 1

    def test_load_missing_empty(self, tmp_path):
        assert load_dq_rules_anywhere(tmp_path / "dq.json") == []

    def test_collect_change_sets_key_shapes(self):
        cr = {"fields": [{"target_column": "amount"}, {"column": "cnt"}],
              "new_sources": [{"table": "ods_new_f"}]}
        f, s = _collect_change_sets(cr)
        assert set(f) == {"amount", "cnt"} and s == ["ods_new_f"]


class TestCli:
    def test_main_produces_report(self, tmp_path, capsys):
        import dq_impact
        dq = tmp_path / "dq.json"
        dq.write_text(json.dumps({"rules": [
            {"idx": 1, "rule_name": "金额口径复核", "mode": "compare",
             "anchored_fields": ["amount"], "compare_sources": ["ods_pay_f"]},
            {"idx": 2, "rule_name": "编号非空", "mode": "assertion", "anchored_fields": ["id"]},
        ]}, ensure_ascii=False), encoding="utf-8")
        cr = tmp_path / "change_request.json"
        cr.write_text(json.dumps({"fields": [{"target_column": "amount"}],
                                  "new_sources": []}, ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "dq_impact.md"
        old_argv = sys.argv
        sys.argv = ["dq_impact.py", "--baseline-dq", str(dq), "--change-request", str(cr),
                    "--output", str(out)]
        try:
            with pytest.raises(SystemExit) as ei:
                dq_impact.main()
        finally:
            sys.argv = old_argv
        assert ei.value.code == 0
        text = out.read_text(encoding="utf-8")
        assert "金额口径复核" in text and "需重做" in text
        assert "编号非空" in text and "原样继承" in text


class TestAssembleDqOptParams:
    """assemble_dq 的 opt 场景参数：--dq-dir（SQL 在变更现场）+ --no-rs-contract（跳过 RS 对照）+ --dq-src（producer 直产 dq.json）。"""

    def _setup(self, tmp_path):
        from tests.test_assemble_dq import _ts, _rule
        build = tmp_path / "build"
        arc_tmp = tmp_path / "arc_tmp"
        (build / "_internal").mkdir(parents=True)
        (build / "dq").mkdir()
        arc_tmp.mkdir()
        (arc_tmp / "ts.json").write_text(json.dumps(_ts(), ensure_ascii=False), encoding="utf-8")
        (arc_tmp / "ts.md").write_text(
            "## 7. 数据质量检查(DQ)\n\n*(占位)*\n\n---\n\n## 8. 增量设计\n", encoding="utf-8")
        (build / "_internal" / "rs_input.json").write_text(
            json.dumps({"dq_requirements": []}, ensure_ascii=False), encoding="utf-8")
        (build / "dq" / "DQ_001_产品编码非空.sql").write_text(
            "SELECT t.id, t.prod_code FROM dws.dwb_test_f t WHERE t.prod_code IS NULL", encoding="utf-8")
        (build / "dq.json").write_text(json.dumps({"rules": [
            {"rule_id": "DQ_001", "scope": "字段级", "check_type": "空值检查", "rule_name": "产品编码非空",
             "mode": "assertion", "violation_condition": "t.prod_code IS NULL",
             "rule_desc": "违规=空"}]}, ensure_ascii=False), encoding="utf-8")
        return build, arc_tmp

    def test_opt_mode_no_rs_no_contract(self, tmp_path):
        """opt 场景：不传 --rs（源表从 ts 派生）+ --no-rs-contract（条目全来自 baseline——不触发 N_DQ3）；
        校验补全写回 build/dq.json，ts.md 渲染进 arc_tmp。"""
        import assemble_dq
        build, arc_tmp = self._setup(tmp_path)
        old_argv = sys.argv
        sys.argv = ["assemble_dq.py", "--ts", str(arc_tmp / "ts.json"),
                    "--dq-src", str(build / "dq.json"),
                    "--dq-dir", str(build / "dq"), "--no-rs-contract"]
        try:
            with pytest.raises(SystemExit) as ei:
                assemble_dq.main()
        finally:
            sys.argv = old_argv
        assert ei.value.code == 0
        dq = json.loads((build / "dq.json").read_text(encoding="utf-8"))
        assert dq["rules"][0]["sql_file"] == "DQ_001_产品编码非空.sql"  # 补全写回
        assert "t.prod_code IS NULL" in (arc_tmp / "ts.md").read_text(encoding="utf-8")

    def test_rs_contract_would_fire_dq3_without_flag(self, tmp_path):
        """对照组：不关 RS 契约时，RS 无需求但有条目 → N_DQ3 warn（new-pipe 场景的护栏仍在）。"""
        from tests.test_assemble_dq import _ts
        from assemble_dq import validate_and_build
        build, arc_tmp = self._setup(tmp_path)
        rs = json.loads((build / "_internal" / "rs_input.json").read_text(encoding="utf-8"))
        ts = json.loads((arc_tmp / "ts.json").read_text(encoding="utf-8"))
        dq_src = json.loads((build / "dq.json").read_text(encoding="utf-8"))
        _, vr = validate_and_build(rs, ts, dq_src["rules"], build / "dq", rs_contract=True)
        assert any(i["code"] == "N_DQ3" for i in vr.items)
        _, vr2 = validate_and_build(rs, ts, dq_src["rules"], build / "dq", rs_contract=False)
        assert not any(i["code"] == "N_DQ3" for i in vr2.items)
