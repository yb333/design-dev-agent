"""参数化机制测试。

覆盖三层：
- 组装层：build_exec_params（标准注入 + 业务透传）
- 配置层：load_test_params（读 db-sources.json）
- 替换层：resolve_test_value（动态/静态） + substitute_params（替换/缺值报错）
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

# conftest 已把 design/coding scripts 加入 sys.path
from assemble_ts import build_exec_params
from dws_db import load_test_params

# run_ut 在 coding refs 下
from run_ut import resolve_test_value, substitute_params, DYNAMIC_EXPRS


# ============================================================
# 组装层：build_exec_params
# ============================================================

class TestBuildExecParams:
    """标准参数自动注入 + 业务参数透传"""

    def test_standard_only(self):
        """designer 不声明业务参数 → 只有 P_CYCLE_ID"""
        params = build_exec_params({})
        assert "P_CYCLE_ID" in params
        assert params["P_CYCLE_ID"]["standard"] is True
        assert params["P_CYCLE_ID"]["desc"] == "批次号"

    def test_with_business_params(self):
        """声明业务参数 → 标准参数 + 业务参数都进"""
        decisions = {"params": [
            {"name": "BIZ_DATE", "value_type": "date", "desc": "业务日期"},
            {"name": "ACCT_PERIOD", "value_type": "string", "desc": "会计期间"},
        ]}
        params = build_exec_params(decisions)
        assert params["P_CYCLE_ID"]["standard"] is True
        assert params["BIZ_DATE"]["standard"] is False
        assert params["BIZ_DATE"]["value_type"] == "date"
        assert params["ACCT_PERIOD"]["desc"] == "会计期间"

    def test_business_param_default_type(self):
        """业务参数没写 value_type → 默认 string"""
        decisions = {"params": [{"name": "X", "desc": "test"}]}
        params = build_exec_params(decisions)
        assert params["X"]["value_type"] == "string"

    def test_business_param_default_desc(self):
        """业务参数没写 desc → 空串"""
        decisions = {"params": [{"name": "X"}]}
        params = build_exec_params(decisions)
        assert params["X"]["desc"] == ""

    def test_empty_decisions(self):
        """空 decisions → 仅标准参数"""
        params = build_exec_params({})
        assert len(params) == 1
        assert "P_CYCLE_ID" in params


# ============================================================
# 配置层：load_test_params
# ============================================================

class TestLoadTestParams:
    """从 db-sources.json 读 test_params 段"""

    def test_read_test_params(self, tmp_path):
        cfg = {
            "default": "dws-dev",
            "sources": {},
            "test_params": {
                "P_CYCLE_ID": {"type": "dynamic", "expr": "today_ymdhms"},
            },
        }
        p = tmp_path / "db-sources.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")

        result = load_test_params(str(p))
        assert "P_CYCLE_ID" in result
        assert result["P_CYCLE_ID"]["expr"] == "today_ymdhms"

    def test_missing_file(self):
        """文件不存在 → 空字典（不报错，让上层 fail loud）"""
        result = load_test_params("/nonexistent/path/db-sources.json")
        assert result == {}

    def test_no_test_params_section(self, tmp_path):
        """配置里没 test_params 段 → 空字典"""
        cfg = {"default": "dws-dev", "sources": {}}
        p = tmp_path / "db-sources.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        assert load_test_params(str(p)) == {}


# ============================================================
# 替换层：resolve_test_value
# ============================================================

class TestResolveTestValue:
    """动态/静态值解析"""

    def test_static_value(self):
        cfg = {"type": "static", "value": "202608"}
        assert resolve_test_value("ACCT_PERIOD", cfg) == "202608"

    def test_dynamic_today_ymdhms(self):
        cfg = {"type": "dynamic", "expr": "today_ymdhms"}
        val = resolve_test_value("P_CYCLE_ID", cfg)
        # 今天日期拼 000000
        expected_prefix = datetime.now().strftime("%Y%m%d")
        assert val == expected_prefix + "000000"
        assert len(val) == 14

    def test_dynamic_today_ymd(self):
        cfg = {"type": "dynamic", "expr": "today_ymd"}
        val = resolve_test_value("BIZ_DATE", cfg)
        assert val == datetime.now().strftime("%Y%m%d")
        assert len(val) == 8

    def test_none_cfg_returns_none(self):
        """没配参数 → None（fail loud 信号）"""
        assert resolve_test_value("MISSING", None) is None

    def test_unknown_dynamic_expr(self):
        """未知动态表达式 → ValueError"""
        cfg = {"type": "dynamic", "expr": "nonexistent_expr"}
        with pytest.raises(ValueError, match="未知动态表达式"):
            resolve_test_value("X", cfg)

    def test_static_no_value_field(self):
        """static 但没 value 字段 → 空串"""
        cfg = {"type": "static"}
        assert resolve_test_value("X", cfg) == ""


# ============================================================
# 替换层：substitute_params
# ============================================================

class TestSubstituteParams:
    """${PARAM} → 实际值替换"""

    def test_single_replace(self):
        sql = "'${P_CYCLE_ID}' AS crt_cycle_id"
        result = substitute_params(sql, {"P_CYCLE_ID": "20260804000000"})
        assert "'20260804000000' AS crt_cycle_id" == result

    def test_multiple_distinct_params(self):
        sql = "WHERE dt >= '${BIZ_DATE}' AND cycle = '${P_CYCLE_ID}'"
        result = substitute_params(sql, {
            "P_CYCLE_ID": "20260804000000",
            "BIZ_DATE": "20260804",
        })
        assert "WHERE dt >= '20260804'" in result
        assert "cycle = '20260804000000'" in result

    def test_same_param_multiple_occurrences(self):
        sql = "'${P_CYCLE_ID}' AS crt, '${P_CYCLE_ID}' AS upd"
        result = substitute_params(sql, {"P_CYCLE_ID": "123"})
        assert result == "'123' AS crt, '123' AS upd"

    def test_no_placeholders(self):
        """SQL 里没有占位符 → 原样返回"""
        sql = "SELECT 1"
        assert substitute_params(sql, {"P_CYCLE_ID": "123"}) == "SELECT 1"

    def test_missing_value_raises(self):
        """SQL 用了参数但没给值 → ValueError（fail loud）"""
        sql = "'${UNKNOWN_PARAM}' AS x"
        with pytest.raises(ValueError, match="UNKNOWN_PARAM"):
            substitute_params(sql, {"P_CYCLE_ID": "123"})

    def test_empty_param_values(self):
        """param_values 为空且 SQL 有占位符 → 报错"""
        sql = "'${P_CYCLE_ID}' AS x"
        with pytest.raises(ValueError):
            substitute_params(sql, {})

    def test_param_name_pattern(self):
        """只匹配大写字母+下划线+数字的参数名，不误匹配小写"""
        sql = "'${P_CYCLE_ID}' AS x, '${lower_name}' AS y"
        result = substitute_params(sql, {"P_CYCLE_ID": "123"})
        # lower_name 不被替换（不匹配 [A-Z_] 开头）
        assert "${lower_name}" in result
        assert "123" in result

    def test_ddl_default_clause(self):
        """DDL 的 DEFAULT 子句里也含 ${P_CYCLE_ID}，应被替换"""
        ddl = (
            "CREATE TABLE t (\n"
            "  crt_cycle_id bigint DEFAULT '${P_CYCLE_ID}',\n"
            "  last_upd_cycle_id bigint DEFAULT '${P_CYCLE_ID}'\n"
            ")"
        )
        result = substitute_params(ddl, {"P_CYCLE_ID": "20260804000000"})
        assert "'20260804000000'" in result
        assert "${P_CYCLE_ID}" not in result


# ============================================================
# E2E：声明 → 组装 → 替换
# ============================================================

class TestE2EParamFlow:
    """端到端：design_decisions.params → build_exec_params → substitute_params"""

    def test_full_flow(self, tmp_path):
        """模拟完整链路：声明业务参数 → ts.json exec_params → SQL 替换"""
        # 1. designer 声明
        decisions = {"params": [
            {"name": "BIZ_DATE", "value_type": "date", "desc": "业务日期"},
        ]}

        # 2. 组装进 exec_params
        exec_params = build_exec_params(decisions)
        assert "P_CYCLE_ID" in exec_params
        assert "BIZ_DATE" in exec_params

        # 3. 配置测试值
        db_cfg = {
            "test_params": {
                "P_CYCLE_ID": {"type": "dynamic", "expr": "today_ymdhms"},
                "BIZ_DATE": {"type": "static", "value": "20260801"},
            }
        }
        db_path = tmp_path / "db-sources.json"
        db_path.write_text(json.dumps(db_cfg), encoding="utf-8")

        test_params = load_test_params(str(db_path))

        # 4. 算出实际值
        values = {}
        for pname in exec_params:
            values[pname] = resolve_test_value(pname, test_params.get(pname))

        assert len(values["P_CYCLE_ID"]) == 14  # 批次号是 14 位（YYYYMMDD + 000000）
        assert values["BIZ_DATE"] == "20260801"

        # 5. 替换进 SQL
        sql = (
            "SELECT '${P_CYCLE_ID}' AS crt_cycle_id, "
            "'${BIZ_DATE}' AS biz_date FROM t WHERE dt = '${BIZ_DATE}'"
        )
        result = substitute_params(sql, values)
        assert "${P_CYCLE_ID}" not in result
        assert "${BIZ_DATE}" not in result
        assert "20260801" in result
