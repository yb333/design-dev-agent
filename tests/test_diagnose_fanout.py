"""diagnose_fanout 测试：UT 回路关联发散定位器（fake executor，不连库）。

核心契约：
- 严格遵守声明条件（复合键 + joins[].filter / join_safety.join_filter / 规则 filter /
  condition 里的字面量项全部并入 WHERE——as-designed 查证）；
- filter 承重墙（裸查重复、声明条件唯一 ⇒ SQL 漏写过滤即发散）单独识别；
- 嫌疑→实锤（重复键样例回伙伴表查命中，不命中=实际可能不膨胀）；
- 驱动表 business_key 自检（排除"根本不是 join 的锅"）；
- 链式无需增量测试（每表全局键唯一=不可能放大，顺序无关）。
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "skills" / "new-pipe" / "scripts"))
sys.path.insert(0, str(REPO / "skills" / "design-dev-shared" / "scripts"))

from diagnose_fanout import diagnose  # noqa: E402


class _R:
    def __init__(self, rows=None, success=True, error=""):
        self.success, self.rows, self.error = success, rows or [], error


class _FakeEx:
    """按 SQL 特征回放结果；capture 收集全部 SQL 供断言。
    handler 返回 ("ERR", "msg") 模拟查询失败（executor 报错路径）。"""

    def __init__(self, handler):
        self.h = handler
        self.captured: list[str] = []

    def test_connection(self):
        return True

    def execute(self, sql):
        self.captured.append(sql)
        out = self.h(sql)
        if isinstance(out, tuple) and out and out[0] == "ERR":
            return _R(success=False, error=out[1])
        return _R(out)

    def close(self):
        pass


def _patch(monkeypatch, handler):
    import dws_db
    ex = _FakeEx(handler)
    ex.created_schemas = []

    def _create(schema, role="etl"):
        ex.created_schemas.append(schema)
        return ex

    monkeypatch.setattr(dws_db, "create_executor_for_schema", _create)
    return ex


def _ts(joins, business_key=("order_no",), extra_rule=None):
    rule = {
        "source_tables": [
            {"schema": "ods", "table": "orders", "alias": "a"},
            {"schema": "dim", "table": "dim_cust", "alias": "c"},
            {"schema": "ods", "table": "pay", "alias": "p"},
        ],
        "joins": joins,
        "join_safety": [],
        "filter": "",
    }
    if extra_rule:
        rule.update(extra_rule)
    return {"design": {"business_key": list(business_key)}, "rules": {"R0001": rule}}


def _run(monkeypatch, tmp_path, ts, handler, rule="R0001"):
    (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
    ex = _patch(monkeypatch, handler)
    lines, concl = diagnose(tmp_path / "ts.json", rule)
    return lines, concl, ex


class TestFanoutLocalization:
    def test_fanout_detected_with_partner_hit(self, monkeypatch, tmp_path):
        """键重复 + 样例 + 伙伴表命中 = 发散嫌疑成立（实锤）。"""
        def h(sql):
            if "GROUP BY" in sql:
                return [{"cust_code": "C001", "c": 3}, {"cust_code": "C002", "c": 2}]
            if " IN (" in sql:
                return [{"hits": 4}]
            if "dim_cust" in sql:
                return [{"total": 90, "uniq": 88, "nulls": 0}]
            return [{"total": 100, "uniq": 100, "nulls": 0}]  # 驱动/pay 唯一

        lines, concl, _ = _run(monkeypatch, tmp_path, _ts([
            {"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"}]), h)
        assert "发散 2 行" in "\n".join(lines)
        assert "C001×3" in "\n".join(lines)
        assert "发散嫌疑成立" in concl

    def test_dup_keys_not_hit_partner_reported_soft(self, monkeypatch, tmp_path):
        """重复键不命中伙伴表 → 软结论（实际可能不膨胀），不误报实锤。"""
        def h(sql):
            if "GROUP BY" in sql:
                return [{"cust_code": "C001", "c": 3}]
            if " IN (" in sql:
                return [{"hits": 0}]
            if "dim_cust" in sql:
                return [{"total": 90, "uniq": 89, "nulls": 0}]
            return [{"total": 100, "uniq": 100, "nulls": 0}]

        lines, concl, _ = _run(monkeypatch, tmp_path, _ts([
            {"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"}]), h)
        assert "未命中伙伴表" in concl and "嫌疑成立" not in concl

    def test_all_unique_conclusion_points_away_from_join(self, monkeypatch, tmp_path):
        def h(sql):
            return [{"total": 50, "uniq": 50, "nulls": 0}]

        lines, concl, _ = _run(monkeypatch, tmp_path, _ts([
            {"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"}]), h)
        assert "发散不来自关联" in concl

    def test_no_joins_message(self, monkeypatch, tmp_path):
        def h(sql):
            return [{"total": 50, "uniq": 50, "nulls": 0}]

        lines, _, _ = _run(monkeypatch, tmp_path, _ts([]), h)
        assert any("无关联可查" in ln for ln in lines)


class TestDeclaredConditionsHonored:
    def test_composite_key_and_filter_in_query(self, monkeypatch, tmp_path):
        """复合键 + 声明过滤必须真进 SQL：COUNT(DISTINCT (x, tenant)) + WHERE c.is_current = 1。"""
        def h(sql):
            return [{"total": 50, "uniq": 50, "nulls": 0}]

        lines, _, ex = _run(monkeypatch, tmp_path, _ts([
            {"alias": "c", "type": "LEFT JOIN",
             "condition": "a.x = c.x and a.tenant = c.tenant and c.is_current = 1"}]), h)
        joined = "\n".join(ex.captured)
        assert "COUNT(DISTINCT (x, tenant))" in joined          # 复合键（单列查会误报）
        assert "is_current = 1" in joined                       # condition 字面量项并入（单表 WHERE 剥别名前缀）
        assert "→ ✓ 唯一" in "\n".join(lines)

    def test_rule_filter_and_join_safety_filter_applied(self, monkeypatch, tmp_path):
        """规则 filter / join_safety.join_filter 归属该表的项并入 WHERE（as-designed）。"""
        def h(sql):
            return [{"total": 50, "uniq": 50, "nulls": 0}]

        ts = _ts([{"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"}],
                 extra_rule={"filter": "c.del_flag = 'N'",
                             "join_safety": [{"table": "dim_cust", "join_filter": "c.is_current = 1",
                                              "join_key_unique": True}]})
        lines, _, ex = _run(monkeypatch, tmp_path, ts, h)
        joined = "\n".join(ex.captured)
        assert "del_flag = 'N'" in joined and "is_current = 1" in joined
        assert "c." not in joined.split("WHERE")[-1]           # FROM 无别名，WHERE 不得残留别名前缀

    def test_filter_load_bearing_wall(self, monkeypatch, tmp_path):
        """裸查重复但声明条件唯一 → filter 承重墙（SQL 漏写即发散）。"""
        def h(sql):
            if "dim_cust" in sql and "WHERE" in sql:
                return [{"total": 105, "uniq": 105, "nulls": 0}]   # 按声明条件唯一
            if "dim_cust" in sql:
                return [{"total": 120, "uniq": 100, "nulls": 0}]   # 裸查重复
            return [{"total": 100, "uniq": 100, "nulls": 0}]

        lines, concl, _ = _run(monkeypatch, tmp_path, _ts([
            {"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code",
             "filter": "c.is_current = 1"}]), h)
        assert "filter 承重墙" in "\n".join(lines) and "承重" in concl


    def test_single_connection_via_target_schema(self, monkeypatch, tmp_path):
        """部署事实：目标 schema 数据源有全部来源表权限——单连接走目标 schema，
        不逐源 schema 连库（曾报'来源 schema 不在 db 配置'）。"""
        def h(sql):
            return [{"total": 50, "uniq": 50, "nulls": 0}]

        ts = _ts([{"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"}])
        ts["meta"] = {"target": {"f_table": {"schema": "dws", "table": "dwb_x_f"}}}
        lines, _, ex = _run(monkeypatch, tmp_path, ts, h)
        assert ex.created_schemas == ["dws"]                    # 只连目标 schema 一次
        assert "FROM dim.dim_cust" in "\n".join(ex.captured)  # 表名带各自 schema 限定


class TestDrivingTable:
    def test_driving_business_key_dup_flagged_as_non_join(self, monkeypatch, tmp_path):
        """驱动表自身 business_key 重复 → 非关联问题（粒度/主键），钉死事实。"""
        def h(sql):
            if "orders" in sql:
                return [{"total": 100, "uniq": 97, "nulls": 0}]
            return [{"total": 50, "uniq": 50, "nulls": 0}]

        lines, concl, _ = _run(monkeypatch, tmp_path, _ts([
            {"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"}]), h)
        assert "驱动表" in "\n".join(lines)
        assert "非关联问题" in concl

    def test_null_keys_do_not_count_as_fanout(self, monkeypatch, tmp_path):
        """NULL 键不参与 join 不会发散——total-nulls-uniq 才是发散行数。"""
        def h(sql):
            if "dim_cust" in sql:
                return [{"total": 100, "uniq": 90, "nulls": 10}]   # 10 行 NULL 键
            return [{"total": 100, "uniq": 100, "nulls": 0}]

        lines, concl, _ = _run(monkeypatch, tmp_path, _ts([
            {"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"}]), h)
        joined = "\n".join(lines)
        assert "✓ 唯一" in joined and "✗" not in joined   # NULL 键不算发散行
        assert "发散不来自关联" in concl


def test_diagnose_all_batch_single_connection_and_skip(monkeypatch, tmp_path):
    """--all 批量（闸口①前）：rules+init.rules 逐规则共享单连接；单规则异常跳过不炸整批。"""
    from diagnose_fanout import diagnose_all

    def h(sql):
        return [{"total": 50, "uniq": 50, "nulls": 0}]

    ts = _ts([{"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"}])
    ts["meta"] = {"target": {"f_table": {"schema": "dws", "table": "dwb_x_f"}}}
    ts["rules"]["R0002"] = {  # 无 source_tables 绑定 → 驱动缺、仍应不炸（或可诊断）
        "source_tables": [], "joins": [], "filter": ""}
    (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
    ex = _patch(monkeypatch, h)
    results = diagnose_all(tmp_path / "ts.json")
    codes = [c for c, _, _ in results]
    assert codes == ["R0001", "R0002"]
    assert "发散不来自关联" in {c: k for c, k, _ in results}["R0001"]
    assert ex.created_schemas == ["dws"]  # 全批一次连接
    # 中间结论不吞（内网实证 --all 曾只留一行总结论）——分规则完整报告行必须保留
    assert all(len(rlines) >= 2 for _, _, rlines in results if rlines)


class TestFaultIsolation:
    """单表故障隔离（内网实证：一张表报错曾炸停整批致报告缺失）+
    隐式转换报错识别（声明条件字面量与列类型不匹配——条件独立执行都跑不通，
    真实 ETL 照写同样炸，闸口①提前抓到）。"""

    def test_declared_filter_error_degrades_to_bare(self, monkeypatch, tmp_path):
        """声明条件查询炸（invalid input 隐式转换）→ 降级裸查给结论+提示，其余表继续。"""
        def h(sql):
            if "dim_cust" in sql and "WHERE" in sql:
                return ("ERR", "invalid input for type numeric: 'R42'")
            if "dim_cust" in sql:
                return [{"total": 90, "uniq": 87, "nulls": 0}]   # 裸查发散
            return [{"total": 50, "uniq": 50, "nulls": 0}]

        lines, concl, _ = _run(monkeypatch, tmp_path, _ts([
            {"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code",
             "filter": "c.status = 1"},
            {"alias": "p", "type": "LEFT JOIN", "condition": "a.pay_id = p.pay_id"}]), h)
        joined = "\n".join(lines)
        assert "降级裸查" in joined and "隐式转换" in joined and "invalid input" in joined
        assert "重复 3 行" in joined                       # 裸查结论仍给出
        assert "JOIN 2" in joined                          # 后续表继续诊断

    def test_table_failure_skips_but_rest_continue(self, monkeypatch, tmp_path):
        """裸查也失败 → 跳过该表，其余表照常出结论，不炸整批。"""
        def h(sql):
            if "dim_cust" in sql:
                return ("ERR", "relation does not exist")
            return [{"total": 50, "uniq": 50, "nulls": 0}]

        lines, concl, _ = _run(monkeypatch, tmp_path, _ts([
            {"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"},
            {"alias": "p", "type": "LEFT JOIN", "condition": "a.pay_id = p.pay_id"}]), h)
        joined = "\n".join(lines)
        assert "查询失败跳过（其余表继续）" in joined
        assert "[JOIN 2] ods.pay" in joined and "✓ 唯一" in joined

    def test_count_1_not_count_star(self, monkeypatch, tmp_path):
        """COUNT(1) 而非 COUNT(*)（平台口径）。"""
        def h(sql):
            return [{"total": 50, "uniq": 50, "nulls": 0}]

        _, _, ex = _run(monkeypatch, tmp_path, _ts([
            {"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"}]), h)
        joined = "\n".join(ex.captured)
        assert "COUNT(1)" in joined and "COUNT(*)" not in joined


class TestJoinCountAndValueForm:
    """声明语义精确计数（闸口①满配核心）+ 字面量值形态开局修正（2026-09-02 第一批）。"""

    def _write_ts(self, tmp_path, joins, rule_filter=""):
        ts = _ts(joins, extra_rule={"filter": rule_filter} if rule_filter else None)
        ts["meta"] = {"target": {"f_table": {"schema": "dws", "table": "dwb_x_f"}}}
        (tmp_path / "ts.json").write_text(json.dumps(ts), encoding="utf-8")
        return ts

    def test_gate_mode_clean_skips_per_table(self, monkeypatch, tmp_path):
        """闸口①批量（deep=False）：计数无膨胀 → 逐表归因省略（省 N 条 count distinct）。"""
        def h(sql):
            if " AS jc " in sql:
                return [{"jc": 100}]                       # before=after 无膨胀无丢行
            return [{"total": 50, "uniq": 50, "nulls": 0}]

        self._write_ts(tmp_path, [
            {"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"}])
        ex = _patch(monkeypatch, h)
        from diagnose_fanout import diagnose
        lines, concl = diagnose(tmp_path / "ts.json", "R0001", deep=False)
        joined = "\n".join(lines)
        assert "✓ 无膨胀无丢行" in joined and "逐表归因] 未触发" in joined
        assert "COUNT(DISTINCT" not in "\n".join(ex.captured[1:])  # 只有驱动自检 + 计数

    def test_gate_mode_fanout_runs_attribution(self, monkeypatch, tmp_path):
        """确认膨胀 → 逐表归因照跑（闸口①模式下定位嫌疑表）。"""
        def h(sql):
            if " AS jc " in sql:
                return [{"jc": 130}] if sql.count("JOIN") else [{"jc": 100}]
            return [{"total": 50, "uniq": 50, "nulls": 0}]

        self._write_ts(tmp_path, [
            {"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"}])
        ex = _patch(monkeypatch, h)
        from diagnose_fanout import diagnose
        lines, concl = diagnose(tmp_path / "ts.json", "R0001", deep=False)
        joined = "\n".join(lines)
        assert "膨胀 30 行" in joined and "精确膨胀" in concl
        assert "[JOIN 1]" in joined                          # 归因跑了

    def test_literal_form_fixed_upfront(self, monkeypatch, tmp_path):
        """值形态开局修正：char 列裸数值（c.status=1）→ SQL 里已是 = '1'，并披露声明错误。"""
        (tmp_path / "_internal").mkdir(exist_ok=True)
        (tmp_path / "_internal" / "schema_cache.json").write_text(json.dumps(
            {"tables": {"dim.dim_cust": {"status": "varchar(2)"}}}), encoding="utf-8")
        self._write_ts(tmp_path, [
            {"alias": "c", "type": "LEFT JOIN",
             "condition": "a.cust_code = c.cust_code and c.status = 1"}])

        def h(sql):
            if " AS jc " in sql:
                return [{"jc": 50}]
            return [{"total": 50, "uniq": 50, "nulls": 0}]

        lines, _, ex = _run(monkeypatch, tmp_path, json.loads((tmp_path / "ts.json").read_text()), h)
        joined = "\n".join(lines)
        assert "字面量形态" in joined and "声明本身需修正" in joined
        assert "c.status = '1'" in "\n".join(ex.captured)   # 开局修正进 SQL，无重试
        assert "c.status = 1" not in "\n".join(ex.captured).replace("c.status = '1'", "")

    def test_hits_carries_partner_filter(self, monkeypatch, tmp_path):
        """实锤查询带伙伴侧过滤（规则 filter 归属项剥别名后拼入——不带会误计已排除行）。"""
        def h(sql):
            if "GROUP BY" in sql:
                return [{"cust_code": "C001", "c": 3}]
            if " IN (" in sql:
                return [{"hits": 2}]
            if "dim_cust" in sql:
                return [{"total": 90, "uniq": 88, "nulls": 0}]
            return [{"total": 100, "uniq": 100, "nulls": 0}]

        ts = self._write_ts(tmp_path, [
            {"alias": "c", "type": "LEFT JOIN", "condition": "a.cust_code = c.cust_code"}],
            rule_filter="a.del_flag = 'N' and c.tenant = 9")
        lines, _, ex = _run(monkeypatch, tmp_path, json.loads((tmp_path / "ts.json").read_text()), h)
        hits_sql = next(s for s in ex.captured if " IN (" in s)
        # 伙伴=c 的对端是驱动表 a——伙伴侧过滤=a 的归属项进实锤查询（不带会误计已排除行）
        assert "del_flag = 'N'" in hits_sql


def test_rule_not_found_raises(tmp_path):
    (tmp_path / "ts.json").write_text(json.dumps({"rules": {}}), encoding="utf-8")
    from diagnose_fanout import diagnose
    with pytest.raises(ValueError, match="没有规则"):
        diagnose(tmp_path / "ts.json", "R9999")
