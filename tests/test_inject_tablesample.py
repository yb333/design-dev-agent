"""inject_tablesample 的测试。

核心验证：
1. 单表 SELECT：主表注入 TABLESAMPLE SYSTEM
2. JOIN：只注入主表（FROM 第一张），JOIN 的表不注入
3. CTE 引用：无 schema 的跳过（可能是 CTE，不误伤）
4. sample_blocks=0：不注入，返回原 SQL
5. 匹配失败：回退原 SQL，不破坏
6. 注入后 SQL 结构不变（只多了 TABLESAMPLE 子句）
"""

import sys
from pathlib import Path

_CODING_SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "dws-coding" / "scripts"
if str(_CODING_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CODING_SCRIPTS))

from run_ut import inject_tablesample


class TestInjectBasic:
    """基础注入测试。"""

    def test_zero_blocks_returns_original(self):
        """sample_blocks=0 → 不注入，返回原 SQL。"""
        sql = "SELECT * FROM ods.fact a WHERE a.dt = 'x'"
        assert inject_tablesample(sql, 0) == sql

    def test_negative_blocks_returns_original(self):
        """sample_blocks<0 → 不注入。"""
        sql = "SELECT * FROM ods.fact a"
        assert inject_tablesample(sql, -1) == sql

    def test_single_table_injected(self):
        """单表 SELECT：主表注入 TABLESAMPLE SYSTEM (10)。"""
        sql = "SELECT a.id, a.name FROM ods.fact_table a WHERE a.dt = 'x'"
        result = inject_tablesample(sql, 10)
        assert "TABLESAMPLE SYSTEM (10)" in result
        # 注入位置在别名后
        assert "ods.fact_table a TABLESAMPLE" in result or "ods.fact_table AS a TABLESAMPLE" in result

    def test_no_schema_not_injected(self):
        """无 schema 的表（可能是 CTE 引用）→ 不注入（保守策略）。"""
        sql = "SELECT * FROM fact_table a"
        result = inject_tablesample(sql, 10)
        assert "TABLESAMPLE" not in result
        assert result == sql  # 原样返回


class TestInjectJoin:
    """JOIN 场景：只注入主表。"""

    def test_join_only_main_table_injected(self):
        """JOIN：只给 FROM 第一张表注入，JOIN 的表不注入。"""
        sql = (
            "SELECT a.id, b.name FROM ods.fact a "
            "JOIN dim.dim_user b ON a.uid = b.id WHERE a.dt = 'x'"
        )
        result = inject_tablesample(sql, 10)
        # 主表 ods.fact 有 TABLESAMPLE
        assert "ods.fact a TABLESAMPLE SYSTEM (10)" in result or "ods.fact AS a TABLESAMPLE" in result
        # JOIN 的 dim.dim_user 没有 TABLESAMPLE
        assert "dim.dim_user b TABLESAMPLE" not in result
        assert "dim.dim_user AS b TABLESAMPLE" not in result

    def test_multi_join_only_first(self):
        """多表 JOIN：只有第一张注入。"""
        sql = (
            "SELECT a.id FROM ods.fact a "
            "JOIN dim.user b ON a.uid=b.id "
            "JOIN dim.store c ON a.sid=c.id"
        )
        result = inject_tablesample(sql, 10)
        assert "TABLESAMPLE" in result
        # 只出现一次（只有主表）
        assert result.count("TABLESAMPLE") == 1


class TestInjectSafety:
    """安全性测试：不破坏 SQL。"""

    def test_cte_not_injected(self):
        """CTE 引用（无 schema）→ 不注入。"""
        sql = (
            "WITH agg AS (SELECT id FROM ods.big GROUP BY id) "
            "SELECT * FROM agg a JOIN ods.small b ON a.id = b.id"
        )
        result = inject_tablesample(sql, 10)
        # 第一个 FROM 是 CTE 引用 agg（无 schema）→ 不注入
        # 第二个 JOIN 的 ods.small 不注入（只注主表，但主表是 CTE 跳过了）
        # 所以整条 SQL 无 TABLESAMPLE
        assert "TABLESAMPLE" not in result

    def test_subquery_from_not_broken(self):
        """FROM 子查询：不破坏 SQL（匹配不到物理表就回退）。"""
        sql = "SELECT * FROM (SELECT id FROM ods.big) sub WHERE sub.id > 0"
        result = inject_tablesample(sql, 10)
        # FROM ( 子查询，正则匹配的是 "FROM sub"？不—— FROM 后跟 ( 不是表名
        # 回退原 SQL 或只注入能匹配的部分，关键是 SQL 不被破坏
        # 验证：SQL 仍能被 sqlglot 解析（结构完整）
        import sqlglot
        try:
            sqlglot.parse_one(result, dialect="postgres")
            parse_ok = True
        except Exception:
            parse_ok = False
        assert parse_ok, f"注入后 SQL 结构被破坏: {result}"

    def test_complex_sql_not_broken(self):
        """复杂 SQL（多行/注释/CTE+JOIN）：注入后仍可解析。"""
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
        # 主表注入了
        assert "TABLESAMPLE SYSTEM (10)" in result

    def test_inject_only_adds_clause(self):
        """注入只多了 TABLESAMPLE 子句，SQL 其余部分不变。"""
        sql = "SELECT a.id FROM ods.fact a WHERE a.dt='x'"
        result = inject_tablesample(sql, 10)
        # 去掉 TABLESAMPLE 子句后应等于原 SQL
        import re
        stripped = re.sub(r"\s+TABLESAMPLE SYSTEM \(\d+\)", "", result)
        assert stripped == sql, f"注入改动了 SQL 其他部分: 原文={sql!r} 结果={result!r}"


class TestInjectWithAs:
    """AS 关键字场景。"""

    def test_with_as_keyword(self):
        """FROM ods.fact AS a → 别名带 AS。"""
        sql = "SELECT * FROM ods.fact AS a"
        result = inject_tablesample(sql, 10)
        assert "TABLESAMPLE SYSTEM (10)" in result
        # AS a 后面跟 TABLESAMPLE
        assert "AS a TABLESAMPLE" in result

    def test_without_alias(self):
        """FROM ods.fact（无别名）→ 表名后注入。"""
        sql = "SELECT count(*) FROM ods.fact"
        result = inject_tablesample(sql, 10)
        assert "TABLESAMPLE SYSTEM (10)" in result
        assert "ods.fact TABLESAMPLE" in result
