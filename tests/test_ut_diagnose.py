"""ut_diagnose.py 测试：类型转换失败的脏数据自动诊断。

用 fake executor 构造脏行，验证：
1. 跨类型字段圈定（源 varchar→目标 numeric 才探测，同 family 不探测）
2. 探测 SQL 拼接（count + 正则模式 + LIMIT 3）
3. 样例捕获
4. 无 schema_cache → __no_cache 提示
5. format_diagnosis 渲染
6. ut_execute 的 _is_type_conversion_error 识别

不连真库——通过 _FakeExecutor 按子串匹配返回预设结果。
"""

import json
from pathlib import Path

import pytest


# 复用 test_coding_scripts 的 fake executor 模式（这里独立定义，保持自包含）
class _FakeResult:
    def __init__(self, success=True, rows=None, columns=None, error=None):
        self.success = success
        self.rows = rows or []
        self.columns = columns or []
        self.error = error


class _FakeExecutor:
    """按 SQL 子串匹配返回预设结果（顺序敏感，首个命中者返回）。"""
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def execute(self, sql):
        self.calls.append(sql)
        for substr, result in self.responses:
            if substr in sql:
                return result
        return _FakeResult(success=True, rows=[{"cnt": 0}], columns=["cnt"])


def _ts_with_cross_type(target_table="ods.dwb_test_f", src_table="ods_test_di"):
    """构造 ts：含一个 varchar→numeric 跨类型字段 + 一个同 family 字段。"""
    return {
        "tables": {
            "dwb_test_f": {
                "fields": [
                    {
                        "target_field": "amount",          # 目标 numeric
                        "field_type": "numeric(18,2)",
                        "source_fields": [{"table": src_table, "field": "amount_str", "alias": "a"}],
                    },
                    {
                        "target_field": "order_id",         # 目标 varchar，源也 varchar（同 family，不探测）
                        "field_type": "varchar(64)",
                        "source_fields": [{"table": src_table, "field": "order_id", "alias": "a"}],
                    },
                    {
                        "target_field": "biz_date",         # 目标 date，源 varchar（字符→日期，探测）
                        "field_type": "date",
                        "source_fields": [{"table": src_table, "field": "biz_date_str", "alias": "a"}],
                    },
                ]
            }
        }
    }


def _rule(target_table="ods.dwb_test_f", src_table="ods_test_di"):
    return {
        "target_table": target_table,
        "source_tables": [{"schema": "ods", "table": src_table, "alias": "a"}],
    }


def _write_cache(tmp_path, src_table="ods_test_di"):
    """写 schema_cache.json：源表 amount_str/biz_date_str 是 varchar。"""
    cache = {
        "cached_at": "2026-08-13T00:00:00",
        "tables": {
            f"ods.{src_table}": {
                "amount_str": "varchar(50)",
                "biz_date_str": "varchar(20)",
                "order_id": "varchar(64)",
            }
        },
    }
    p = tmp_path / "schema_cache.json"
    p.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return p


# ============================================================
# 1. 跨类型圈定 + 探测 + 样例捕获
# ============================================================

class TestDiagnoseTypeError:
    def test_finds_dirty_numeric_and_date_fields(self, tmp_path):
        """varchar→numeric 与 varchar→date 字段都脏 → 两条诊断，含 count+样例。"""
        from ut_diagnose import diagnose_type_error
        cache_path = _write_cache(tmp_path)
        ts = _ts_with_cross_type()
        rule = _rule()
        # amount_str 脏 128 行；biz_date_str 脏 5 行
        # 响应顺序敏感：样例查询（AS val）放前，count 查询（含列名但无 AS val）放后
        exe = _FakeExecutor([
            ("amount_str AS val", _FakeResult(rows=[{"val": "N/A"}, {"val": "-"}])),  # amount 样例
            ("biz_date_str AS val", _FakeResult(rows=[{"val": "2026/13/99"}])),       # biz_date 样例
            ("amount_str", _FakeResult(rows=[{"cnt": 128}], columns=["cnt"])),        # amount count
            ("biz_date_str", _FakeResult(rows=[{"cnt": 5}], columns=["cnt"])),        # biz_date count
        ])
        entries = diagnose_type_error(exe, rule, ts, cache_path)
        targets = {e["target_field"] for e in entries}
        assert "amount" in targets and "biz_date" in targets
        amt = [e for e in entries if e["target_field"] == "amount"][0]
        assert amt["dirty_count"] == 128
        assert "N/A" in amt["samples"]
        # order_id 同 family 不该被探测（不在结果）
        assert "order_id" not in targets

    def test_probe_sql_uses_regex_and_limit(self, tmp_path):
        """探测 SQL 含正则模式 !~ 和 LIMIT 3（count 也要带模式条件）。"""
        from ut_diagnose import diagnose_type_error
        cache_path = _write_cache(tmp_path)
        exe = _FakeExecutor([("AS val", _FakeResult(rows=[{"val": "x"}]))])
        diagnose_type_error(exe, _rule(), _ts_with_cross_type(), cache_path)
        # 样例查询必须带 LIMIT 3
        sample_sqls = [c for c in exe.calls if "AS val" in c]
        assert sample_sqls, "应有样例探测 SQL"
        assert all("LIMIT 3" in s for s in sample_sqls)
        # count/样例 SQL 都应含正则 !~
        assert all("!~" in s for s in sample_sqls)

    def test_clean_field_not_reported(self, tmp_path):
        """字段跨类型但无脏数据（count=0）→ 不报（避免全干净噪音）。"""
        from ut_diagnose import diagnose_type_error
        cache_path = _write_cache(tmp_path)
        exe = _FakeExecutor([
            # 所有 count 都返回 0（默认 _FakeExecutor 兜底 {cnt:0}，这里显式）
            ("count(*) AS cnt", _FakeResult(rows=[{"cnt": 0}])),
        ])
        entries = diagnose_type_error(exe, _rule(), _ts_with_cross_type(), cache_path)
        assert entries == [], f"无脏数据不应报诊断: {entries}"

    def test_no_cache_returns_no_cache_marker(self, tmp_path):
        """schema_cache 不存在 → 返回 __no_cache 标志。"""
        from ut_diagnose import diagnose_type_error
        exe = _FakeExecutor([])
        entries = diagnose_type_error(exe, _rule(), _ts_with_cross_type(),
                                      tmp_path / "absent.json")
        assert len(entries) == 1 and entries[0].get("__no_cache") is True

    def test_source_not_in_cache_skipped(self, tmp_path):
        """源表不在 schema_cache → 该字段跳过（无类型无法判）。"""
        from ut_diagnose import diagnose_type_error
        cache_path = _write_cache(tmp_path, src_table="other_table")  # 不同表名
        exe = _FakeExecutor([("AS val", _FakeResult(rows=[{"val": "x"}]))])
        entries = diagnose_type_error(exe, _rule(src_table="ods_test_di"),
                                      _ts_with_cross_type(), cache_path)
        assert entries == [], "源表不在缓存应跳过"

    def test_probe_exception_swallowed(self, tmp_path):
        """探测异常不抛出（增益不是依赖）。"""
        from ut_diagnose import diagnose_type_error
        cache_path = _write_cache(tmp_path)

        class BoomExecutor:
            def execute(self, sql):
                raise RuntimeError("连接断了")
        entries = diagnose_type_error(BoomExecutor(), _rule(), _ts_with_cross_type(), cache_path)
        # 异常被吞，count 取不到 → 无脏数据报告 → 空
        assert entries == []

    def test_non_high_value_family_not_probed(self, tmp_path):
        """目标 boolean/varchar 等非高价值 family → 不探测。"""
        from ut_diagnose import diagnose_type_error, _dirty_pattern
        # _dirty_pattern 只对 numeric/integer/datetime 返回模式
        assert _dirty_pattern("numeric") is not None
        assert _dirty_pattern("datetime") is not None
        assert _dirty_pattern("varchar") is None
        assert _dirty_pattern("boolean") is None


# ============================================================
# 2. format_diagnosis 渲染
# ============================================================

class TestFormatDiagnosis:
    def test_renders_dirty_entries(self):
        from ut_diagnose import format_diagnosis
        text = format_diagnosis([
            {"target_field": "amount", "target_type": "numeric(18,2)",
             "source": "ods.t.amount_str", "source_type": "varchar(50)",
             "dirty_count": 128, "samples": ["N/A", "-", "1,000"]},
        ])
        assert "字段 amount" in text
        assert "128 行脏数据" in text
        assert "'N/A'" in text and "'1,000'" in text
        assert "根因判断" in text

    def test_renders_no_cache_honestly(self):
        from ut_diagnose import format_diagnosis
        text = format_diagnosis([{"__no_cache": True}])
        assert "未连库无 schema_cache" in text

    def test_renders_empty_honestly(self):
        from ut_diagnose import format_diagnosis
        text = format_diagnosis([])
        assert "未识别到嫌疑字段" in text


# ============================================================
# 3. ut_execute 的类型报错识别（_is_type_conversion_error）
# ============================================================

class TestTypeErrorDetection:
    def test_detects_invalid_input_syntax(self):
        from ut_execute import _is_type_conversion_error
        assert _is_type_conversion_error(
            'ERROR: invalid input syntax for type numeric: "N/A"')

    def test_detects_cast_error(self):
        from ut_execute import _is_type_conversion_error
        assert _is_type_conversion_error("CAST failed: cannot convert")

    def test_ignores_column_missing(self):
        """字段不存在的报错不算类型转换（不该触发诊断）。"""
        from ut_execute import _is_type_conversion_error
        assert not _is_type_conversion_error('column "foo" does not exist')
        assert not _is_type_conversion_error("permission denied")

    def test_ignores_empty(self):
        from ut_execute import _is_type_conversion_error
        assert not _is_type_conversion_error("")
