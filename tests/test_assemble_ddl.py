"""
assemble_ddl.py 的 generate_ddl 测试。

覆盖目标表后缀的 4 条路径（_i / _f / _d / tmp）+ 视图字段列表 +
回退脚本配套 + 审计字段进 DDL + 分布键。

测试数据用 conftest.make_ts_json 工厂构造，不依赖真实 ts.json 文件。
make_ts_json 默认把 rule.target_table 设成 f_table 名（无 schema 前缀），
generate_ddl 内部从 meta.target.f_table.schema 兜底 schema。
要触发 _i/_f/_d/tmp 的不同分支，传自定义 rules 指定 target_table 后缀。
"""

import pytest

from assemble_ddl import generate_ddl
from conftest import make_ts_json


# ============================================================
# 辅助：构造带指定 target_table 后缀的 rule
# ============================================================

def _rule(table, fields=None):
    """构造单规则，target_table 用传入的 table（决定后缀分支）。

    fields 默认 1 个业务字段 + 1 个审计字段，足够覆盖 CREATE TABLE 与视图。
    """
    if fields is None:
        fields = [
            {
                "target_field": "id",
                "field_type": "bigint",
                "field_comment": "ID",
                "transform_type": "direct",
                "source_fields": [],
                "design_logic": "直取",
            },
            {
                "target_field": "del_flag",
                "field_type": "NVARCHAR(1)",
                "field_comment": "删除标识",
                "transform_type": "assign",
                "source_fields": [],
                "design_logic": "固定赋值",
            },
        ]
    return {
        "rule_name": "测试规则",
        "scenario": "default",
        "exec_sequence": 1,
        "target_table": table,
        "is_view_step": False,
        "design_intent": "测试",
        "source_tables": [],
        "fields": fields,
        "field_count": len(fields),
    }


# ============================================================
# 1. 目标表后缀 → F表 / I视图 分支
# ============================================================

class TestTargetSuffixBranching:
    def test_i_target_creates_f_table_and_view(self):
        """_i 结尾目标表 → 先建 F表（_i→_f），再建 I视图"""
        ts = make_ts_json(
            table="dwb_test_i",
            rules={"R0001": _rule("dwb_test_i")},
        )
        ddls, rollbacks = generate_ddl(ts)

        # 应该有 create_table_xxx_f.sql 和 create_view_xxx_i.sql
        assert any("create_table_" in f and "_f" in f for f in ddls), \
            f"应有 _f 表 DDL，实际: {list(ddls.keys())}"
        assert any("create_view_" in f and "_i" in f for f in ddls), \
            f"应有 _i 视图 DDL，实际: {list(ddls.keys())}"
        # 不应直接对 _i 建 CREATE TABLE
        assert "create_table_dwb_test_i.sql" not in ddls

    def test_f_target_creates_f_table_and_paired_view(self):
        """_f 结尾目标表 → 建 F表 + 自动配套 I视图"""
        ts = make_ts_json(
            table="dwb_test_f",
            rules={"R0001": _rule("dwb_test_f")},
        )
        ddls, rollbacks = generate_ddl(ts)

        assert "create_table_dwb_test_f.sql" in ddls
        # 自动配套的 I视图
        assert "create_view_dwb_test_i.sql" in ddls, \
            f"_f 目标应自动配套 _i 视图，实际: {list(ddls.keys())}"

    def test_d_target_creates_table_only(self):
        """_d 结尾（明细层）→ 只建表，不建视图"""
        ts = make_ts_json(
            table="dim_test_d",
            rules={"R0001": _rule("dim_test_d")},
        )
        ddls, rollbacks = generate_ddl(ts)

        assert "create_table_dim_test_d.sql" in ddls
        # 明细层不配视图
        assert not any("view" in f for f in ddls), \
            f"_d 表不应有视图，实际: {list(ddls.keys())}"

    def test_tmp_table_creates_table_only(self):
        """中间表（tmp）→ 只建表"""
        ts = make_ts_json(
            table="tmp_order_agg",
            rules={"R0001": _rule("tmp_order_agg")},
        )
        ddls, rollbacks = generate_ddl(ts)

        assert "create_table_tmp_order_agg.sql" in ddls
        assert not any("view" in f for f in ddls), \
            f"中间表不应有视图，实际: {list(ddls.keys())}"


# ============================================================
# 2. I视图字段列表（不用 SELECT *）
# ============================================================

class TestViewFieldListing:
    def test_i_view_lists_fields_not_select_star(self):
        """I视图不用 SELECT *，要列出字段"""
        ts = make_ts_json(
            table="dwb_test_i",
            rules={"R0001": _rule("dwb_test_i")},
        )
        ddls, _ = generate_ddl(ts)
        view_content = ddls["create_view_dwb_test_i.sql"]

        assert "SELECT *" not in view_content, "I视图不应使用 SELECT *"
        # 业务字段和审计字段都应列出
        assert "id" in view_content
        assert "del_flag" in view_content
        assert "FROM" in view_content.upper()

    def test_f_paired_view_lists_fields(self):
        """_f 目标配套的 I视图同样要列字段"""
        ts = make_ts_json(
            table="dwb_test_f",
            rules={"R0001": _rule("dwb_test_f")},
        )
        ddls, _ = generate_ddl(ts)
        view_content = ddls["create_view_dwb_test_i.sql"]

        assert "SELECT *" not in view_content
        assert "id" in view_content


# ============================================================
# 3. 回退脚本配套
# ============================================================

class TestRollbackPaired:
    def test_every_ddl_has_matching_rollback(self):
        """每个 DDL 都有对应的 DROP 回退脚本"""
        ts = make_ts_json(
            table="dwb_test_i",
            rules={"R0001": _rule("dwb_test_i")},
        )
        ddls, rollbacks = generate_ddl(ts)

        # DDL 和 rollback 数量应一致
        assert len(ddls) == len(rollbacks), \
            f"DDL({len(ddls)}) 和 rollback({len(rollbacks)}) 数量不一致"

        # 每个 DDL 文件名都能找到对应 rollback（去掉 create_ / rollback_ 前缀后词干一致）
        def stem(name, prefix):
            return name.replace(prefix, "").replace(".sql", "")

        ddl_stems = {stem(f, "create_table_").replace("create_view_", "") for f in ddls}
        rb_stems = set()
        for f in rollbacks:
            for pfx in ("rollback_create_table_", "rollback_create_view_"):
                if f.startswith(pfx):
                    rb_stems.add(f[len(pfx):-4])
        assert ddl_stems == rb_stems, \
            f"DDL 与 rollback 词干不匹配: ddl={ddl_stems} rb={rb_stems}"

    def test_rollback_is_drop_statement(self):
        """回退脚本是 DROP 语句"""
        ts = make_ts_json(
            table="dwb_test_i",
            rules={"R0001": _rule("dwb_test_i")},
        )
        ddls, rollbacks = generate_ddl(ts)
        for name, content in rollbacks.items():
            assert "DROP" in content.upper(), \
                f"回退脚本 {name} 应含 DROP: {content}"

    def test_view_rollback_uses_drop_view(self):
        """视图回退用 DROP VIEW，表回退用 DROP TABLE"""
        ts = make_ts_json(
            table="dwb_test_i",
            rules={"R0001": _rule("dwb_test_i")},
        )
        ddls, rollbacks = generate_ddl(ts)

        view_rb = rollbacks["rollback_create_view_dwb_test_i.sql"]
        assert "DROP VIEW" in view_rb.upper()

        table_rb = rollbacks["rollback_create_table_dwb_test_f.sql"]
        assert "DROP TABLE" in table_rb.upper()


# ============================================================
# 4. 审计字段 + 分布键进 DDL
# ============================================================

class TestAuditAndDistribute:
    def test_audit_fields_in_create_table(self):
        """审计字段（del_flag/crt_cycle_id 等）应在 CREATE TABLE 里"""
        ts = make_ts_json(
            table="dwb_test_i",
            rules={"R0001": _rule("dwb_test_i")},
        )
        ddls, _ = generate_ddl(ts)
        table_content = ddls["create_table_dwb_test_f.sql"]

        # design.audit_fields 有 4 个标准字段，都应在 CREATE TABLE 的列定义里
        assert "del_flag" in table_content
        assert "crt_cycle_id" in table_content
        assert "last_upd_cycle_id" in table_content
        assert "dw_last_update_date" in table_content
        # 必须是 CREATE TABLE（不是视图）
        assert "CREATE TABLE" in table_content.upper()

    def test_distribute_by_present(self):
        """DDL 应含 DISTRIBUTE BY（分布键）"""
        ts = make_ts_json(
            table="dwb_test_i",
            rules={"R0001": _rule("dwb_test_i")},
        )
        ddls, _ = generate_ddl(ts)
        table_content = ddls["create_table_dwb_test_f.sql"]

        assert "DISTRIBUTE BY" in table_content, \
            f"CREATE TABLE 应含 DISTRIBUTE BY: {table_content}"
        # make_ts_json 默认分布键是 id
        assert "id" in table_content

    def test_distribute_respects_custom_key(self):
        """自定义 distribution_key 应反映到 DDL"""
        ts = make_ts_json(
            table="dwb_test_i",
            rules={"R0001": _rule("dwb_test_i")},
        )
        # 覆盖分布键为复合键
        ts["design"]["distribution_key"] = ["contract_id", "pu_id"]
        ddls, _ = generate_ddl(ts)
        table_content = ddls["create_table_dwb_test_f.sql"]

        assert "DISTRIBUTE BY HASH(contract_id, pu_id)" in table_content


# ============================================================
# 5. I 视图按 meta.target.i_view（不加戏）
# ============================================================
class TestIViewByMeta:
    """I 视图建不建，由 meta.target.i_view 决定（assemble_ddl 不自动配套）。"""

    def test_i_view_empty_no_view(self):
        """meta.target.i_view 为空 → 不建视图（即使目标是 _f 表）"""
        ts = make_ts_json(table="dwb_test_f", rules={"R0001": _rule("dwb_test_f")})
        # 清空 i_view
        ts["meta"]["target"]["i_view"] = {}
        ddls, _ = generate_ddl(ts)
        assert "create_table_dwb_test_f.sql" in ddls
        assert not any("view" in f for f in ddls), \
            f"i_view 为空不该建视图: {list(ddls.keys())}"

    def test_i_view_present_builds_view(self):
        """meta.target.i_view 非空 + 目标是 _f 表 → 建视图"""
        ts = make_ts_json(table="dwb_test_f", rules={"R0001": _rule("dwb_test_f")})
        # i_view 非空（make_ts_json 默认推导了）
        ddls, _ = generate_ddl(ts)
        assert "create_table_dwb_test_f.sql" in ddls
        assert "create_view_dwb_test_i.sql" in ddls, \
            f"i_view 非空 + F 表应建视图: {list(ddls.keys())}"

    def test_intermediate_table_no_view_even_if_i_view_present(self):
        """中间表即使 meta.target.i_view 非空，也不建视图（不是最终目标 F 表）"""
        ts = make_ts_json(table="dwb_test_f", rules={
            "R0001": _rule("tmp_order_agg"),  # 中间表
            "R0002": _rule("dwb_test_f"),     # 目标 F 表
        })
        ddls, _ = generate_ddl(ts)
        # 中间表只建表
        assert "create_table_tmp_order_agg.sql" in ddls
        assert not any("tmp_order_agg" in f and "view" in f for f in ddls), \
            f"中间表不该建视图: {list(ddls.keys())}"
        # 目标 F 表建表 + 视图
        assert "create_table_dwb_test_f.sql" in ddls
        assert "create_view_dwb_test_i.sql" in ddls
