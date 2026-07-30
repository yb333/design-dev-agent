"""excel_parser 单元测试"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from excel_parser import (
    AttributeMapping,
    DesignConfig,
    EntityMapping,
    ExcelMappingParser,
    ExecutionPlatformConfig,
    MappingDocument,
    MappingExporter,
    SchedulingConfig,
)


# ── Fixture Helpers ──────────────────────────────────────


def _create_excel(tmp_path, sheets: dict) -> Path:
    """Create a .xlsx file with given sheets."""
    filepath = tmp_path / "test_mapping.xlsx"
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return filepath


def _make_entity_df(**overrides) -> pd.DataFrame:
    """Create a standard entity mapping DataFrame."""
    return pd.DataFrame(
        [
            {
                "源表schema": "ods",
                "源表物理表名": "ods_order_f",
                "源表中文名": "订单表",
                "目标表schema": "slprd",
                "目标表物理表名": "dwb_order_center_f",
                "目标表中文名": "订单中心宽表",
                "关联&限定条件": "left join on o.id=oc.id",
                "备注": "",
                "调度任务名称": "",
                "执行路径": "",
                "依赖参数": "",
                "源表别名": "",
                **overrides,
            }
        ]
    )


def _make_attribute_df(**overrides) -> pd.DataFrame:
    """Create a standard attribute mapping DataFrame."""
    rows = [
        {
            "源表schema": "ods",
            "源表物理表名": "ods_order_f",
            "源字段名": "order_id",
            "源字段类型": "bigint",
            "映射规则": "直取",
            "映射表达式": "",
            "目标字段名": "order_id",
            "目标字段中文名": "订单ID",
            "目标字段类型": "bigint",
            "源表别名": "",
        },
        {
            "源表schema": "ods",
            "源表物理表名": "ods_order_f",
            "源字段名": "amount",
            "源字段类型": "decimal(18,2)",
            "映射规则": "直取",
            "映射表达式": "",
            "目标字段名": "order_amount",
            "目标字段中文名": "订单金额",
            "目标字段类型": "decimal(18,2)",
            "源表别名": "",
        },
    ]
    return pd.DataFrame(rows)


def _make_schedule_df() -> pd.DataFrame:
    """Create a scheduling config DataFrame."""
    return pd.DataFrame(
        {
            "配置项": ["项目名称", "任务组名称", "调度周期", "责任人"],
            "值": ["ETL项目", "订单任务组", "日", "张三"],
        }
    )


def _make_design_df(wrap_view: str = "否") -> pd.DataFrame:
    """Create a design config DataFrame."""
    return pd.DataFrame(
        {
            "配置项": ["封装视图"],
            "值": [wrap_view],
        }
    )


# ── TestDataclasses ──────────────────────────────────────


class TestDataclasses:

    def test_EntityMapping默认值(self):
        m = EntityMapping(
            source_schema="ods",
            source_table="t1",
            source_table_cn="表1",
            target_schema="slprd",
            target_table_cn="目标表",
            target_table="tgt1",
            join_condition="",
            remark="",
        )
        assert m.schedule_task == ""
        assert m.exec_path == ""
        assert m.dep_job_params == ""
        assert m.source_alias == ""
        assert m.scene_group == ""

    def test_AttributeMapping默认值(self):
        m = AttributeMapping(
            source_schema="ods",
            source_table="t1",
            source_column="id",
            source_type="bigint",
            mapping_rule="直取",
            mapping_expression="",
            target_column="id",
            target_column_cn="ID",
            target_type="bigint",
        )
        assert m.source_alias == ""
        assert m.scene_group == ""

    def test_MappingDocument默认值(self):
        doc = MappingDocument(
            target_schema="slprd",
            target_table="tgt",
            target_table_cn="目标",
            source_tables=[],
            field_mappings=[],
            parse_time="2026-01-01 00:00:00",
        )
        assert doc.design_pattern == "single_source"
        assert doc.scene_count == 1
        assert doc.field_statistics is None
        assert doc.scheduling_config is None

    def test_SchedulingConfig默认值(self):
        config = SchedulingConfig()
        assert config.project_name == ""
        assert config.task_group == ""
        assert config.schedule_cycle == ""
        assert config.owner == ""

    def test_DesignConfig默认值(self):
        config = DesignConfig()
        assert config.wrap_view is False


# ── TestSafeStr ──────────────────────────────────────────


class TestSafeStr:

    def test_普通字符串(self):
        parser = ExcelMappingParser("")
        assert parser._safe_str("hello") == "hello"

    def test_NaN值(self):
        parser = ExcelMappingParser("")
        assert parser._safe_str(pd.NA) == ""

    def test_None值(self):
        parser = ExcelMappingParser("")
        assert parser._safe_str(None) == ""

    def test_带空格字符串(self):
        parser = ExcelMappingParser("")
        assert parser._safe_str("  hello  ") == "hello"

    def test_空字符串(self):
        parser = ExcelMappingParser("")
        assert parser._safe_str("") == ""


# ── TestDetectDesignPattern ──────────────────────────────


class TestDetectDesignPattern:

    def test_单场景(self):
        parser = ExcelMappingParser("")
        entities = [
            EntityMapping(
                source_schema="ods",
                source_table="t1",
                source_table_cn="表1",
                target_schema="slprd",
                target_table_cn="目标",
                target_table="tgt",
                join_condition="",
                remark="",
            )
        ]
        result = parser._detect_design_pattern(entities)
        assert result == ("single_source", 1)

    def test_多场景UNION(self):
        parser = ExcelMappingParser("")
        entities = [
            EntityMapping(
                source_schema="ods",
                source_table="t1",
                source_table_cn="表1",
                target_schema="slprd",
                target_table_cn="目标",
                target_table="tgt",
                join_condition="",
                remark="场景1xxx",
            ),
            EntityMapping(
                source_schema="ods",
                source_table="t2",
                source_table_cn="表2",
                target_schema="slprd",
                target_table_cn="目标",
                target_table="tgt",
                join_condition="",
                remark="场景2yyy",
            ),
        ]
        result = parser._detect_design_pattern(entities)
        assert result == ("multi_scene_union", 2)

    def test_场景编号混合中英文(self):
        parser = ExcelMappingParser("")
        entities = [
            EntityMapping(
                source_schema="ods",
                source_table="t1",
                source_table_cn="表1",
                target_schema="slprd",
                target_table_cn="目标",
                target_table="tgt",
                join_condition="",
                remark="场景1",
            ),
            EntityMapping(
                source_schema="ods",
                source_table="t2",
                source_table_cn="表2",
                target_schema="slprd",
                target_table_cn="目标",
                target_table="tgt",
                join_condition="",
                remark="SCENE2",
            ),
        ]
        result = parser._detect_design_pattern(entities)
        assert result == ("multi_scene_union", 2)

    def test_空列表(self):
        parser = ExcelMappingParser("")
        result = parser._detect_design_pattern([])
        assert result == ("single_source", 1)


# ── TestCalculateFieldStatistics ─────────────────────────


class TestCalculateFieldStatistics:

    def test_正常统计(self):
        parser = ExcelMappingParser("")
        fields = [
            AttributeMapping("", "", "", "", "直取", "", "f1", "", "", "", ""),
            AttributeMapping("", "", "", "", "直取", "", "f2", "", "", "", ""),
            AttributeMapping("", "", "", "", "直取", "", "f3", "", "", "", ""),
            AttributeMapping("", "", "", "", "加工", "expr1", "f4", "", "", "", ""),
            AttributeMapping("", "", "", "", "加工", "expr2", "f5", "", "", "", ""),
        ]
        stats = parser._calculate_field_statistics(fields)
        assert stats["total_records"] == 5
        assert stats["unique_fields"] == 5
        assert stats["direct_mapping"] == 3
        assert stats["processed_mapping"] == 2

    def test_空列表(self):
        parser = ExcelMappingParser("")
        stats = parser._calculate_field_statistics([])
        assert stats["total_records"] == 0
        assert stats["unique_fields"] == 0
        assert stats["direct_mapping"] == 0
        assert stats["processed_mapping"] == 0

    def test_去重字段数(self):
        parser = ExcelMappingParser("")
        fields = [
            AttributeMapping("", "", "", "", "直取", "", "f1", "", "", "", ""),
            AttributeMapping("", "", "", "", "加工", "", "f1", "", "", "", ""),
            AttributeMapping("", "", "", "", "直取", "", "f2", "", "", "", ""),
        ]
        stats = parser._calculate_field_statistics(fields)
        assert stats["total_records"] == 3
        assert stats["unique_fields"] == 2


# ── TestInferSourceTableFromExpression ───────────────────


class TestInferSourceTableFromExpression:

    def test_从表按模式(self):
        parser = ExcelMappingParser("")
        result = parser._infer_source_table_from_expression(
            "从 dwd_order_detail_f 按 order_id 汇总", ""
        )
        assert result is not None
        assert result["table"] == "dwd_order_detail_f"
        assert result["schema"] == ""

    def test_带schema的表(self):
        parser = ExcelMappingParser("")
        result = parser._infer_source_table_from_expression(
            "从 dwd.dim_user 按 user_id 统计", ""
        )
        assert result is not None
        assert result["schema"] == "dwd"
        assert result["table"] == "dim_user"

    def test_FROM子句(self):
        parser = ExcelMappingParser("")
        result = parser._infer_source_table_from_expression(
            "FROM dim_product_f WHERE active=1", ""
        )
        assert result is not None
        assert result["table"] == "dim_product_f"

    def test_无匹配返回None(self):
        parser = ExcelMappingParser("")
        result = parser._infer_source_table_from_expression("some random text", "")
        assert result is None

    def test_join子句(self):
        parser = ExcelMappingParser("")
        result = parser._infer_source_table_from_expression(
            "join dwd_order_detail_f on d.id = o.id", ""
        )
        assert result is not None
        assert result["table"] == "dwd_order_detail_f"


# ── TestNormalizeColumns ─────────────────────────────────


class TestNormalizeColumns:

    def test_精确匹配列名(self):
        parser = ExcelMappingParser("")
        df = pd.DataFrame({"源表schema": ["ods"], "源表物理表名": ["t1"]})
        result = parser._normalize_columns(df, parser.ENTITY_COLUMN_MAP)
        assert "source_schema" in result.columns
        assert "source_table" in result.columns

    def test_子串匹配列名(self):
        parser = ExcelMappingParser("")
        # '源表物理表名(长)' contains '源表物理表名' as substring
        df = pd.DataFrame(
            {"源表物理表名(长)": ["t1"], "源表schema": ["ods"]}
        )
        result = parser._normalize_columns(df, parser.ENTITY_COLUMN_MAP)
        assert "source_table" in result.columns

    def test_无匹配列名不修改(self):
        parser = ExcelMappingParser("")
        df = pd.DataFrame({"unknown_col": ["val1"], "other_col": ["val2"]})
        result = parser._normalize_columns(df, parser.ENTITY_COLUMN_MAP)
        assert "unknown_col" in result.columns
        assert "other_col" in result.columns


# ── TestLoad ─────────────────────────────────────────────


class TestExcelMappingParserLoad:

    def test_加载标准Excel(self, tmp_path):
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": _make_entity_df(),
                "属性级mapping": _make_attribute_df(),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        assert parser.load() is True

    def test_缺少核心Sheet(self, tmp_path):
        filepath = _create_excel(tmp_path, {"调度配置": _make_schedule_df()})
        parser = ExcelMappingParser(str(filepath))
        assert parser.load() is False

    def test_非Excel文件(self, tmp_path):
        filepath = tmp_path / "test.txt"
        filepath.write_text("not an excel", encoding="utf-8")
        parser = ExcelMappingParser(str(filepath))
        assert parser.load() is False

    def test_未识别Sheet诊断(self, tmp_path):
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": _make_entity_df(),
                "一些奇怪的Sheet": pd.DataFrame({"col": [1]}),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        types = [d["type"] for d in parser.diagnostics]
        assert "sheet_unrecognized" in types


# ── TestParseEntityMapping ───────────────────────────────


class TestParseEntityMapping:

    def test_解析实体级映射(self, tmp_path):
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": _make_entity_df(),
                "属性级mapping": _make_attribute_df(),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        entities = parser.parse_entity_mapping()
        assert len(entities) == 1
        assert entities[0].source_schema == "ods"
        assert entities[0].source_table == "ods_order_f"
        assert entities[0].target_table == "dwb_order_center_f"

    def test_空行跳过(self, tmp_path):
        df = pd.DataFrame(
            [
                {
                    "源表schema": "ods",
                    "源表物理表名": "ods_order_f",
                    "源表中文名": "订单表",
                    "目标表schema": "slprd",
                    "目标表物理表名": "dwb_order_center_f",
                    "目标表中文名": "订单中心宽表",
                    "关联&限定条件": "",
                    "备注": "",
                    "调度任务名称": "",
                    "执行路径": "",
                    "依赖参数": "",
                    "源表别名": "",
                },
                {
                    "源表schema": None,
                    "源表物理表名": None,
                    "源表中文名": None,
                    "目标表schema": None,
                    "目标表物理表名": None,
                    "目标表中文名": None,
                    "关联&限定条件": None,
                    "备注": None,
                    "调度任务名称": None,
                    "执行路径": None,
                    "依赖参数": None,
                    "源表别名": None,
                },
            ]
        )
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": df,
                "属性级mapping": _make_attribute_df(),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        entities = parser.parse_entity_mapping()
        # Empty rows (source_table="" and target_table="") should be skipped
        assert len(entities) == 1

    def test_空Sheet返回空列表(self):
        parser = ExcelMappingParser("")
        # entity_df is None by default
        entities = parser.parse_entity_mapping()
        assert entities == []


# ── TestParseAttributeMapping ────────────────────────────


class TestParseAttributeMapping:

    def test_解析属性级映射(self, tmp_path):
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": _make_entity_df(),
                "属性级mapping": _make_attribute_df(),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        attrs = parser.parse_attribute_mapping()
        assert len(attrs) == 2
        assert attrs[0].target_column == "order_id"
        assert attrs[0].mapping_rule == "直取"
        assert attrs[1].target_column == "order_amount"

    def test_加工字段自动推断表(self, tmp_path):
        attr_df = pd.DataFrame(
            [
                {
                    "源表schema": "",
                    "源表物理表名": "",
                    "源字段名": "",
                    "源字段类型": "",
                    "映射规则": "加工",
                    "映射表达式": "从 dwd_order_detail_f 按 order_id 汇总 amount",
                    "目标字段名": "total_amount",
                    "目标字段中文名": "总金额",
                    "目标字段类型": "decimal(18,2)",
                    "源表别名": "",
                }
            ]
        )
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": _make_entity_df(),
                "属性级mapping": attr_df,
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        attrs = parser.parse_attribute_mapping()
        assert len(attrs) == 1
        assert attrs[0].source_table == "dwd_order_detail_f"
        assert attrs[0].mapping_rule == "加工"

    def test_审计字段自动追加(self, tmp_path):
        """parse() result includes 4 audit fields when not present in mapping."""
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": _make_entity_df(),
                "属性级mapping": _make_attribute_df(),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        doc = parser.parse()
        audit_cols = {"del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"}
        actual_cols = {f.target_column for f in doc.field_mappings}
        assert audit_cols.issubset(actual_cols)


# ── TestParseSchedulingConfig ────────────────────────────


class TestParseSchedulingConfig:

    def test_解析调度配置(self, tmp_path):
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": _make_entity_df(),
                "属性级mapping": _make_attribute_df(),
                "调度配置": _make_schedule_df(),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        config = parser.parse_scheduling_config()
        assert config is not None
        assert config.project_name == "ETL项目"
        assert config.task_group == "订单任务组"
        assert config.schedule_cycle == "日"
        assert config.owner == "张三"

    def test_无调度Sheet返回None(self):
        parser = ExcelMappingParser("")
        # schedule_config_df is None by default
        config = parser.parse_scheduling_config()
        assert config is None


# ── TestParseDesignConfig ────────────────────────────────


class TestParseDesignConfig:

    def test_封装视图是(self, tmp_path):
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": _make_entity_df(),
                "属性级mapping": _make_attribute_df(),
                "设计配置": _make_design_df(wrap_view="是"),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        config = parser.parse_design_config()
        assert config is not None
        assert config.wrap_view is True

    def test_封装视图否(self, tmp_path):
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": _make_entity_df(),
                "属性级mapping": _make_attribute_df(),
                "设计配置": _make_design_df(wrap_view="否"),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        config = parser.parse_design_config()
        assert config is not None
        assert config.wrap_view is False


# ── TestMappingExporter ──────────────────────────────────


class TestMappingExporter:

    def _make_doc(self) -> MappingDocument:
        entity = EntityMapping(
            source_schema="ods",
            source_table="ods_order_f",
            source_table_cn="订单表",
            target_schema="slprd",
            target_table_cn="订单中心宽表",
            target_table="dwb_order_center_f",
            join_condition="left join on o.id=oc.id",
            remark="",
        )
        attrs = [
            AttributeMapping(
                source_schema="ods",
                source_table="ods_order_f",
                source_column="order_id",
                source_type="bigint",
                mapping_rule="直取",
                mapping_expression="",
                target_column="order_id",
                target_column_cn="订单ID",
                target_type="bigint",
            )
        ]
        return MappingDocument(
            target_schema="slprd",
            target_table="dwb_order_center_f",
            target_table_cn="订单中心宽表",
            source_tables=[entity],
            field_mappings=attrs,
            parse_time="2026-04-03 12:00:00",
            design_pattern="single_source",
            scene_count=1,
            field_statistics={"total_records": 1, "unique_fields": 1, "direct_mapping": 1, "processed_mapping": 0},
        )

    def test_to_json(self, tmp_path):
        doc = self._make_doc()
        json_path = tmp_path / "output.json"
        MappingExporter.to_json(doc, str(json_path))
        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["target_table"] == "dwb_order_center_f"
        assert len(data["source_tables"]) == 1
        assert len(data["field_mappings"]) == 1
        assert data["design_pattern"] == "single_source"

    def test_to_markdown(self, tmp_path):
        doc = self._make_doc()
        md_path = tmp_path / "output.md"
        MappingExporter.to_markdown(doc, str(md_path))
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "订单中心宽表" in content
        assert "实体级映射" in content
        assert "属性级映射" in content
        assert "统计信息" in content

    def test_to_summary(self):
        doc = self._make_doc()
        summary = MappingExporter.to_summary(doc)
        assert "dwb_order_center_f" in summary
        assert "订单中心宽表" in summary
        assert "源表数量" in summary
        assert "字段数量" in summary


# ── TestSafeStrSeriesDefense ──────────────────────────────


class TestSafeStrSeriesDefense:

    def test_Series输入取第一个非空值(self):
        parser = ExcelMappingParser("")
        s = pd.Series(["val1", "val2"])
        assert parser._safe_str(s) == "val1"

    def test_Series全NaN返回空字符串(self):
        parser = ExcelMappingParser("")
        s = pd.Series([pd.NA, np.nan, None])
        assert parser._safe_str(s) == ""

    def test_Series部分NaN取第一个非空(self):
        parser = ExcelMappingParser("")
        s = pd.Series([pd.NA, "hello", "world"])
        assert parser._safe_str(s) == "hello"

    def test_pd_NA值(self):
        parser = ExcelMappingParser("")
        assert parser._safe_str(pd.NA) == ""

    def test_np_nan值(self):
        parser = ExcelMappingParser("")
        assert parser._safe_str(np.nan) == ""

    def test_None值(self):
        parser = ExcelMappingParser("")
        assert parser._safe_str(None) == ""

    def test_普通字符串(self):
        parser = ExcelMappingParser("")
        assert parser._safe_str("hello") == "hello"

    def test_整数(self):
        parser = ExcelMappingParser("")
        assert parser._safe_str(42) == "42"


# ── TestNormalizeColumnsDedup ────────────────────────────


class TestNormalizeColumnsDedup:

    def test_重复列名只映射第一个(self):
        """当 Excel 同时有'源字段名'和'源表字段名'时，只映射第一个到 source_column"""
        parser = ExcelMappingParser("")
        df = pd.DataFrame({
            "源表schema": ["ods"],
            "源字段名": ["col_a"],
            "源表字段名": ["col_b"],  # 也映射到 source_column — 应跳过
            "目标字段名": ["target_a"],
        })
        result = parser._normalize_columns(df, parser.ATTRIBUTE_COLUMN_MAP)
        # 不应有两个 source_column
        assert list(result.columns).count("source_column") == 1
        # 应产生诊断
        types = [d["type"] for d in parser.diagnostics]
        assert "duplicate_column_mapping" in types

    def test_无重复列名正常映射(self):
        parser = ExcelMappingParser("")
        df = pd.DataFrame({
            "源表schema": ["ods"],
            "源字段名": ["col_a"],
            "目标字段名": ["target_a"],
        })
        result = parser._normalize_columns(df, parser.ATTRIBUTE_COLUMN_MAP)
        assert "source_schema" in result.columns
        assert "source_column" in result.columns
        assert "target_column" in result.columns


# ── TestSceneGroupParsing ────────────────────────────────


class TestSceneGroupParsing:

    def _make_entity_df_with_group(self, group: str) -> pd.DataFrame:
        return pd.DataFrame([{
            "源表schema": "ods",
            "源表物理表名": "ods_order_f",
            "源表中文名": "订单表",
            "目标表schema": "slprd",
            "目标表物理表名": "dwb_order_f",
            "目标表中文名": "订单宽表",
            "关联&限定条件": "主表",
            "备注": "",
            "源表别名": "",
            "分组": group,
        }])

    def _make_attr_df_with_group(self, group: str) -> pd.DataFrame:
        return pd.DataFrame([{
            "源表schema": "ods",
            "源表物理表名": "ods_order_f",
            "源字段名": "order_id",
            "源字段类型": "bigint",
            "映射规则": "直取",
            "映射表达式": "",
            "目标字段名": "order_id",
            "目标字段中文名": "订单ID",
            "目标字段类型": "bigint",
            "源表别名": "",
            "分组": group,
        }])

    def test_实体级解析分组列(self, tmp_path):
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": self._make_entity_df_with_group("eb"),
                "属性级mapping": self._make_attr_df_with_group("eb"),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        entities = parser.parse_entity_mapping()
        assert len(entities) == 1
        assert entities[0].scene_group == "eb"

    def test_属性级解析分组列(self, tmp_path):
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": self._make_entity_df_with_group("eb"),
                "属性级mapping": self._make_attr_df_with_group("eb"),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        attrs = parser.parse_attribute_mapping()
        assert len(attrs) >= 1
        assert attrs[0].scene_group == "eb"

    def test_场景列名也识别(self, tmp_path):
        """列名'场景'也能映射到 scene_group"""
        df_entity = pd.DataFrame([{
            "源表schema": "ods",
            "源表物理表名": "ods_order_f",
            "源表中文名": "订单表",
            "目标表schema": "slprd",
            "目标表物理表名": "dwb_order_f",
            "目标表中文名": "订单宽表",
            "关联&限定条件": "主表",
            "备注": "",
            "源表别名": "",
            "场景": "分组1",
        }])
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": df_entity,
                "属性级mapping": self._make_attr_df_with_group("分组1"),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        entities = parser.parse_entity_mapping()
        assert entities[0].scene_group == "分组1"

    def test_空分组列不影响解析(self, tmp_path):
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": self._make_entity_df_with_group(""),
                "属性级mapping": self._make_attr_df_with_group(""),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        entities = parser.parse_entity_mapping()
        attrs = parser.parse_attribute_mapping()
        assert len(entities) == 1
        assert entities[0].scene_group == ""
        assert len(attrs) >= 1


# ── TestGroupConsistencyCheck ────────────────────────────


class TestGroupConsistencyCheck:

    def _make_entity_df(self, group: str) -> pd.DataFrame:
        return pd.DataFrame([{
            "源表schema": "ods",
            "源表物理表名": "ods_order_f",
            "源表中文名": "订单表",
            "目标表schema": "slprd",
            "目标表物理表名": "dwb_order_f",
            "目标表中文名": "订单宽表",
            "关联&限定条件": "主表",
            "备注": "",
            "源表别名": "",
            "分组": group,
        }])

    def _make_attr_df(self, group: str) -> pd.DataFrame:
        return pd.DataFrame([{
            "源表schema": "ods",
            "源表物理表名": "ods_order_f",
            "源字段名": "order_id",
            "源字段类型": "bigint",
            "映射规则": "直取",
            "映射表达式": "",
            "目标字段名": "order_id",
            "目标字段中文名": "订单ID",
            "目标字段类型": "bigint",
            "源表别名": "",
            "分组": group,
        }])

    def test_实体级占位值default检测(self, tmp_path):
        """实体级写 default 但属性级写 eb/dpb → 应产生诊断"""
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": self._make_entity_df("default"),
                "属性级mapping": self._make_attr_df("eb"),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        parser.parse()
        types = [d["type"] for d in parser.diagnostics]
        assert "group_placeholder_detected" in types

    def test_分组不匹配检测(self, tmp_path):
        """属性级分组不在实体级分组中 → 应产生诊断"""
        entity_df = pd.DataFrame([
            {**self._make_entity_df("eb").iloc[0].to_dict()},
        ])
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": entity_df,
                "属性级mapping": self._make_attr_df("dpb"),  # dpb 不在实体级中
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        parser.parse()
        types = [d["type"] for d in parser.diagnostics]
        assert "group_mismatch" in types

    def test_分组一致无诊断(self, tmp_path):
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": self._make_entity_df("eb"),
                "属性级mapping": self._make_attr_df("eb"),
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        parser.parse()
        types = [d["type"] for d in parser.diagnostics]
        assert "group_placeholder_detected" not in types
        assert "group_mismatch" not in types


# ── TestDetectDesignPatternExpanded ──────────────────────


class TestDetectDesignPatternExpanded:

    def test_scene_group字段优先(self):
        """scene_group 字段值应优先于 remark 匹配"""
        parser = ExcelMappingParser("")
        entities = [
            EntityMapping(
                source_schema="ods", source_table="t1", source_table_cn="表1",
                target_schema="slprd", target_table_cn="目标", target_table="tgt",
                join_condition="", remark="", scene_group="分组1",
            ),
            EntityMapping(
                source_schema="ods", source_table="t2", source_table_cn="表2",
                target_schema="slprd", target_table_cn="目标", target_table="tgt",
                join_condition="", remark="", scene_group="分组2",
            ),
        ]
        result = parser._detect_design_pattern(entities)
        assert result == ("multi_scene_union", 2)

    def test_分组关键词识别(self):
        parser = ExcelMappingParser("")
        entities = [
            EntityMapping(
                source_schema="ods", source_table="t1", source_table_cn="表1",
                target_schema="slprd", target_table_cn="目标", target_table="tgt",
                join_condition="", remark="分组1xxx",
            ),
            EntityMapping(
                source_schema="ods", source_table="t2", source_table_cn="表2",
                target_schema="slprd", target_table_cn="目标", target_table="tgt",
                join_condition="", remark="分组2yyy",
            ),
        ]
        result = parser._detect_design_pattern(entities)
        assert result == ("multi_scene_union", 2)

    def test_GROUP关键词识别(self):
        parser = ExcelMappingParser("")
        entities = [
            EntityMapping(
                source_schema="ods", source_table="t1", source_table_cn="表1",
                target_schema="slprd", target_table_cn="目标", target_table="tgt",
                join_condition="", remark="GROUP 1",
            ),
            EntityMapping(
                source_schema="ods", source_table="t2", source_table_cn="表2",
                target_schema="slprd", target_table_cn="目标", target_table="tgt",
                join_condition="", remark="GROUP 2",
            ),
        ]
        result = parser._detect_design_pattern(entities)
        assert result == ("multi_scene_union", 2)

    def test_第N组关键词识别(self):
        parser = ExcelMappingParser("")
        entities = [
            EntityMapping(
                source_schema="ods", source_table="t1", source_table_cn="表1",
                target_schema="slprd", target_table_cn="目标", target_table="tgt",
                join_condition="", remark="第1组-基础",
            ),
            EntityMapping(
                source_schema="ods", source_table="t2", source_table_cn="表2",
                target_schema="slprd", target_table_cn="目标", target_table="tgt",
                join_condition="", remark="第2组-统计",
            ),
        ]
        result = parser._detect_design_pattern(entities)
        assert result == ("multi_scene_union", 2)


# ── TestRowParseErrorTolerance ────────────────────────────


class TestRowParseErrorTolerance:

    def test_异常行跳过不崩溃(self, tmp_path):
        """含 NaN 单元格的行不应导致崩溃"""
        attr_df = pd.DataFrame([
            {
                "源表schema": "ods",
                "源表物理表名": "ods_order_f",
                "源字段名": None,  # NaN 单元格
                "源字段类型": None,
                "映射规则": "直取",
                "映射表达式": None,
                "目标字段名": "order_id",
                "目标字段中文名": "订单ID",
                "目标字段类型": "bigint",
                "源表别名": None,
            },
            {
                "源表schema": "ods",
                "源表物理表名": "ods_order_f",
                "源字段名": "amount",
                "源字段类型": "decimal",
                "映射规则": "直取",
                "映射表达式": "",
                "目标字段名": "amount",
                "目标字段中文名": "金额",
                "目标字段类型": "decimal",
                "源表别名": "",
            },
        ])
        filepath = _create_excel(
            tmp_path,
            {
                "实体级mapping": _make_entity_df(),
                "属性级mapping": attr_df,
            },
        )
        parser = ExcelMappingParser(str(filepath))
        parser.load()
        attrs = parser.parse_attribute_mapping()
        # 两行都应成功解析（NaN 转为空字符串）
        assert len(attrs) == 2
        assert attrs[0].source_column == ""  # None → ""
        assert attrs[1].source_column == "amount"
