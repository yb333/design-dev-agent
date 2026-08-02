"""
编码段核心脚本测试。

不依赖数据库——测的是脚本逻辑：
- slice_ts.py: 规则切片
- check_sql.py: 静态对比
- assemble_ddl.py: DDL 生成
- run_ut.py: INSERT 包装

用现有样例 ts.json（docs/output/dwl_con_pu_any_f/02_design/ts.json）做测试数据。
"""

import json
import sys
import pytest
from pathlib import Path

# 脚本目录
CODING_REFS = Path(__file__).resolve().parent.parent / "skills" / "dws-coding" / "references"
sys.path.insert(0, str(CODING_REFS))

# 样例 ts.json
SAMPLE_TS = Path(__file__).resolve().parent.parent / "docs" / "output" / "dwl_con_pu_any_f" / "02_design" / "ts.json"


@pytest.fixture
def ts_data():
    """加载样例 ts.json"""
    return json.loads(SAMPLE_TS.read_text(encoding="utf-8"))


# ============================================================
# slice_ts.py 测试
# ============================================================

class TestSliceTs:
    def test_slice_existing_rule(self, ts_data):
        """切片存在的规则"""
        from slice_ts import slice_rule
        result = slice_rule(ts_data, "R0001")
        assert result["rule_code"] == "R0001"
        assert result["target_table"] != ""
        assert len(result["fields"]) > 0
        assert "_global" in result
        assert "audit_fields" in result["_global"]

    def test_slice_nonexistent_rule(self, ts_data):
        """切片不存在的规则应报错"""
        from slice_ts import slice_rule
        with pytest.raises(ValueError, match="不存在"):
            slice_rule(ts_data, "R9999")

    def test_slice_has_design_logic(self, ts_data):
        """切片应包含 design_logic"""
        from slice_ts import slice_rule
        result = slice_rule(ts_data, "R0001")
        for f in result["fields"]:
            assert "design_logic" in f

    def test_slice_has_business_key(self, ts_data):
        """切片全局信息应包含 business_key"""
        from slice_ts import slice_rule
        result = slice_rule(ts_data, "R0001")
        assert "business_key" in result["_global"]


# ============================================================
# check_sql.py 测试
# ============================================================

class TestCheckSql:
    VALID_SELECT = """
    SELECT
        t.contract_no AS contract_no,
        t.contract_id AS contract_id,
        t.pu_id AS pu_id,
        t.currency_code AS tc_code,
        t.proj_key AS proj_key,
        pu.pu_key AS pu_key,
        SUM(CASE WHEN t.rpt_code = 'fbt_0001' THEN t.rpt_value_usd ELSE 0 END) AS equip_org_amt_usd,
        SUM(CASE WHEN t.rpt_code = 'fbt_0001' THEN t.rpt_value_rmb ELSE 0 END) AS equip_org_amt_rmb,
        SUM(CASE WHEN t.rpt_code = 'fbt_0002' THEN t.rpt_value_rmb ELSE 0 END) AS equip_cfm_amt_rmb,
        SUM(CASE WHEN t.rpt_code = 'fbt_0002' THEN t.rpt_value_usd ELSE 0 END) AS equip_cfm_amt_usd,
        COALESCE(inv_agg.inv_tol_amt_usd, 0) AS inv_tol_amt_usd,
        COALESCE(inv_agg.inv_tol_amt_rmb, 0) AS inv_tol_amt_rmb,
        'N' AS del_flag,
        '${P_CYCLE_ID}' AS crt_cycle_id,
        '${P_CYCLE_ID}' AS last_upd_cycle_id,
        CURRENT_TIMESTAMP AS dw_last_update_date
    FROM fin_dwl_cnb.dwl_con_pu_mtr_f t
    LEFT JOIN fin_dwl_cnb.dwl_con_any_f f ON t.contract_key = f.contract_key
    LEFT JOIN fin_dwl_cnb.dwr_dim_pu_d pu ON t.pu_id = pu.pu_id
    GROUP BY t.contract_no, t.contract_id, t.pu_id, t.currency_code, t.proj_key, pu.pu_key
    """

    def test_valid_select_passes(self, ts_data):
        """完整正确的 SELECT 应通过检查"""
        from check_sql import check_sql
        issues = check_sql(self.VALID_SELECT, ts_data, "R0001")
        # 可能有一些表引用警告（CTE 名），但不应有字段覆盖问题
        field_issues = [i for i in issues if "字段覆盖" in i and "缺少" in i]
        assert len(field_issues) == 0, f"不应有字段覆盖缺失: {field_issues}"

    def test_missing_field_detected(self, ts_data):
        """缺字段应被检测到"""
        from check_sql import check_sql
        bad_sql = """
        SELECT
            t.contract_no AS contract_no,
            'N' AS del_flag
        FROM fin_dwl_cnb.dwl_con_pu_mtr_f t
        """
        issues = check_sql(bad_sql, ts_data, "R0001")
        assert any("缺少字段" in i for i in issues)

    def test_select_star_detected(self, ts_data):
        """SELECT * 应被检测到"""
        from check_sql import check_sql
        bad_sql = "SELECT * FROM fin_dwl_cnb.dwl_con_pu_mtr_f t"
        issues = check_sql(bad_sql, ts_data, "R0001")
        assert any("SELECT *" in i for i in issues)

    def test_unknown_table_detected(self, ts_data):
        """引用不存在的表应被检测到"""
        from check_sql import check_sql
        bad_sql = """
        SELECT t.contract_no AS contract_no, 'N' AS del_flag
        FROM fin_dwl_cnb.unknown_table t
        """
        issues = check_sql(bad_sql, ts_data, "R0001")
        assert any("unknown_table" in i for i in issues)

    def test_bracket_imbalance_detected(self, ts_data):
        """括号不平衡应被检测到"""
        from check_sql import check_sql
        bad_sql = "SELECT t.x AS x FROM t WHERE ((t.x = 1)"
        issues = check_sql(bad_sql, ts_data, "R0001")
        assert any("括号" in i for i in issues)


# ============================================================
# assemble_ddl.py 测试
# ============================================================

class TestAssembleDdl:
    def test_generate_ddl_produces_files(self, ts_data):
        """生成 DDL 应产出内容"""
        from assemble_ddl import generate_ddl
        ddls = generate_ddl(ts_data)
        assert len(ddls) > 0
        for filename, content in ddls.items():
            assert "CREATE" in content.upper()
            assert len(content) > 0

    def test_ddl_has_audit_fields(self, ts_data):
        """DDL 应包含审计字段"""
        from assemble_ddl import generate_ddl
        ddls = generate_ddl(ts_data)
        # 找 CREATE TABLE（不是 VIEW）
        table_ddl = next((c for f, c in ddls.items() if "TABLE" in c), None)
        if table_ddl:
            assert "del_flag" in table_ddl
            assert "crt_cycle_id" in table_ddl
            assert "dw_last_update_date" in table_ddl

    def test_ddl_has_distribute_by(self, ts_data):
        """DDL 应有分布键"""
        from assemble_ddl import generate_ddl
        ddls = generate_ddl(ts_data)
        table_ddl = next((c for f, c in ddls.items() if "TABLE" in c and "VIEW" not in c.upper().split("TABLE")[0]), None)
        if table_ddl and ts_data.get("design", {}).get("distribution_key"):
            assert "DISTRIBUTE BY" in table_ddl

    def test_ddl_has_to_group(self, ts_data):
        """DDL 应有 TO GROUP"""
        from assemble_ddl import generate_ddl
        ddls = generate_ddl(ts_data)
        table_ddl = next((c for f, c in ddls.items() if "CREATE TABLE" in c), None)
        if table_ddl:
            assert "TO GROUP" in table_ddl

    def test_ddl_has_column_comments(self, ts_data):
        """DDL 应有字段注释"""
        from assemble_ddl import generate_ddl
        ddls = generate_ddl(ts_data)
        table_ddl = next((c for f, c in ddls.items() if "CREATE TABLE" in c), None)
        if table_ddl:
            assert "COMMENT ON COLUMN" in table_ddl


# ============================================================
# run_ut.py 的 INSERT 包装测试
# ============================================================

class TestInsertWrapping:
    def test_wrap_insert_basic(self):
        """INSERT 包装基本功能"""
        from run_ut import wrap_insert
        select = "SELECT t.col1 AS col1, 'N' AS del_flag FROM table t"
        fields = [{"target_field": "col1"}]
        audit = {"del_flag": {}, "crt_cycle_id": {}, "last_upd_cycle_id": {}, "dw_last_update_date": {}}
        result = wrap_insert(select, "schema.target_table", fields, audit)
        assert "INSERT INTO schema.target_table" in result
        assert "col1" in result
        assert "del_flag" in result
        assert "SELECT t.col1" in result

    def test_wrap_insert_preserves_select(self):
        """INSERT 包装应保留 SELECT 内容"""
        from run_ut import wrap_insert
        select = "SELECT\n    t.x AS x,\n    'N' AS del_flag\nFROM t"
        fields = [{"target_field": "x"}]
        audit = {"del_flag": {}}
        result = wrap_insert(select, "schema.tbl", fields, audit)
        assert "t.x AS x" in result
        assert "FROM t" in result


# ============================================================
# dws_db.py 的配置解析测试（不连库）
# ============================================================

class TestDbConfig:
    def test_resolve_password_plain(self):
        """明文密码直接返回"""
        from dws_db import resolve_password
        assert resolve_password("mypassword") == "mypassword"

    def test_resolve_password_env_var(self, monkeypatch):
        """环境变量密码解析"""
        monkeypatch.setenv("TEST_DB_PW", "secret123")
        from dws_db import resolve_password
        assert resolve_password("${TEST_DB_PW}") == "secret123"

    def test_resolve_password_missing_env(self, monkeypatch):
        """环境变量不存在返回空"""
        monkeypatch.delenv("NONEXISTENT_PW", raising=False)
        from dws_db import resolve_password
        assert resolve_password("${NONEXISTENT_PW}") == ""
