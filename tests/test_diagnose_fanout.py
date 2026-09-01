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
    def __init__(self, rows):
        self.success, self.rows = True, rows


class _FakeEx:
    """按 SQL 特征回放结果；capture 收集全部 SQL 供断言（复合键/过滤是否真进了查询）。"""

    def __init__(self, handler):
        self.h = handler
        self.captured: list[str] = []

    def test_connection(self):
        return True

    def execute(self, sql):
        self.captured.append(sql)
        return _R(self.h(sql))

    def close(self):
        pass


def _patch(monkeypatch, handler):
    import dws_db
    ex = _FakeEx(handler)

    def _create(schema, role="etl"):
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
        assert "c.is_current = 1" in joined                     # condition 字面量项并入
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
        assert "c.del_flag = 'N'" in joined and "c.is_current = 1" in joined

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


def test_rule_not_found_raises(tmp_path):
    (tmp_path / "ts.json").write_text(json.dumps({"rules": {}}), encoding="utf-8")
    from diagnose_fanout import diagnose
    with pytest.raises(ValueError, match="没有规则"):
        diagnose(tmp_path / "ts.json", "R9999")
