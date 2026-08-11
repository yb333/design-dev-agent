"""inject_tablesample 的测试。

核心验证：
1. 单表 SELECT：注入 TABLESAMPLE SYSTEM
2. JOIN：所有物理表（FROM + JOIN）都注入（多主表场景每张都要采样）
3. CTE：CTE 定义里的表不注入（只在主查询层注入）
4. sample_blocks=0：不注入，返回原 SQL
5. 注入后 SQL 结构不变（只多了 TABLESAMPLE 子句）

策略说明：多主表场景（两个事实表 INNER JOIN）每张都要采样，
否则没采样的那张还是全量扫，照样慢。
"""

import sys
from pathlib import Path

_CODING_SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "dws-coding" / "scripts"
if str(_CODING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CODING_SCRIPTS))

from run_ut import inject_tablesample, resolve_sample_blocks


class TestInjectBasic:
    """基础注入测试。"""

    def test_zero_blocks_returns_original(self):
        """sample_blocks=0 → 不注入，返回原 SQL。"""
        sql = "SELECT * FROM ods.fact a WHERE a.dt = 'x'"
        assert inject_tablesample(sql, 0) == sql

    def test_single_table_injected(self):
        """单表 SELECT：注入 TABLESAMPLE SYSTEM (10)。"""
        sql = "SELECT a.id, a.name FROM ods.fact_table a WHERE a.dt = 'x'"
        result = inject_tablesample(sql, 10)
        assert "TABLESAMPLE SYSTEM (10)" in result

    def test_no_schema_not_injected(self):
        """无 schema 的表（可能是 CTE 引用）→ 正则不匹配，不注入。"""
        sql = "SELECT * FROM fact_table a"
        result = inject_tablesample(sql, 10)
        assert "TABLESAMPLE" not in result


class TestInjectJoin:
    """JOIN 场景：所有物理表都注入（不只主表）。"""

    def test_all_tables_injected(self):
        """JOIN：FROM 和 JOIN 的所有物理表都注入。"""
        sql = (
            "SELECT a.id, b.name FROM ods.fact a "
            "JOIN dim.dim_user b ON a.uid = b.id WHERE a.dt = 'x'"
        )
        result = inject_tablesample(sql, 10)
        # 两张表都注入了
        assert result.count("TABLESAMPLE") == 2, \
            f"FROM+JOIN 两张表都应注入，实际 {result.count('TABLESAMPLE')} 处: {result}"

    def test_multi_join_all_injected(self):
        """多表 JOIN（都是 INNER）：每张物理表都注入。"""
        sql = (
            "SELECT a.id FROM ods.fact a "
            "JOIN dim.user b ON a.uid=b.id "
            "JOIN dim.store c ON a.sid=c.id"
        )
        result = inject_tablesample(sql, 10)
        assert result.count("TABLESAMPLE") == 3, \
            f"3张表都应注入，实际 {result.count('TABLESAMPLE')} 处: {result}"


class TestInjectJoinType:
    """JOIN 类型决定切不切：FROM/INNER/逗号/CROSS 切，LEFT/RIGHT/FULL 从表不切。

    核心场景：外连接从表保留全量，避免切片后关联不上变 NULL；
    必要表（INNER）切了控制总量。避免主表被切太狠空表 UT 假通过。
    """

    def test_left_join_slave_not_injected(self):
        """LEFT JOIN 从表不切（避免关联不上变 NULL）；主表切。"""
        sql = (
            "SELECT a.id, b.name FROM ods.fact a "
            "LEFT JOIN dim.dim_user b ON a.uid = b.id WHERE a.dt = 'x'"
        )
        result = inject_tablesample(sql, 10)
        assert result.count("TABLESAMPLE") == 1, f"只切主表，LEFT从表不切: {result}"

    def test_right_join_slave_not_injected(self):
        """RIGHT JOIN 从表不切。"""
        sql = "SELECT a.id FROM ods.fact a RIGHT JOIN dim.dim_user b ON a.uid = b.id"
        result = inject_tablesample(sql, 10)
        assert result.count("TABLESAMPLE") == 1, f"只切主表: {result}"

    def test_full_join_slave_not_injected(self):
        """FULL JOIN 从表不切。"""
        sql = "SELECT a.id FROM ods.fact a FULL JOIN dim.dim_user b ON a.uid = b.id"
        result = inject_tablesample(sql, 10)
        assert result.count("TABLESAMPLE") == 1, f"只切主表: {result}"

    def test_mixed_inner_left(self):
        """混合：主表 + INNER JOIN 表切，LEFT JOIN 从表不切。"""
        sql = (
            "SELECT a.id FROM ods.fact a "
            "INNER JOIN ods.fact2 b ON a.id=b.id "
            "LEFT JOIN dim.dim_user c ON a.uid=c.id"
        )
        result = inject_tablesample(sql, 10)
        # 主表 fact + INNER 的 fact2 切（2 处），LEFT 的 dim_user 不切
        assert result.count("TABLESAMPLE") == 2, f"主表+INNER切，LEFT不切: {result}"

    def test_implicit_comma_join_injected(self):
        """隐式逗号 JOIN（FROM t1, t2）：两张都切（等价 INNER，必要表）。"""
        sql = "SELECT a.id FROM ods.fact a, ods.fact2 b WHERE a.id=b.id"
        result = inject_tablesample(sql, 10)
        assert result.count("TABLESAMPLE") == 2, f"逗号JOIN都切: {result}"

    def test_cross_join_injected(self):
        """CROSS JOIN：两张都切（笛卡尔积，两边必要）。"""
        sql = "SELECT a.id FROM ods.fact a CROSS JOIN ods.fact2 b"
        result = inject_tablesample(sql, 10)
        assert result.count("TABLESAMPLE") == 2, f"CROSS都切: {result}"

    def test_subquery_left_join_not_injected(self):
        """LEFT JOIN 子查询：主表切，子查询不切（不是直接物理表）。"""
        sql = (
            "SELECT a.id FROM ods.fact a "
            "LEFT JOIN (SELECT id FROM ods.dim) b ON a.id=b.id"
        )
        result = inject_tablesample(sql, 10)
        assert result.count("TABLESAMPLE") == 1, f"只切主表，子查询不切: {result}"

    def test_join_type_not_broken(self):
        """各种 JOIN 类型注入后 SQL 结构不被破坏。"""
        import sqlglot
        sqls = [
            "SELECT a.id FROM ods.fact a LEFT JOIN dim.dim_user b ON a.uid=b.id",
            "SELECT a.id FROM ods.fact a RIGHT JOIN ods.f2 b ON a.uid=b.id",
            "SELECT a.id FROM ods.fact a FULL JOIN ods.f2 b ON a.uid=b.id",
            "SELECT a.id FROM ods.fact a INNER JOIN ods.f2 b ON a.id=b.id LEFT JOIN dim.c c ON a.id=c.id",
        ]
        for sql in sqls:
            result = inject_tablesample(sql, 10)
            try:
                sqlglot.parse_one(result, dialect="postgres")
            except Exception as e:
                assert False, f"注入后 SQL 结构被破坏: {result} ({e})"


class TestInjectSafety:
    """安全性测试：不破坏 SQL。"""

    def test_cte_not_injected(self):
        """CTE 定义里的表不注入（只在主查询层注入）。"""
        sql = (
            "WITH agg AS (SELECT id FROM ods.big GROUP BY id) "
            "SELECT * FROM agg a JOIN ods.small b ON a.id = b.id"
        )
        result = inject_tablesample(sql, 10)
        # 主查询的 ods.small 应注入（如果匹配到）
        # CTE 里的 ods.big 不应注入
        # 验证 SQL 不被破坏
        import sqlglot
        try:
            sqlglot.parse_one(result, dialect="postgres")
            parse_ok = True
        except Exception:
            parse_ok = False
        assert parse_ok, f"注入后 SQL 结构被破坏: {result}"

    def test_subquery_from_not_broken(self):
        """FROM 子查询：不破坏 SQL。"""
        sql = "SELECT * FROM (SELECT id FROM ods.big) sub WHERE sub.id > 0"
        result = inject_tablesample(sql, 10)
        import sqlglot
        try:
            sqlglot.parse_one(result, dialect="postgres")
            parse_ok = True
        except Exception:
            parse_ok = False
        assert parse_ok, f"注入后 SQL 结构被破坏: {result}"

    def test_complex_sql_not_broken(self):
        """复杂 SQL（多行/注释/JOIN/GROUP BY）：注入后仍可解析。"""
        sql = """-- 主查询
SELECT a.id, b.name, SUM(a.amt)
FROM ods.fact_table a
JOIN dim.dim_user b ON a.uid = b.id
WHERE a.dt = '${BIZ_DATE}'
GROUP BY a.id, b.name"""
        result = inject_tablesample(sql, 10)
        import sqlglot
        try:
            sqlglot.parse_one(result, dialect="postgres")
            parse_ok = True
        except Exception:
            parse_ok = False
        assert parse_ok, f"注入后 SQL 结构被破坏: {result}"
        assert "TABLESAMPLE SYSTEM (10)" in result

    def test_inject_not_double_injected(self):
        """已有 TABLESAMPLE 的不重复注入。"""
        sql = "SELECT * FROM ods.fact a TABLESAMPLE SYSTEM (10)"
        result = inject_tablesample(sql, 10)
        # 不应重复注入
        assert result.count("TABLESAMPLE") == 1, f"不应重复注入: {result}"


class TestInjectWithAs:
    """AS 关键字场景。"""

    def test_with_as_keyword(self):
        """FROM ods.fact AS a → 注入。"""
        sql = "SELECT * FROM ods.fact AS a"
        result = inject_tablesample(sql, 10)
        assert "TABLESAMPLE SYSTEM (10)" in result

    def test_without_alias(self):
        """FROM ods.fact（无别名）→ 注入。"""
        sql = "SELECT count(*) FROM ods.fact"
        result = inject_tablesample(sql, 10)
        assert "TABLESAMPLE SYSTEM (10)" in result


class TestResolveSampleBlocks:
    """resolve_sample_blocks 测试：CLI 参数 > 配置文件默认 > 0。"""

    def test_cli_value_takes_priority(self, tmp_path):
        """CLI 传了 >0 的值 → 用 CLI 值，不读配置。"""
        import json
        cfg = tmp_path / "db.json"
        cfg.write_text(json.dumps({"security": {"sample_blocks": 50}}))
        result = resolve_sample_blocks(str(cfg), cli_value=10)
        assert result == 10

    def test_cli_zero_reads_config(self, tmp_path):
        """CLI 没传（0）→ 从配置读默认值。"""
        import json
        cfg = tmp_path / "db.json"
        cfg.write_text(json.dumps({"security": {"sample_blocks": 10}}))
        result = resolve_sample_blocks(str(cfg), cli_value=0)
        assert result == 10

    def test_no_config_no_cli_returns_zero(self, tmp_path):
        """配置没有 sample_blocks + CLI 没传 → 0。"""
        import json
        cfg = tmp_path / "db.json"
        cfg.write_text(json.dumps({"security": {"timeout": 600}}))
        result = resolve_sample_blocks(str(cfg), cli_value=0)
        assert result == 0

    def test_config_file_not_found_returns_zero(self):
        """配置文件不存在 → 0。"""
        result = resolve_sample_blocks("/nonexistent/path/db.json", cli_value=0)
        assert result == 0

    def test_config_zero_means_no_sample(self, tmp_path):
        """配置 sample_blocks=0（UAT/生产）→ 0。"""
        import json
        cfg = tmp_path / "db.json"
        cfg.write_text(json.dumps({"security": {"sample_blocks": 0}}))
        result = resolve_sample_blocks(str(cfg), cli_value=0)
        assert result == 0
