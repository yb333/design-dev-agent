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
CODING_REFS = Path(__file__).resolve().parent.parent / "skills" / "dws-coding" / "scripts"
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

    def test_compact_view_compresses_direct(self, ts_data):
        """compact 模式：direct 字段压成单行字符串"""
        from slice_ts import slice_rule, to_compact_view
        sliced = slice_rule(ts_data, "R0001")
        compact = to_compact_view(sliced)
        # direct 字段应在 fields_direct（字符串列表）
        assert "fields_direct" in compact
        assert "fields_detail" in compact
        # compact 不应再有旧的 fields 键
        assert "fields" not in compact
        # fields_direct 是字符串列表（每个是一行）
        for line in compact["fields_direct"]:
            assert isinstance(line, str)
            assert " | direct | " in line  # 格式: target | type | direct | alias.src

    def test_compact_keeps_non_direct_detail(self, ts_data):
        """compact 模式：非 direct 字段完整保留在 fields_detail"""
        from slice_ts import slice_rule, to_compact_view
        sliced = slice_rule(ts_data, "R0001")
        compact = to_compact_view(sliced)
        # 非 direct 字段（aggregate/assign等）应在 fields_detail 完整
        for f in compact["fields_detail"]:
            assert isinstance(f, dict)
            assert "target_field" in f
            assert f.get("transform_type") != "direct"

    def test_compact_keeps_rule_info(self, ts_data):
        """compact 模式：规则信息（joins/grain/ctes等）原样保留"""
        from slice_ts import slice_rule, to_compact_view
        sliced = slice_rule(ts_data, "R0001")
        compact = to_compact_view(sliced)
        for key in ("rule_code", "rule_name", "joins", "join_safety", "grain", "ctes", "_global"):
            assert key in compact, f"compact 丢了规则信息: {key}"

    def test_compact_direct_field_format(self, ts_data):
        """compact 的 direct 行格式: target | type | direct | alias.src"""
        from slice_ts import _compact_direct_field
        f = {
            "target_field": "user_name", "field_type": "varchar(100)",
            "transform_type": "direct",
            "source_fields": [{"table": "t1", "field": "user_name", "alias": "t"}],
        }
        line = _compact_direct_field(f)
        assert line == "user_name | varchar(100) | direct | t.user_name"

    def test_compact_direct_field_missing_alias(self, ts_data):
        """compact 的 direct 字段缺 alias → 用 ? 标记（不崩）"""
        from slice_ts import _compact_direct_field
        f = {
            "target_field": "x", "field_type": "int", "transform_type": "direct",
            "source_fields": [{"table": "t1", "field": "", "alias": ""}],
        }
        line = _compact_direct_field(f)
        assert "?" in line  # 缺 alias/field → ?

    def test_compact_view_smaller_than_full(self, ts_data):
        """compact 模式 YAML 体积应小于全量（direct 多时明显）"""
        import yaml
        from slice_ts import slice_rule, to_compact_view
        sliced = slice_rule(ts_data, "R0001")
        full_yaml = yaml.dump(sliced, allow_unicode=True, default_flow_style=False)
        compact = to_compact_view(sliced)
        compact_yaml = yaml.dump(compact, allow_unicode=True, default_flow_style=False)
        assert len(compact_yaml) <= len(full_yaml)


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

    # ---- 输出格式：大规则字段列表折行 + 计数汇总 ----

    def test_format_field_list_wraps(self):
        """_format_field_list 超过 per_line 个字段应折行"""
        from check_sql import _format_field_list
        result = _format_field_list({"a", "b", "c", "d", "e", "f", "g"}, per_line=5)
        # 7个字段，每行5个 → 两行
        assert result.count("\n") == 1
        # 第一行5个，第二行2个
        lines = result.split("\n")
        assert len(lines[0].split(",")) == 5
        assert len(lines[1].split(",")) == 2

    def test_format_field_list_sorted(self):
        """_format_field_list 应排序输出"""
        from check_sql import _format_field_list
        result = _format_field_list({"c", "a", "b"})
        assert result.startswith("  a, b, c")

    def test_missing_fields_issue_has_count(self, ts_data):
        """缺字段时 issue 应含计数 '共 N 个'"""
        from check_sql import check_sql
        bad_sql = "SELECT t.contract_no AS contract_no, 'N' AS del_flag FROM fin_dwl_cnb.dwl_con_pu_mtr_f t"
        issues = check_sql(bad_sql, ts_data, "R0001")
        missing_issues = [i for i in issues if "缺少字段" in i]
        assert len(missing_issues) > 0
        assert "共" in missing_issues[0]
        assert "个" in missing_issues[0]

    def test_missing_fields_not_truncated(self, ts_data):
        """大量缺失字段时，issue 应完整列出所有字段（不截断）"""
        from check_sql import check_sql
        # 只写一个字段，缺其余所有
        bad_sql = "SELECT t.contract_no AS contract_no, 'N' AS del_flag FROM fin_dwl_cnb.dwl_con_pu_mtr_f t"
        issues = check_sql(bad_sql, ts_data, "R0001")
        missing_issue = [i for i in issues if "缺少字段" in i][0]
        # 应包含换行（折行显示）
        assert "\n" in missing_issue

    # ---- 行注释检测（规范：一律用 /* */ 块注释，禁 --）----

    def test_line_comment_detected(self):
        """-- 行注释应被检测到"""
        from check_sql import check_no_line_comment
        sql = "SELECT t.id AS id -- 取ID\nFROM t"
        ok, msg = check_no_line_comment(sql)
        assert not ok
        assert "行注释" in msg

    def test_block_comment_ok(self):
        """/* */ 块注释不应报错"""
        from check_sql import check_no_line_comment
        sql = "/* 取ID */ SELECT t.id AS id FROM t"
        ok, msg = check_no_line_comment(sql)
        assert ok

    def test_date_literal_not_flagged(self):
        """日期字面量里的 - 不应误判为行注释"""
        from check_sql import check_no_line_comment
        sql = "SELECT t.id AS id FROM t WHERE dt >= '${BIZ_DATE_START}'"
        ok, msg = check_no_line_comment(sql)
        assert ok, f"日期字面量误判: {msg}"

    def test_string_with_dash_not_flagged(self):
        """字符串字面量里的 dash 不应误判"""
        from check_sql import check_no_line_comment
        sql = "SELECT t.id AS id FROM t WHERE name = 'a-b-c'"
        ok, msg = check_no_line_comment(sql)
        assert ok, f"字符串 dash 误判: {msg}"

    def test_check_sql_reports_line_comment(self, ts_data):
        """check_sql 主函数应把 -- 行注释报为问题"""
        from check_sql import check_sql
        sql = """
        SELECT t.contract_no AS contract_no,
               'N' AS del_flag
        FROM fin_dwl_cnb.dwl_con_pu_mtr_f t
        -- 这是行注释
        """
        issues = check_sql(sql, ts_data, "R0001")
        assert any("行注释" in i for i in issues)

    # ---- CTE（WITH ... AS (...)）相关：回归 012 大案例发现的误报 ----

    def test_split_cte_main_extracts_cte_names(self):
        """split_cte_main 应解析出所有顶层 CTE 名，并返回主查询体"""
        from check_sql import split_cte_main
        sql = """
        WITH order_agg AS (SELECT user_id, COUNT(1) AS c FROM ods.o GROUP BY user_id),
             pay_agg AS (SELECT user_id, SUM(amt) AS s FROM ods.p GROUP BY user_id)
        SELECT oa.user_id AS user_id, oa.c AS order_cnt, pa.s AS pay_amt
        FROM order_agg oa
        LEFT JOIN pay_agg pa ON oa.user_id = pa.user_id
        """
        cte_names, main = split_cte_main(sql)
        assert cte_names == ["order_agg", "pay_agg"]
        assert main.strip().upper().startswith("SELECT")

    def test_cte_internal_aliases_not_flagged_as_extra(self, ts_data):
        """CTE 内部的 AS 别名不应被误判为主 SELECT 的输出字段"""
        from check_sql import check_sql, split_cte_main, extract_select_aliases
        # 用一个含 CTE 的 SELECT：内部 _rn / r_score 等不应进入主查询字段集
        sql = """
        WITH agg AS (
            SELECT t.contract_no AS contract_no, ROW_NUMBER() OVER (PARTITION BY t.contract_no ORDER BY t.dt) AS r_score
            FROM fin_dwl_cnb.dwl_con_pu_mtr_f t
        )
        SELECT a.contract_no AS contract_no,
               'N' AS del_flag, '${P_CYCLE_ID}' AS crt_cycle_id,
               '${P_CYCLE_ID}' AS last_upd_cycle_id, CURRENT_TIMESTAMP AS dw_last_update_date
        FROM agg a
        """
        # 主查询别名里不应有 r_score（那是 CTE 内部的）
        aliases = extract_select_aliases(sql)
        assert "r_score" not in aliases
        assert "contract_no" in aliases
        # 字段覆盖检查不应把 r_score 报成"多出的字段"
        issues = check_sql(sql, ts_data, "R0001")
        extra_issues = [i for i in issues if "没定义的字段" in i]
        assert len(extra_issues) == 0, f"不应把 CTE 内部别名报为多余字段: {extra_issues}"

    def test_cte_names_treated_as_legit_tables(self, ts_data):
        """主 SELECT 引用的 CTE 名不应被报为未知表"""
        from check_sql import check_sql
        sql = """
        WITH agg AS (SELECT t.contract_no AS contract_no FROM fin_dwl_cnb.dwl_con_pu_mtr_f t)
        SELECT a.contract_no AS contract_no,
               'N' AS del_flag, '${P_CYCLE_ID}' AS crt_cycle_id,
               '${P_CYCLE_ID}' AS last_upd_cycle_id, CURRENT_TIMESTAMP AS dw_last_update_date
        FROM agg a
        """
        issues = check_sql(sql, ts_data, "R0001")
        table_issues = [i for i in issues if "表引用" in i]
        assert len(table_issues) == 0, f"CTE 名不应被报为未知表: {table_issues}"

    def test_group_by_key_from_grain_not_flagged(self, ts_data):
        """聚合规则按 grain.output 的分组键 SELECT 出来时，不应报为多余字段"""
        from check_sql import check_sql
        # ts_data 的 R0001 是聚合规则；构造一个带分组键 user_id 的 SELECT（即便 user_id 不在 fields 里）
        # 这里用 contract_no（在 fields 里）作为分组键模拟，确保不误报
        sql = """
        SELECT t.contract_no AS contract_no,
               'N' AS del_flag, '${P_CYCLE_ID}' AS crt_cycle_id,
               '${P_CYCLE_ID}' AS last_upd_cycle_id, CURRENT_TIMESTAMP AS dw_last_update_date
        FROM fin_dwl_cnb.dwl_con_pu_mtr_f t
        """
        issues = check_sql(sql, ts_data, "R0001")
        extra_issues = [i for i in issues if "没定义的字段" in i]
        assert len(extra_issues) == 0, f"grain 分组键不应报为多余字段: {extra_issues}"


# ============================================================
# assemble_ddl.py 测试
# ============================================================

# TestAssembleDdl 已迁移到 test_assemble_ddl.py（更完整的覆盖）


# ============================================================
# run_ut.py 的 INSERT 包装测试
# ============================================================

class TestInsertWrapping:
    def test_wrap_insert_basic(self):
        """INSERT 包装基本功能"""
        from run_ut import wrap_insert
        select = "SELECT t.col1 AS col1, 'N' AS del_flag FROM table t"
        # table_fields = 表的全部字段（含审计）
        table_fields = [{"target_field": "col1"}, {"target_field": "del_flag"}]
        result = wrap_insert(select, "schema.target_table", table_fields)
        assert "INSERT INTO schema.target_table" in result
        assert "col1" in result
        assert "del_flag" in result
        assert "SELECT t.col1" in result

    def test_wrap_insert_preserves_select(self):
        """INSERT 包装应保留 SELECT 内容"""
        from run_ut import wrap_insert
        select = "SELECT\n    t.x AS x,\n    'N' AS del_flag\nFROM t"
        table_fields = [{"target_field": "x"}, {"target_field": "del_flag"}]
        result = wrap_insert(select, "schema.tbl", table_fields)
        assert "t.x AS x" in result
        assert "FROM t" in result

    def test_insert_columns_follow_select_order_not_table_fields(self):
        """★ INSERT 字段列表按 SELECT 输出顺序，不按 table_fields 顺序（模拟平台行为）"""
        from run_ut import wrap_insert
        # table_fields 顺序: a, b, c
        table_fields = [{"target_field": "a"}, {"target_field": "b"},
                        {"target_field": "c"}, {"target_field": "del_flag"}]
        # SELECT 输出顺序: c, a, b（与 table_fields 不一致）
        select = "SELECT t.c3 AS c, t.c1 AS a, t.c2 AS b, 'N' AS del_flag FROM t"
        result = wrap_insert(select, "schema.tbl", table_fields)
        # INSERT 字段列表应该是 c, a, b, del_flag（SELECT 顺序）
        # 验证：INSERT(...)<到>SELECT 之间的字段列表保持 SELECT 顺序
        insert_cols_section = result.split("INSERT INTO schema.tbl (")[1].split(")")[0]
        cols = [c.strip() for c in insert_cols_section.split(",")]
        assert cols == ["c", "a", "b", "del_flag"], f"INSERT 字段顺序应跟 SELECT，实际 {cols}"

    def test_insert_columns_with_string_table_fields(self):
        """table_fields 是字符串列表时，INSERT 字段顺序仍按 SELECT"""
        from run_ut import wrap_insert
        table_fields = ["a", "b", "del_flag"]
        select = "SELECT t.b AS b, t.a AS a, 'N' AS del_flag FROM t"
        result = wrap_insert(select, "schema.tbl", table_fields)
        insert_cols_section = result.split("INSERT INTO schema.tbl (")[1].split(")")[0]
        cols = [c.strip() for c in insert_cols_section.split(",")]
        assert cols == ["b", "a", "del_flag"]

    def test_insert_fallback_to_table_fields_when_no_aliases(self):
        """SELECT 无 AS 别名时，回退到 table_fields 顺序兜底"""
        from run_ut import wrap_insert
        table_fields = [{"target_field": "a"}, {"target_field": "b"}]
        # 无 AS 别名（解析不出顺序）
        select = "SELECT t.a, t.b FROM t"
        result = wrap_insert(select, "schema.tbl", table_fields)
        assert "a" in result and "b" in result  # 回退不崩


# ============================================================
# wrap_write 测试：按 load_mode 拼 INSERT/MERGE
# ============================================================

class TestWrapWrite:
    """wrap_write 按 load_mode 产生不同的写入语句（模拟平台）。"""

    def _select(self):
        return "SELECT t.id AS id, 'N' AS del_flag FROM tmp t"

    def _fields(self):
        return [{"target_field": "id"}, {"target_field": "del_flag"}]

    def test_truncate_table_returns_insert(self):
        """truncate_table → 走 INSERT（和 wrap_insert 一致）"""
        from run_ut import wrap_write
        result = wrap_write(self._select(), "sch.tbl", self._fields(),
                            "truncate_table", "")
        assert "INSERT INTO" in result
        assert "MERGE" not in result

    def test_no_delete_returns_insert(self):
        """no_delete → 走 INSERT"""
        from run_ut import wrap_write
        result = wrap_write(self._select(), "sch.tbl", self._fields(),
                            "no_delete", "")
        assert "INSERT INTO" in result

    def test_delete_returns_insert(self):
        """delete → 走 INSERT（删除由 ut_execute 预处理做）"""
        from run_ut import wrap_write
        result = wrap_write(self._select(), "sch.tbl", self._fields(),
                            "delete", "rule_id>0")
        assert "INSERT INTO" in result

    def test_partition_returns_insert(self):
        """truncate_partition → 走 INSERT（分区清空由 ut_execute 预处理做）"""
        from run_ut import wrap_write
        result = wrap_write(self._select(), "sch.tbl", self._fields(),
                            "truncate_partition", "P_1001")
        assert "INSERT INTO" in result

    def test_merge_into_produces_merge_statement(self):
        """★ merge_into → 拼 MERGE INTO ... ON ... WHEN MATCHED/NOT MATCHED"""
        from run_ut import wrap_write
        result = wrap_write(self._select(), "sch.tbl", self._fields(),
                            "merge_into", "T.id=T1.id")
        assert "MERGE INTO sch.tbl T" in result
        assert "USING" in result
        assert "T1" in result  # 源别名
        assert "ON T.id=T1.id" in result
        assert "WHEN MATCHED THEN UPDATE SET" in result
        assert "WHEN NOT MATCHED THEN INSERT" in result

    def test_merge_columns_follow_select_order(self):
        """★ MERGE 的 INSERT/UPDATE 字段也按 SELECT 顺序（和平台一致）"""
        from run_ut import wrap_write
        # table_fields 顺序 a,b；SELECT 顺序 b,a
        fields = [{"target_field": "a"}, {"target_field": "b"}]
        select = "SELECT t.fb AS b, t.fa AS a FROM t"
        result = wrap_write(select, "sch.tbl", fields, "merge_into", "T.a=T1.a")
        # INSERT VALUES 的字段顺序应跟 SELECT: b, a
        insert_values = result.split("VALUES (")[1].split(")")[0]
        vals = [v.strip() for v in insert_values.split(",")]
        assert vals == ["T1.b", "T1.a"], f"MERGE INSERT 值顺序应跟 SELECT，实际 {vals}"

    def test_update_produces_merge_statement(self):
        """update → 同 merge（MERGE 语句）"""
        from run_ut import wrap_write
        result = wrap_write(self._select(), "sch.tbl", self._fields(),
                            "update", "T.id=T1.id")
        assert "MERGE INTO" in result

    def test_merge_no_condition_fallback_on_condition(self):
        """merge 无 write_condition → ON 用 1=1 兜底（不崩）"""
        from run_ut import wrap_write
        result = wrap_write(self._select(), "sch.tbl", self._fields(),
                            "merge_into", "")
        assert "ON 1=1" in result

    def test_merge_update_set_has_all_fields(self):
        """MERGE 的 UPDATE SET 覆盖所有字段"""
        from run_ut import wrap_write
        result = wrap_write(self._select(), "sch.tbl", self._fields(),
                            "merge_into", "T.id=T1.id")
        assert "T.id = T1.id" in result
        assert "T.del_flag = T1.del_flag" in result

    def test_merge_insert_values_uses_t1(self):
        """MERGE 的 INSERT VALUES 用 T1 别名"""
        from run_ut import wrap_write
        result = wrap_write(self._select(), "sch.tbl", self._fields(),
                            "merge_into", "T.id=T1.id")
        assert "T1.id" in result
        assert "T1.del_flag" in result


# ============================================================
# run_ut_check 测试（用 fake executor，不连库）
# 验证：主键重复/空值时捕获 samples 样例（数据质量回退包的硬数据来源）
# ============================================================

class _FakeResult:
    def __init__(self, success=True, rows=None, columns=None, error=None):
        self.success = success
        self.rows = rows or []
        self.columns = columns or []
        self.error = error


class _FakeExecutor:
    """按 SQL 子串匹配返回预设结果，模拟 executor.execute"""
    def __init__(self, responses):
        # responses: list of (sql_substr, _FakeResult)
        self.responses = responses
        self.calls = []

    def execute(self, sql):
        self.calls.append(sql)
        for substr, result in self.responses:
            if substr in sql:
                return result
        return _FakeResult(success=True, rows=[{"cnt": 0}], columns=["cnt"])


class TestRunUtCheck:
    def test_pk_unique_pass_no_samples(self):
        """主键无重复：PASS 且不带 samples"""
        from run_ut import run_ut_check
        exe = _FakeExecutor([
            ("HAVING COUNT(*)", _FakeResult(rows=[])),  # 主键无重复
            ("IS NULL", _FakeResult(rows=[{"cnt": 0}])),  # 审计字段无空值
        ])
        results = run_ut_check(exe, "schema.tbl", ["id"], {"del_flag": {}})
        pk_check = [c for c in results if c["check"] == "业务主键唯一"][0]
        assert pk_check["status"] == "PASS"
        assert "samples" not in pk_check

    def test_pk_duplicate_captures_samples(self):
        """主键重复：FAIL 且 samples 含重复键样例（LIMIT 5）"""
        from run_ut import run_ut_check
        dup_rows = [
            {"id": "A1", "cnt": 3},
            {"id": "A2", "cnt": 2},
        ]
        exe = _FakeExecutor([
            ("HAVING COUNT(*)", _FakeResult(rows=dup_rows)),  # 主键重复
            ("IS NULL", _FakeResult(rows=[{"cnt": 0}])),  # 审计字段无空值
        ])
        results = run_ut_check(exe, "schema.tbl", ["id"], {"del_flag": {}})
        pk_check = [c for c in results if c["check"] == "业务主键唯一"][0]
        assert pk_check["status"] == "FAIL"
        assert pk_check["samples"] == dup_rows
        assert "A1" in str(pk_check["samples"])

    def test_pk_query_uses_limit_5(self):
        """主键重复检查 SQL 必须带 LIMIT 5（防抓一堆数据）"""
        from run_ut import run_ut_check
        exe = _FakeExecutor([
            ("COUNT(*) AS cnt FROM schema.tbl", _FakeResult(rows=[{"cnt": 10}])),
            ("HAVING COUNT(*)", _FakeResult(rows=[])),
        ])
        run_ut_check(exe, "schema.tbl", ["id"], {})
        pk_sql = [c for c in exe.calls if "HAVING COUNT(*)" in c][0]
        assert "LIMIT 5" in pk_sql

    def test_audit_null_captures_samples(self):
        """审计字段空值：FAIL 且 samples 含空值行样例（LIMIT 3）"""
        from run_ut import run_ut_check
        null_rows = [{"id": "A1", "del_flag": None}, {"id": "A2", "del_flag": None}]
        exe = _FakeExecutor([
            ("GROUP BY id", _FakeResult(rows=[])),                     # 主键检查通过
            ("LIMIT 3", _FakeResult(rows=null_rows)),                  # 空值样例（特异子串放前）
            ("IS NULL", _FakeResult(rows=[{"cnt": 2}])),                # del_flag 空值计数
        ])
        results = run_ut_check(exe, "schema.tbl", ["id"], {"del_flag": {"type": "nvarchar(1)"}})
        null_check = [c for c in results if "审计字段非空(del_flag)" in c["check"]][0]
        assert null_check["status"] == "FAIL"
        assert null_check["samples"] == null_rows

    def test_audit_null_pass_no_samples(self):
        """审计字段无空值：PASS 且不带 samples"""
        from run_ut import run_ut_check
        exe = _FakeExecutor([
            ("GROUP BY id", _FakeResult(rows=[])),                      # 主键通过
            ("WHERE del_flag IS NULL", _FakeResult(rows=[{"cnt": 0}])),  # 无空值
        ])
        results = run_ut_check(exe, "schema.tbl", ["id"], {"del_flag": {}})
        null_check = [c for c in results if "审计字段非空(del_flag)" in c["check"]][0]
        assert null_check["status"] == "PASS"
        assert "samples" not in null_check

    def test_check_entries_contain_sql(self):
        """★ 每个 UT 检查 entry 含 sql 字段（供 ut_execute 落地 debug）"""
        from run_ut import run_ut_check
        exe = _FakeExecutor([
            ("GROUP BY id", _FakeResult(rows=[])),
            ("WHERE del_flag IS NULL", _FakeResult(rows=[{"cnt": 0}])),
        ])
        results = run_ut_check(exe, "schema.tbl", ["id"], {"del_flag": {}})
        for entry in results:
            assert "sql" in entry, f"检查 {entry.get('check')} 缺 sql 字段"
            assert isinstance(entry["sql"], str)
            assert len(entry["sql"]) > 0
        # 行数检查的 SQL 含 COUNT
        count_check = [c for c in results if "行数" in c["check"]][0]
        assert "COUNT(*)" in count_check["sql"]
        # 主键检查的 SQL 含 GROUP BY
        pk_check = [c for c in results if "主键" in c["check"]][0]
        assert "GROUP BY" in pk_check["sql"]


# ============================================================
# ut_execute._dump_rule_sql 测试（SQL 落地 debug 用）
# ============================================================

class TestDumpRuleSql:
    def test_dump_creates_file(self, tmp_path):
        """落地生成 _internal/ut_sql/{rule}.sql 文件"""
        # 造 ts.json 路径（_dump_rule_sql 用 ts_path.parent 定位 _internal/）
        ts_path = tmp_path / "ddlc_design_dev" / "ts.json"
        ts_path.parent.mkdir(parents=True)
        ts_path.write_text("{}", encoding="utf-8")

        from ut_execute import _dump_rule_sql
        _dump_rule_sql(
            ts_path, "R0001", "dws.t",
            select_sql="SELECT t.id AS id FROM src t",
            insert_sql="INSERT INTO dws.t (id) SELECT t.id AS id FROM src t",
            insert_result="执行成功: 5 行",
            ut_checks=[
                {"check": "行数合理", "status": "PASS", "detail": "5 行",
                 "sql": "SELECT COUNT(*) AS cnt FROM dws.t"},
            ],
        )
        out = ts_path.parent / "_internal" / "ut_sql" / "R0001.sql"
        assert out.exists()

    def test_dump_contains_all_sections(self, tmp_path):
        """落地文件含三段：原始SELECT + 拼接INSERT + UT检查"""
        ts_path = tmp_path / "ddlc_design_dev" / "ts.json"
        ts_path.parent.mkdir(parents=True)
        ts_path.write_text("{}", encoding="utf-8")

        from ut_execute import _dump_rule_sql
        _dump_rule_sql(
            ts_path, "R0001", "dws.t",
            select_sql="SELECT t.id AS id FROM src t",
            insert_sql="INSERT INTO dws.t (id)\nSELECT t.id AS id FROM src t",
            insert_result="执行成功: 5 行",
            ut_checks=[
                {"check": "行数合理", "status": "PASS", "detail": "5 行",
                 "sql": "SELECT COUNT(*) AS cnt FROM dws.t"},
            ],
        )
        out = ts_path.parent / "_internal" / "ut_sql" / "R0001.sql"
        content = out.read_text(encoding="utf-8")
        assert "原始 SELECT" in content
        assert "SELECT t.id AS id FROM src t" in content
        assert "拼接后 INSERT" in content
        assert "INSERT INTO dws.t" in content
        assert "UT 检查" in content
        assert "SELECT COUNT(*) AS cnt FROM dws.t" in content

    def test_dump_failure_result_recorded(self, tmp_path):
        """INSERT 失败时落地文件记录失败结果"""
        ts_path = tmp_path / "ddlc_design_dev" / "ts.json"
        ts_path.parent.mkdir(parents=True)
        ts_path.write_text("{}", encoding="utf-8")

        from ut_execute import _dump_rule_sql
        _dump_rule_sql(
            ts_path, "R0001", "dws.t",
            select_sql="SELECT t.id AS id FROM src t",
            insert_sql="INSERT INTO dws.t (id) SELECT t.id AS id FROM src t",
            insert_result="执行失败(SQL): column xxx does not exist",
            ut_checks=[],  # 失败时没跑 UT 检查
        )
        out = ts_path.parent / "_internal" / "ut_sql" / "R0001.sql"
        content = out.read_text(encoding="utf-8")
        assert "执行失败" in content
        assert "column xxx does not exist" in content

    def test_dump_includes_samples_when_present(self, tmp_path):
        """UT 检查有 samples 时落地文件带上样例数据"""
        ts_path = tmp_path / "ddlc_design_dev" / "ts.json"
        ts_path.parent.mkdir(parents=True)
        ts_path.write_text("{}", encoding="utf-8")

        from ut_execute import _dump_rule_sql
        _dump_rule_sql(
            ts_path, "R0001", "dws.t",
            select_sql="SELECT t.id AS id FROM src t",
            insert_sql="INSERT INTO dws.t (id) SELECT t.id AS id FROM src t",
            insert_result="执行成功: 5 行",
            ut_checks=[
                {"check": "业务主键唯一", "status": "FAIL", "detail": "2 个重复键",
                 "sql": "SELECT id, COUNT(*) FROM dws.t GROUP BY id HAVING COUNT(*) > 1",
                 "samples": [{"id": 1, "cnt": 3}, {"id": 2, "cnt": 2}]},
            ],
        )
        content = (ts_path.parent / "_internal" / "ut_sql" / "R0001.sql").read_text(encoding="utf-8")
        assert "样例数据" in content
        assert "id" in content  # sample 里有 id


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


# ============================================================
# resolve_all_params 的直接单元测试（不连库，防函数体被意外截断）
# ============================================================

class TestResolveAllParams:
    """resolve_all_params 行为测试。

    这个测试的存在意义：之前 resolve_sample_blocks 插入时把 resolve_all_params
    函数体撕裂了（无 return），但没有测试挡住——因为这个函数没有直接单元测试。
    现在补上，确保函数行为正确（有返回值、缺值时 exit）。
    """

    def test_returns_values_when_configured(self, tmp_path):
        """有 exec_params + 有 test_params → 返回正确参数值。"""
        import json
        from run_ut import resolve_all_params

        cfg = {
            "test_params": {"P_CYCLE_ID": {"type": "static", "value": "20260801000000"}},
            "sources": {"x": {"roles": {"admin": {"user": "a", "password": ""}, "etl": {"user": "e", "password": ""}}}},
        }
        cfg_path = tmp_path / "db.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

        ts = {"meta": {"schedule": {"exec_params": {"P_CYCLE_ID": {"desc": "批次号"}}}}}
        result = resolve_all_params(ts, str(cfg_path))
        assert result == {"P_CYCLE_ID": "20260801000000"}, f"应返回参数值: {result}"

    def test_returns_empty_when_no_exec_params(self, tmp_path):
        """无 exec_params → 返回空 dict。"""
        import json
        from run_ut import resolve_all_params

        cfg_path = tmp_path / "db.json"
        cfg_path.write_text("{}", encoding="utf-8")

        ts = {"meta": {"schedule": {}}}
        result = resolve_all_params(ts, str(cfg_path))
        assert result == {}, f"无 exec_params 应返回空 dict: {result}"

    def test_exits_when_missing_test_param(self, tmp_path):
        """有 exec_params + 缺 test_params → sys.exit(2)。"""
        import json
        from run_ut import resolve_all_params

        cfg = {
            "test_params": {},
            "sources": {"x": {"roles": {"admin": {"user": "a", "password": ""}, "etl": {"user": "e", "password": ""}}}},
        }
        cfg_path = tmp_path / "db.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

        ts = {"meta": {"schedule": {"exec_params": {"P_CYCLE_ID": {"desc": "批次号"}}}}}
        with pytest.raises(SystemExit) as exc_info:
            resolve_all_params(ts, str(cfg_path))
        assert exc_info.value.code == 2

    def test_resolve_password_missing_env(self, monkeypatch):
        """环境变量不存在返回空"""
        monkeypatch.delenv("NONEXISTENT_PW", raising=False)
        from dws_db import resolve_password
        assert resolve_password("${NONEXISTENT_PW}") == ""
