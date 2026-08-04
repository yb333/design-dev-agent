"""数据流图渲染测试。

覆盖：
- is_dim_table 维表识别（表名/schema 两条规则）
- render_data_flow_mermaid 各场景（单规则/多规则/维表标注/视图/多写同表/空）
"""
import pytest

# conftest 已把 design references 加入 sys.path
from assemble_ts import is_dim_table, render_data_flow_mermaid, _sanitize_node_id


# ============================================================
# 维表识别
# ============================================================

class TestIsDimTable:
    """维表识别：表名含 dim OR schema ∈ {dim, dwrdim, dwrdim_dw1}"""

    def test_by_table_name_dim_prefix(self):
        """表名以 dim_ 开头 → 维表"""
        assert is_dim_table("dim", "dim_product_f") is True
        assert is_dim_table("dim", "dim_user_f") is True

    def test_by_table_name_dim_anywhere(self):
        """表名任意位置含 dim → 维表"""
        assert is_dim_table("xx", "sys_dim_config") is True

    def test_by_schema_dim(self):
        """schema=dim → 维表"""
        assert is_dim_table("dim", "product_f") is True

    def test_by_schema_dwrdim(self):
        """schema=dwrdim → 维表"""
        assert is_dim_table("dwrdim", "cust_d") is True

    def test_by_schema_dwrdim_dw1(self):
        """schema=dwrdim_dw1 → 维表"""
        assert is_dim_table("dwrdim_dw1", "product_d") is True

    def test_non_dim_fact_table(self):
        """事实表（dwd_ 开头，非 dim schema）→ 非维表"""
        assert is_dim_table("sdord", "dwd_order_detail_f") is False
        assert is_dim_table("sdinv", "dwd_inventory_f") is False

    def test_non_dim_ods_table(self):
        """ODS 表 → 非维表"""
        assert is_dim_table("ods", "ods_trade_order_di") is False

    def test_case_insensitive(self):
        """大小写不敏感"""
        assert is_dim_table("DIM", "DIM_PRODUCT_F") is True
        assert is_dim_table("Dim", "Product_F") is True

    def test_empty_inputs(self):
        """空输入不崩"""
        assert is_dim_table("", "") is False
        assert is_dim_table(None, None) is False


# ============================================================
# render_data_flow_mermaid
# ============================================================

class TestRenderDataFlowMermaid:
    """数据流图 mermaid 渲染"""

    def test_no_rules_returns_empty(self):
        """无规则 → 空串"""
        ts = {"rules": {}, "data_flow": {}}
        assert render_data_flow_mermaid(ts) == ""

    def test_single_rule_basic(self):
        """单规则单源表：源表→步骤→目标表"""
        ts = {
            "rules": {
                "R0001": {
                    "rule_name": "订单汇总",
                    "target_table": "dwb_trade_order_d",
                    "exec_sequence": 1,
                    "is_view_step": False,
                    "source_tables": [
                        {"schema": "ods", "table": "ods_trade_order_di", "alias": "a"},
                    ],
                }
            },
            "data_flow": {"dependencies": [], "schedule_groups": [
                {"sequence": 1, "rules": ["R0001"]}
            ]},
        }
        result = render_data_flow_mermaid(ts)
        assert "```mermaid" in result
        assert "flowchart TD" in result
        # 步骤节点含规则名
        assert "R0001" in result
        assert "订单汇总" in result
        # 源表画了节点（非维表）
        assert "ods_trade_order_di" in result
        # 目标表画了节点
        assert "dwb_trade_order_d" in result
        # 有边
        assert "-->" in result
        # 有 classDef
        assert "classDef" in result

    def test_multi_rule_with_tmp(self):
        """多规则带中间表：按 schedule_groups 分层"""
        ts = {
            "rules": {
                "R0001": {
                    "rule_name": "销售汇总",
                    "target_table": "dwb_sales_tmp1",
                    "exec_sequence": 1,
                    "is_view_step": False,
                    "source_tables": [{"schema": "sdord", "table": "dwd_order_f", "alias": "a"}],
                },
                "R0002": {
                    "rule_name": "装配宽表",
                    "target_table": "dwb_product_center_f",
                    "exec_sequence": 2,
                    "is_view_step": False,
                    "source_tables": [{"schema": "dim", "table": "dim_product_f", "alias": "b"}],
                },
            },
            "data_flow": {
                "dependencies": [{"from": "R0001", "to": "R0002", "intermediate_table": "dwb_sales_tmp1"}],
                "schedule_groups": [
                    {"sequence": 1, "rules": ["R0001"]},
                    {"sequence": 2, "rules": ["R0002"]},
                ],
            },
        }
        result = render_data_flow_mermaid(ts)
        # 中间表节点存在
        assert "dwb_sales_tmp1" in result
        # 中间表标 intermediate 样式
        assert "intermediate" in result
        # 中间表→R0002 步骤的边（跨步骤依赖）
        assert "dwb_sales_tmp1" in result

    def test_dim_table_as_annotation(self):
        """维表不画节点，降级为步骤标注"""
        ts = {
            "rules": {
                "R0001": {
                    "rule_name": "装配",
                    "target_table": "dwb_xxx_f",
                    "exec_sequence": 1,
                    "is_view_step": False,
                    "source_tables": [
                        {"schema": "dim", "table": "dim_product_f", "alias": "a"},
                        {"schema": "dim", "table": "dim_brand_f", "alias": "b"},
                        {"schema": "sdord", "table": "dwd_order_f", "alias": "c"},
                    ],
                }
            },
            "data_flow": {"dependencies": [], "schedule_groups": [
                {"sequence": 1, "rules": ["R0001"]}
            ]},
        }
        result = render_data_flow_mermaid(ts)
        # 维表出现在标注里
        assert "关联维表" in result
        assert "dim_product_f" in result
        assert "dim_brand_f" in result
        # 维表没有独立节点声明（没有 src_dim_product_f 这种）
        # 非维表画了节点
        assert "dwd_order_f" in result

    def test_view_step_dashed_edge(self):
        """视图规则：is_view_step → F表 -.-> 视图（虚线边）"""
        ts = {
            "rules": {
                "R0001": {
                    "rule_name": "目标表",
                    "target_table": "dwb_xxx_f",
                    "exec_sequence": 1,
                    "is_view_step": False,
                    "source_tables": [{"schema": "ods", "table": "ods_xxx_di", "alias": "a"}],
                },
                "R0002": {
                    "rule_name": "视图",
                    "target_table": "dwb_xxx_i",
                    "exec_sequence": 2,
                    "is_view_step": True,
                    "source_tables": [],
                },
            },
            "data_flow": {
                "dependencies": [],
                "schedule_groups": [
                    {"sequence": 1, "rules": ["R0001"]},
                    {"sequence": 2, "rules": ["R0002"]},
                ],
            },
        }
        result = render_data_flow_mermaid(ts)
        # 视图节点存在，用 view 样式
        assert "dwb_xxx_i" in result
        assert "view" in result
        # 虚线边
        assert "-.->" in result

    def test_multi_write_same_table(self):
        """两个步骤写同一张表：两条边指向同一产出表节点"""
        ts = {
            "rules": {
                "R0001": {
                    "rule_name": "步骤1",
                    "target_table": "dwb_shared_f",
                    "exec_sequence": 1,
                    "is_view_step": False,
                    "source_tables": [{"schema": "ods", "table": "ods_a_f", "alias": "a"}],
                },
                "R0002": {
                    "rule_name": "步骤2",
                    "target_table": "dwb_shared_f",
                    "exec_sequence": 1,
                    "is_view_step": False,
                    "source_tables": [{"schema": "ods", "table": "ods_b_f", "alias": "b"}],
                },
            },
            "data_flow": {"dependencies": [], "schedule_groups": [
                {"sequence": 1, "rules": ["R0001", "R0002"]}
            ]},
        }
        result = render_data_flow_mermaid(ts)
        # 产出表节点出现（不重复声明）
        # count occurrences of target table node declaration
        assert result.count('tbl_dwb_shared_f["dwb_shared_f"]') == 1

    def test_no_schedule_groups_fallback(self):
        """没有 schedule_groups → 按 exec_sequence 兜底分层"""
        ts = {
            "rules": {
                "R0001": {
                    "rule_name": "步骤1",
                    "target_table": "tmp1",
                    "exec_sequence": 1,
                    "is_view_step": False,
                    "source_tables": [{"schema": "ods", "table": "ods_a", "alias": "a"}],
                },
            },
            "data_flow": {},
        }
        result = render_data_flow_mermaid(ts)
        # 兜底也能画出图
        assert "R0001" in result
        assert "tmp1" in result

    def test_mermaid_code_fence(self):
        """生成的文本用 ```mermaid 围栏包裹"""
        ts = {
            "rules": {"R0001": {"rule_name": "x", "target_table": "t", "exec_sequence": 1,
                                "is_view_step": False, "source_tables": []}},
            "data_flow": {},
        }
        result = render_data_flow_mermaid(ts)
        assert result.startswith("```mermaid")
        assert result.rstrip().endswith("```")

    def test_class_defs_present(self):
        """classDef 声明齐全"""
        ts = {
            "rules": {"R0001": {"rule_name": "x", "target_table": "t", "exec_sequence": 1,
                                "is_view_step": False,
                                "source_tables": [{"schema": "ods", "table": "s", "alias": "a"}]}},
            "data_flow": {"schedule_groups": [{"sequence": 1, "rules": ["R0001"]}]},
        }
        result = render_data_flow_mermaid(ts)
        assert "classDef source" in result
        assert "classDef step" in result
        assert "classDef intermediate" in result
        assert "classDef target" in result
        assert "classDef view" in result

    def test_dim_annotation_truncation(self):
        """维表超过4个 → 标注显示前4个 + '等N张'"""
        ts = {
            "rules": {
                "R0001": {
                    "rule_name": "x",
                    "target_table": "t_f",
                    "exec_sequence": 1,
                    "is_view_step": False,
                    "source_tables": [
                        {"schema": "dim", "table": "dim_a_f", "alias": "a"},
                        {"schema": "dim", "table": "dim_b_f", "alias": "b"},
                        {"schema": "dim", "table": "dim_c_f", "alias": "c"},
                        {"schema": "dim", "table": "dim_d_f", "alias": "d"},
                        {"schema": "dim", "table": "dim_e_f", "alias": "e"},
                    ],
                }
            },
            "data_flow": {"schedule_groups": [{"sequence": 1, "rules": ["R0001"]}]},
        }
        result = render_data_flow_mermaid(ts)
        assert "等5张" in result


# ============================================================
# _sanitize_node_id
# ============================================================

class TestSanitizeNodeId:
    """节点 ID 清理（mermaid 节点 ID 只能字母数字下划线）"""

    def test_dot_replaced(self):
        """点号替换成下划线"""
        assert _sanitize_node_id("dim.product_f") == "dim_product_f"

    def test_dash_replaced(self):
        """短横线替换成下划线"""
        assert _sanitize_node_id("dwb-order-d") == "dwb_order_d"

    def test_clean_id_unchanged(self):
        """合法 ID 不变"""
        assert _sanitize_node_id("R0001") == "R0001"

    def test_empty(self):
        """空串不崩"""
        assert _sanitize_node_id("") == ""
        assert _sanitize_node_id(None) == ""
