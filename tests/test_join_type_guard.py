"""关联键类型守卫测试：宁放过不误报的贯穿链路。

覆盖四层：
1. type_compat.join_key_pair_risky 保守谓词
2. sql_parse.parse_join_pairs 等值对解析
3. precheck 关联键对账（检出 → 决策骨架 → 三选处置 → 回写 rs_input）
4. assemble_ts N_JOIN1（风险对必须 cast 或豁免）
5. ut_diagnose 报错分类 + join 嫌疑反查 + 嫌疑报告
6. explore 键值重叠率纯函数
7. build_compact 的 join_type_risk 段
"""

import json
from pathlib import Path

import pytest


# ============================================================
# 1. 保守谓词
# ============================================================

class TestJoinKeyPairRisky:

    def test_cross_family_flagged(self):
        from type_compat import join_key_pair_risky
        # 用户案例：字符存 abc ↔ 数值存 123
        assert join_key_pair_risky("varchar(32)", "bigint") is True
        assert join_key_pair_risky("numeric(18,2)", "varchar(50)") is True
        assert join_key_pair_risky("timestamp(0)", "varchar(20)") is True

    def test_same_family_pass(self):
        from type_compat import join_key_pair_risky
        assert join_key_pair_risky("varchar(32)", "varchar2(64)") is False
        assert join_key_pair_risky("bigint", "integer") is False
        assert join_key_pair_risky("numeric(10,2)", "numeric(18,4)") is False

    def test_int_numeric_pass(self):
        """整数↔数值：数字家族互跨，PG 等值原生支持——放行（宁放过）"""
        from type_compat import join_key_pair_risky
        assert join_key_pair_risky("bigint", "numeric(18,2)") is False
        assert join_key_pair_risky("numeric", "integer") is False

    def test_unknown_or_empty_pass(self):
        from type_compat import join_key_pair_risky
        assert join_key_pair_risky("", "bigint") is False
        assert join_key_pair_risky("weirdtype", "varchar(10)") is False


# ============================================================
# 2. 等值对解析
# ============================================================

class TestParseJoinPairs:

    def test_basic_and_multi(self):
        from sql_parse import parse_join_pairs
        pairs = parse_join_pairs("a.cust_id = b.cust_id and a.Org_Id = c.org_id")
        assert pairs == [(("a", "cust_id"), ("b", "cust_id")),
                         (("a", "org_id"), ("c", "org_id"))]

    def test_natural_language_unparsed(self):
        from sql_parse import parse_join_pairs
        assert parse_join_pairs("关联客户主数据，编码对编码") == []
        assert parse_join_pairs("") == []

    def test_function_wrapped_not_matched(self):
        """TO_CHAR(a.x)=b.y 函数包装不匹配——只认裸等值（宁放过）"""
        from sql_parse import parse_join_pairs
        assert parse_join_pairs("TO_CHAR(a.dt) = b.dt") == []


# ============================================================
# 3. precheck 关联键对账
# ============================================================

def _mk_rs_input():
    """两源表 + 一个字符↔数值关联条件的最小 rs_input。"""
    return {
        "meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_x_f", "cn": "X"}}},
        "source_tables": [
            {"source_schema": "ods", "source_table": "t_order", "source_alias": "a"},
            {"source_schema": "ods", "source_table": "t_prod", "source_alias": "b"},
        ],
        "field_mappings": [
            {"target_column": "order_id", "transform_rule": "直接复制",
             "source_alias": "a", "source_schema": "ods", "source_table": "t_order",
             "source_column": "order_id", "join_condition": "a.prod_code = b.prod_id"},
            {"target_column": "prod_code", "transform_rule": "直接复制",
             "source_alias": "a", "source_schema": "ods", "source_table": "t_order",
             "source_column": "prod_code", "join_condition": "a.prod_code = b.prod_id"},
        ],
        "schedule": {},
    }


def _mk_cache(tmp_path, tables=None):
    """造 schema_cache（不连库）。"""
    tables = tables if tables is not None else {
        "ods.t_order": {"prod_code": "varchar(32)", "order_id": "bigint"},
        "ods.t_prod": {"prod_id": "bigint", "prod_name": "varchar(64)", "status": "varchar(2)"},
    }
    cache_file = tmp_path / "schema_cache.json"
    cache_file.write_text(json.dumps(
        {"cached_at": "2999-01-01T00:00:00", "tables": tables}), encoding="utf-8")
    return cache_file


class TestPrecheckEruptTogether:

    def test_type_and_join_risks_erupt_same_round(self, tmp_path, capsys):
        """★ 同轮全爆：字段类型风险 + 关联键风险一次性都出来（不剥洋葱）"""
        from precheck import precheck
        rs = _mk_rs_input()
        # 字段类型风险：order_id 直接复制 varchar→numeric（跨大类）
        rs["field_mappings"][0]["source_type"] = "varchar(50)"
        rs["field_mappings"][0]["target_type"] = "numeric(18,2)"
        # 关联键风险已在实体级条件里（a.prod_code varchar ↔ b.prod_id bigint）
        cache = _mk_cache(tmp_path, tables={
            "ods.t_order": {"prod_code": "varchar(32)", "order_id": "varchar(50)"},
            "ods.t_prod": {"prod_id": "bigint"},
        })
        decision = tmp_path / "type_risk_decision.yaml"
        result = precheck(rs, cache, False, decision, None)
        assert any("类型风险" in e for e in result.errors)                      # 字段风险在
        assert any("关联键类型跨大类" in e for e in result.errors)               # ★ 同一轮关联风险也在
        out = capsys.readouterr().out
        assert "TYPE_RISK_PENDING" in out and "JOIN_TYPE_RISK_PENDING" in out   # 双标记同轮

    def test_structural_errors_still_short_circuit(self, tmp_path):
        """结构性错误（字段不存在）仍短路风险检测——元数据不可信时判定是垃圾"""
        from precheck import precheck
        rs = _mk_rs_input()
        rs["field_mappings"][0]["source_type"] = "varchar(50)"
        rs["field_mappings"][0]["target_type"] = "numeric(18,2)"
        cache = _mk_cache(tmp_path, tables={
            "ods.t_order": {"prod_code": "varchar(32)"},   # order_id 不在 → [字段不存在]
            "ods.t_prod": {"prod_id": "bigint"},
        })
        decision = tmp_path / "type_risk_decision.yaml"
        result = precheck(rs, cache, False, decision, None)
        assert any("字段不存在" in e for e in result.errors)
        assert not any("关联键类型跨大类" in e for e in result.errors)


class TestFillJoinRiskDecision:

    def _write_skeleton(self, tmp_path):
        from precheck import _generate_join_risk_skeleton
        p = tmp_path / "join_type_decision.yaml"
        _generate_join_risk_skeleton(p, [{
            "condition": "a.prod_code = b.prod_id",
            "left": "ods.t_order.prod_code", "left_type": "varchar(32)",
            "right": "ods.t_prod.prod_id", "right_type": "bigint",
            "left_samples": "P001", "right_samples": "1001",
        }])
        return p

    def test_fill_and_validate(self, tmp_path):
        import subprocess, sys as _sys
        p = self._write_skeleton(tmp_path)
        rc = subprocess.run([
            _sys.executable, "skills/dws-design/scripts/fill_join_risk_decision.py",
            "--decision", str(p),
            "--pair-decisions", "a.prod_code = b.prod_id=>接受",
            "--reasons", "a.prod_code = b.prod_id=>业务确认",
        ], capture_output=True, text=True)
        assert rc.returncode == 0, rc.stderr
        import yaml
        dec = yaml.safe_load(p.read_text(encoding="utf-8"))
        entry = dec["关联风险对"][0]
        assert entry["处置"] == "接受"
        assert entry["原因"] == "业务确认"

    def test_bad_enum_rejected(self, tmp_path):
        import subprocess, sys as _sys
        p = self._write_skeleton(tmp_path)
        rc = subprocess.run([
            _sys.executable, "skills/dws-design/scripts/fill_join_risk_decision.py",
            "--decision", str(p),
            "--pair-decisions", "a.prod_code = b.prod_id=>随便填",
        ], capture_output=True, text=True)
        assert rc.returncode == 1
        assert "枚举值非法" in rc.stderr

    def test_unknown_condition_rejected(self, tmp_path):
        import subprocess, sys as _sys
        p = self._write_skeleton(tmp_path)
        rc = subprocess.run([
            _sys.executable, "skills/dws-design/scripts/fill_join_risk_decision.py",
            "--decision", str(p),
            "--pair-decisions", "a.x = b.y=>接受",
        ], capture_output=True, text=True)
        assert rc.returncode == 1
        assert "不在骨架里" in rc.stderr


class TestPrecheckJoinTypeRisk:

    def test_entity_level_condition_detected(self, tmp_path, capsys):
        """★ 回归守护：关联&限定条件写在实体级 source_tables（mapping 的真实形态，
        属性级模板无此列恒空）。条件带 left join on 前缀 + 字面量过滤混排。"""
        from precheck import precheck
        rs = _mk_rs_input()
        # 清掉属性级（模拟真实：字段行不写），条件挂到实体级 b 表上
        for fm in rs["field_mappings"]:
            fm["join_condition"] = ""
        rs["source_tables"][1]["join_condition"] = "left join on a.prod_code = b.prod_id and b.status = 'N'"
        cache = _mk_cache(tmp_path)
        decision = tmp_path / "type_risk_decision.yaml"
        result = precheck(rs, cache, False, decision, None)
        assert any("关联键类型跨大类" in e for e in result.errors)
        out = capsys.readouterr().out
        assert "JOIN_TYPE_RISK_PENDING" in out
        assert "a.prod_code = b.prod_id" in out  # 等值对抽出，字面量条件不干扰

    def test_risky_pair_blocks_and_generates_skeleton(self, tmp_path, capsys):
        from precheck import precheck
        rs = _mk_rs_input()
        cache = _mk_cache(tmp_path)
        decision = tmp_path / "type_risk_decision.yaml"
        result = precheck(rs, cache, False, decision, tmp_path / "rs_input.json")
        assert result.return_code == 2
        assert any("关联键类型跨大类" in e for e in result.errors)
        join_decision = tmp_path / "join_type_decision.yaml"
        assert join_decision.exists()
        skel = join_decision.read_text(encoding="utf-8")
        assert "a.prod_code = b.prod_id" in skel
        assert "转换 | 改关联键 | 接受" in skel
        out = capsys.readouterr().out
        assert "JOIN_TYPE_RISK_PENDING" in out

    def test_same_family_passes(self, tmp_path):
        from precheck import precheck
        rs = _mk_rs_input()
        # 两侧都字符 → 同族放行（order_id 也要在缓存，否则 DB 校验先短路）
        cache = _mk_cache(tmp_path, tables={
            "ods.t_order": {"prod_code": "varchar(32)", "order_id": "bigint"},
            "ods.t_prod": {"prod_id": "varchar(64)"},
        })
        decision = tmp_path / "type_risk_decision.yaml"
        result = precheck(rs, cache, False, decision, None)
        assert not any("关联键" in e for e in result.errors)
        assert any("全部同族" in p for p in result.passed)

    def test_decision_accept_releases_and_writes_back(self, tmp_path):
        from precheck import precheck
        rs_path = tmp_path / "rs_input.json"
        rs_path.write_text(json.dumps(_mk_rs_input(), ensure_ascii=False), encoding="utf-8")
        cache = _mk_cache(tmp_path)
        decision = tmp_path / "type_risk_decision.yaml"
        precheck(json.loads(rs_path.read_text()), cache, False, decision, rs_path)
        # 填决策：接受（豁免）
        jd = tmp_path / "join_type_decision.yaml"
        jd.write_text(
            "关联风险对:\n"
            "  - 关联条件: \"a.prod_code = b.prod_id\"\n"
            "    处置: \"接受\"\n"
            "    原因: \"业务确认\"\n", encoding="utf-8")
        rs2 = json.loads(rs_path.read_text())
        result = precheck(rs2, cache, False, decision, rs_path)
        assert not any("关联键" in e for e in result.errors)
        # 回写：事实 + 决策进 rs_input
        rs3 = json.loads(rs_path.read_text())
        assert rs3["_join_type_risks"][0]["left"] == "ods.t_order.prod_code"
        assert rs3["_join_type_decisions"][0]["decision"] == "接受"
        # compact 视图同步（designer 可见）
        view = json.loads((tmp_path / "rs_input_view.json").read_text())
        assert "join_type_risk" in view

    def test_decision_change_key_still_blocks(self, tmp_path):
        from precheck import precheck
        rs = _mk_rs_input()
        cache = _mk_cache(tmp_path)
        decision = tmp_path / "type_risk_decision.yaml"
        precheck(rs, cache, False, decision, None)
        jd = tmp_path / "join_type_decision.yaml"
        jd.write_text(
            "关联风险对:\n"
            "  - 关联条件: \"a.prod_code = b.prod_id\"\n"
            "    处置: \"改关联键\"\n", encoding="utf-8")
        result = precheck(_mk_rs_input(), cache, False, decision, None)
        assert any("改关联键" in e and "mapping" in e for e in result.errors)

    def test_unparseable_condition_warns_not_blocks(self, tmp_path):
        from precheck import precheck
        rs = _mk_rs_input()
        rs["field_mappings"][0]["join_condition"] = "按客户编码关联客户主数据"
        # prod_code/prod_id 同族（不触发风险），order_id 在缓存避免 DB 校验短路
        cache = _mk_cache(tmp_path, tables={
            "ods.t_order": {"prod_code": "varchar(32)", "order_id": "bigint"},
            "ods.t_prod": {"prod_id": "varchar(64)"},
        })
        decision = tmp_path / "type_risk_decision.yaml"
        result = precheck(rs, cache, False, decision, None)
        assert any("无法自动对账" in w for w in result.warnings)
        assert not any("关联键类型跨大类" in e for e in result.errors)

    def test_no_cache_skips_with_warn(self, tmp_path, monkeypatch):
        from precheck import precheck
        rs = _mk_rs_input()
        # 全赋值字段，但实体级源表（join_condition 用）仍在 DB 校验范围（扩围修复）——
        # mock 连库失败（环境类）→ 跳过；缓存缺失 → 关联对账跳过 warn
        for fm in rs["field_mappings"]:
            fm["transform_rule"] = "赋值"
            fm["transform_detail"] = "'N'"
            fm["source_alias"] = ""
            fm["source_schema"] = fm["source_table"] = fm["source_column"] = ""

        class _Status:
            ok = False
            category = "network"
            reason = "mock 不可达"
        class _Exec:
            def diagnose_connection(self):
                return _Status()
            def get_current_source(self):
                return "mock"
            def test_connection(self):
                return False
            def close(self):
                pass
        monkeypatch.setattr("dws_db.create_executor_for_schema",
                            lambda schema, config_path="": _Exec())

        decision = tmp_path / "type_risk_decision.yaml"
        result = precheck(rs, tmp_path / "none.json", False, decision, None)
        assert any("关联键类型对账跳过" in w for w in result.warnings)
        assert not any("关联键类型跨大类" in e for e in result.errors)


# ============================================================
# 4. assemble_ts N_JOIN1
# ============================================================

def _mk_decisions_and_rs(with_cast=False, with_exempt=False):
    """造 decisions（规则带 joins）+ rs_input（带 _join_type_risks）。"""
    join_entry = {
        "rule_code": "R0001", "rule_name": "装配", "exec_sequence": 1,
        "target_table": "dws.dwb_x_f", "target_role": "target", "step_type": "full",
        "load_mode": "truncate_table", "write_condition": "",
        "field_targets": ["order_id"], "field_logics": {"order_id": "直取"},
        "source_aliases": ["a", "b"],
        "joins": [{"alias": "b", "type": "LEFT JOIN",
                   "condition": "a.prod_code = b.prod_id",
                   "filter": "", **({"cast": "a.prod_code::numeric"} if with_cast else {})}],
    }
    decisions = {
        "meta": {"asset_cn": "X", "target_table": "dws.dwb_x_f"},
        "schedule": {"schedule_type": "daily", "cron": "0 30 3 * * ?"},
        "tables": {"dwb_x_f": {"distribution_key": ["order_id"], "fields": [
            {"target_field": "order_id", "field_type": "varchar(64)"}]}},
        "rules": [join_entry],
    }
    rs_input = {
        "meta": {"target": {"f_table": {"schema": "dws", "table": "dwb_x_f"}}},
        "source_tables": [
            {"source_schema": "ods", "source_table": "t_order", "source_alias": "a"},
            {"source_schema": "ods", "source_table": "t_prod", "source_alias": "b"},
        ],
        "field_mappings": [
            {"target_column": "order_id", "transform_rule": "直接复制",
             "source_alias": "a", "source_schema": "ods", "source_table": "t_order",
             "source_column": "order_id", "source_type": "bigint", "target_type": "varchar(64)"},
        ],
        "_join_type_risks": [{
            "condition": "a.prod_code = b.prod_id",
            "left": "ods.t_order.prod_code", "left_type": "varchar(32)",
            "right": "ods.t_prod.prod_id", "right_type": "bigint",
        }],
    }
    if with_exempt:
        rs_input["_join_type_decisions"] = [
            {"condition": "a.prod_code = b.prod_id", "decision": "接受", "reason": ""}]
    return decisions, rs_input


class TestNJoin1:

    def _hard_msgs(self, vr):
        return [it["msg"] for it in vr.items if it.get("level") == "hard"]

    def test_risky_without_cast_blocks(self):
        from assemble_ts import run_all_validations
        decisions, rs_input = _mk_decisions_and_rs()
        vr = run_all_validations(decisions, rs_input, {"order_id": {}})
        hits = [m for m in self._hard_msgs(vr) if "N_JOIN1" in m or "键类型跨大类" in m]
        assert hits, f"应报 N_JOIN1 硬错，实际硬错: {self._hard_msgs(vr)}"

    def test_cast_declared_passes(self):
        from assemble_ts import run_all_validations
        decisions, rs_input = _mk_decisions_and_rs(with_cast=True)
        vr = run_all_validations(decisions, rs_input, {"order_id": {}})
        assert not [m for m in self._hard_msgs(vr) if "键类型跨大类" in m]

    def test_exempted_passes(self):
        from assemble_ts import run_all_validations
        decisions, rs_input = _mk_decisions_and_rs(with_exempt=True)
        vr = run_all_validations(decisions, rs_input, {"order_id": {}})
        assert not [m for m in self._hard_msgs(vr) if "键类型跨大类" in m]

    def test_no_risk_facts_skips(self):
        """rs_input 无 _join_type_risks（precheck 没检出）→ 不硬判（宁放过）"""
        from assemble_ts import run_all_validations
        decisions, rs_input = _mk_decisions_and_rs()
        rs_input.pop("_join_type_risks")
        vr = run_all_validations(decisions, rs_input, {"order_id": {}})
        assert not [m for m in self._hard_msgs(vr) if "键类型跨大类" in m]


# ============================================================
# 5. ut_diagnose：分类 + join 嫌疑 + 嫌疑报告
# ============================================================

class TestClassifyDbError:

    def test_high_confidence_patterns(self):
        from ut_diagnose import classify_db_error
        assert classify_db_error("ERROR: operator does not exist: character varying = integer")["class"] == "比较算子缺失"
        assert classify_db_error('invalid input syntax for type numeric: "abc"')["class"] == "值转换失败"
        assert classify_db_error("ORA-01722: invalid number")["class"] == "值转换失败"

    def test_unknown_not_classified(self):
        from ut_diagnose import classify_db_error
        assert classify_db_error("connection refused") is None
        assert classify_db_error("") is None


def _mk_ts_rule():
    return {
        "rule_code": "R0001", "target_table": "dws.dwb_x_f",
        "source_tables": [
            {"schema": "ods", "table": "t_order", "alias": "a"},
            {"schema": "ods", "table": "t_prod", "alias": "b"},
        ],
        "joins": [{"alias": "b", "type": "LEFT JOIN",
                   "condition": "a.prod_code = b.prod_id", "filter": ""}],
    }


class TestDiagnoseJoinSuspicion:

    def test_finds_risky_pair(self):
        from ut_diagnose import diagnose_join_suspicion
        cache = {"ods.t_order": {"prod_code": "varchar(32)"},
                 "ods.t_prod": {"prod_id": "bigint"}}
        suspects = diagnose_join_suspicion(_mk_ts_rule(), {}, cache)
        assert len(suspects) == 1
        s = suspects[0]
        assert s["left"] == "ods.t_order.prod_code" and s["left_type"] == "varchar(32)"
        assert s["right"] == "ods.t_prod.prod_id" and s["right_type"] == "bigint"

    def test_same_family_not_suspect(self):
        from ut_diagnose import diagnose_join_suspicion
        cache = {"ods.t_order": {"prod_code": "varchar(32)"},
                 "ods.t_prod": {"prod_id": "varchar(64)"}}
        assert diagnose_join_suspicion(_mk_ts_rule(), {}, cache) == []

    def test_missing_types_not_suspect(self):
        from ut_diagnose import diagnose_join_suspicion
        cache = {"ods.t_order": {}}  # 查不到类型判不了 → 放过
        assert diagnose_join_suspicion(_mk_ts_rule(), {}, cache) == []


class TestSuspicionReport:

    def test_report_with_suspects_routes_to_designer(self):
        from ut_diagnose import classify_db_error, format_suspicion_report
        cls = classify_db_error('invalid input syntax for type numeric: "abc"')
        suspects = [{
            "condition": "a.prod_code = b.prod_id",
            "left": "ods.t_order.prod_code", "left_type": "varchar(32)",
            "right": "ods.t_prod.prod_id", "right_type": "bigint",
            "left_samples": ["P001", "P002"], "right_samples": ["1001", "1002"],
        }]
        text = format_suspicion_report("invalid input syntax", cls, suspects, "")
        assert "嫌疑报告" in text
        assert "a.prod_code = b.prod_id" in text
        assert "'P001'" in text and "'1001'" in text
        assert "禁止" in text and "改字段类型" in text  # 路由铁律
        assert "疑似关联逻辑错误" in text

    def test_report_without_suspects_goes_field_route(self):
        from ut_diagnose import classify_db_error, format_suspicion_report
        cls = classify_db_error("invalid input syntax for type numeric")
        text = format_suspicion_report("invalid input syntax", cls, [], "字段 amount 有 3 行脏数据")
        assert "无关联嫌疑" in text
        assert "字段类型链路" in text


# ============================================================
# 6. explore 键值重叠率
# ============================================================

class TestOverlap:

    def test_compute_overlap_disjoint(self):
        from explore import compute_overlap
        r = compute_overlap(["P001", "P002"], ["1001", "1002"])
        assert r["common"] == 0
        assert r["rate_a"] == 0.0

    def test_compute_overlap_partial(self):
        from explore import compute_overlap
        r = compute_overlap(["1", "2", "3"], ["2", "3", "4"])
        assert r["common"] == 2
        assert r["rate_a"] == round(2 / 3, 4)

    def test_format_zero_overlap_verdict(self):
        from explore import compute_overlap, format_overlap_result
        r = compute_overlap(["P001"], ["1001"])
        text = format_overlap_result("ods.t1", "code", "ods.t2", "id", r)
        assert "零交集" in text and "关联逻辑大概率错误" in text

    def test_format_high_overlap_verdict(self):
        from explore import compute_overlap, format_overlap_result
        r = compute_overlap(["1", "2", "3"], ["1", "2", "3"])
        text = format_overlap_result("ods.t1", "code", "ods.t2", "id", r)
        assert "语义吻合" in text

    def test_sql_shape(self):
        from explore import build_overlap_sample_sql
        sql = build_overlap_sample_sql("ods", "t1", "cust_code", "is_current = 1")
        assert sql == ("SELECT DISTINCT cust_code::text AS v FROM ods.t1 "
                       "WHERE is_current = 1 LIMIT 500")


# ============================================================
# 7. build_compact 的 join_type_risk 段
# ============================================================

class TestCompactJoinRisk:

    def test_block_present_when_risks(self):
        from preprocess import build_compact
        rs = _mk_rs_input()
        rs["_join_type_risks"] = [{
            "condition": "a.prod_code = b.prod_id",
            "left": "ods.t_order.prod_code", "left_type": "varchar(32)",
            "right": "ods.t_prod.prod_id", "right_type": "bigint"}]
        rs["_join_type_decisions"] = [
            {"condition": "a.prod_code = b.prod_id", "decision": "转换", "reason": ""}]
        view = build_compact(rs)
        assert "join_type_risk" in view
        assert "cast" in view["join_type_risk"]["说明"]

    def test_block_absent_without_risks(self):
        from preprocess import build_compact
        view = build_compact(_mk_rs_input())
        assert "join_type_risk" not in view
