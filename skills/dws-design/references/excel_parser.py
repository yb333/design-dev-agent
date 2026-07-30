#!/usr/bin/env python3
"""
ETL Mapping Excel 解析工具

功能:
1. 解析实体级 mapping (源表、目标表、关联条件)
2. 解析属性级 mapping (字段映射、转换逻辑)
3. 输出结构化 JSON/Markdown 格式

使用方法:
    python excel_parser.py --input mapping.xlsx --output ./output
    python excel_parser.py --input mapping.xlsx --format json --output mapping.json
"""

VERSION = "2.7.0"
CHANGELOG = """
v2.7.0 (2026-04-16):
  - 修复: _normalize_columns 重复列名映射导致 row.get() 返回 Series 崩溃（根因修复）
  - 修复: _safe_str 增加 Series/None/异常类型防御，解析器永不 crash
  - 修复: 行级 try/except 保护，单行解析失败记录诊断继续下一行
  - 新增: scene_group 字段，支持「分组」「场景」等多种列名识别
  - 新增: 跨级分组一致性校验（实体级占位值检测、分组不匹配检测）
  - 新增: 场景关键词扩展（分组/场景/SCENE/GROUP/来源/逻辑）
  - 修复: str() 替代 _safe_str() 导致 'nan' 字符串泄漏
v2.6.0 (2026-04-13):
  - 新增: DesignConfig 新增 target_grain（目标表粒度）、write_strategy（写入策略）、incremental_key（增量键）
  - 新增: 键值映射支持「目标表粒度」「写入策略」「增量键」
  - 新增: Markdown 和 Summary 输出包含新增配置项
v2.5.0 (2026-04-09):
  - 新增: 三层列名匹配机制（精确→子串→模糊），大幅提升列名变体兼容性
  - 新增: _clean_column_name 预处理（strip 尾部*、全角→半角）
  - 新增: _fuzzy_match 基于 difflib.SequenceMatcher（阈值 0.75）
  - 新增: 模糊匹配结果写入 diagnostics（column_fuzzy_match 类型）
  - 修复: 路径构建防双重 01_input 嵌套（--output 传了 01_input 时不再重复拼接）
v2.4.0 (2026-04-09):
  - 新增: 解析「数据处理步骤」sheet（步骤组 + 步骤编号 + 说明）
  - 新增: DataFlowStep、DataFlowConfig 数据结构
  - 新增: MappingDocument 增加 data_flow 字段
  - 新增: JSON/Markdown/Summary 输出包含数据处理步骤
  - 兼容: 数据处理步骤 sheet 为可选，不存在时不影响原有功能
v2.3.0 (2026-04-03):
  - 新增: 自动补充标准审计字段（del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date）
    当用户 mapping 中缺少审计字段时，解析结果自动追加标准定义
v2.2.0 (2026-03-26):
  - 新增: 属性级 mapping 支持 "源表别名" 列（用于区分同一源表的不同关联实例）
  - 新增: AttributeMapping 增加 source_alias 字段
v2.1.0 (2026-03-26):
  - 新增: 实体级 mapping 支持 "源表别名" 列
  - 新增: 解析 "设计配置" sheet（键值对: 封装视图），输出 DesignConfig
  - 新增: EntityMapping 增加 source_alias 字段
  - 新增: MappingDocument 增加 design_config 字段
  - 兼容: 源表别名和设计配置 sheet 均为可选，不存在时不影响原有功能
v2.0.0 (2026-03-25):
  - 新增: 解析 "执行平台配置" sheet（键值对: 配置项/值），输出 ExecutionPlatformConfig
  - 新增: SchedulingConfig 增加 owner 字段（调度平台责任人）
  - 新增: MappingDocument 增加 execution_platform_config 字段
  - 新增: JSON/Markdown/Summary 输出包含执行平台配置信息
  - 兼容: 执行平台配置 sheet 和调度责任人字段为可选，不存在时不影响原有功能
v1.5.0 (2026-03-23):
  - 新增: 解析 "调度配置" sheet（键值对: 配置项/值），输出 SchedulingConfig
  - 新增: 实体级 mapping 支持 "调度任务名称" 和 "执行路径" 列
  - 新增: JSON/Markdown/Summary 输出包含调度配置信息
  - 兼容: 调度配置 sheet 和新增列为可选，不存在时不影响原有功能
v1.4.1 (2026-03-11):
  - 修复: to_json() 输出 design_pattern/scene_count/field_statistics 字段
  - 修复: to_markdown() 输出设计模式和字段统计信息
  - 修复: to_summary() 输出设计模式信息
  - 修复: _detect_design_pattern() 场景计数逻辑（改为提取场景编号并去重）
v1.4.0 (2026-03-11):
  - 新增: 设计模式识别（multi_scene_union / single_source）
  - 新增: 字段统计输出（总记录数、去重字段数、直取/加工分布）
  - 优化: 多场景设计自动识别，供 precheck.py 使用
v1.3.1 (2026-02-28):
  - 优化: 添加 Windows 控制台 UTF-8 编码支持
  - 改进: 跨平台兼容性增强
v1.3.0 (2026-02-25):
  - 新增: 自动推断依赖表功能
    - 从 mapping_expression 中识别表名引用（如"从 dwd_order_detail_f 汇总..."）
    - 自动填充加工字段的 source_table 字段
    - 支持 schema.table 和 table 两种格式
  - 修复: 添加 '源表字段名' 列名别名，解决 source_column 为空的问题
  - 兼容: 同时支持 '源字段名' 和 '源表字段名' 两种列名
v1.2.0 (2026-02-19):
  - 修复: 添加 '源字段类型' 列名别名，解决 source_type 为空的问题
  - 兼容: 同时支持 '源字段类型' 和 '源表字段类型' 两种列名
v1.1.0 (2026-02-18):
  - 修复: 列名映射 '源表字段名' → '源字段名'，解决 source_column 全部为空的问题
v1.0.0:
  - 初始版本
"""

import os
import re
import sys
import json
import argparse
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    import pandas as pd
except ImportError:
    print("请安装 pandas: pip install pandas openpyxl")
    sys.exit(1)


@dataclass
class SchedulingConfig:
    """调度配置（来自 "调度配置" sheet 的键值对）"""
    project_name: str = ''
    task_group: str = ''
    schedule_cycle: str = ''
    owner: str = ''


@dataclass
class ExecutionPlatformConfig:
    """执行平台配置（来自 "执行平台配置" sheet 的键值对）"""
    project_code: str = ''
    project_cn_name: str = ''
    project_en_name: str = ''
    sub_project_code: str = ''
    sub_project_cn_name: str = ''
    sub_project_en_name: str = ''
    data_source: str = ''
    business_owner: str = ''


@dataclass
class DesignConfig:
    """设计配置（来自 "设计配置" sheet 的键值对）"""
    wrap_view: bool = False
    target_grain: str = ''          # 目标表粒度，如 "每个商品一行（商品ID）"
    write_strategy: str = ''        # 写入策略: "全量" / "增量"，空则 AI 推断
    incremental_key: str = ''       # 增量键（仅增量时填写），如 "order_id"


@dataclass
class DataFlowStep:
    """数据处理步骤（一行）"""
    group_name: str      # 步骤组名称（如"商品分类"）
    step_number: int     # 步骤编号（组内顺序）
    description: str     # 步骤说明（原文，一字不改）


@dataclass
class DataFlowConfig:
    """数据处理步骤配置（整个 sheet）"""
    groups: List[Dict[str, Any]]  # [{"name": "商品分类", "steps": [{"step": 1, "description": "..."}]}]


@dataclass
class EntityMapping:
    """实体级映射"""
    source_schema: str
    source_table: str
    source_table_cn: str
    target_schema: str
    target_table_cn: str
    target_table: str
    join_condition: str
    remark: str
    schedule_task: str = ''
    exec_path: str = ''
    dep_job_params: str = ''
    source_alias: str = ''
    scene_group: str = ''


@dataclass
class AttributeMapping:
    """属性级映射"""
    source_schema: str
    source_table: str
    source_column: str
    source_type: str
    mapping_rule: str  # 直取/赋值/加工
    mapping_expression: str
    target_column: str
    target_column_cn: str
    target_type: str
    source_alias: str = ''
    scene_group: str = ''


@dataclass
class MappingDocument:
    """完整的映射文档"""
    target_schema: str
    target_table: str
    target_table_cn: str
    source_tables: List[EntityMapping]
    field_mappings: List[AttributeMapping]
    parse_time: str
    # v1.4.0 新增字段
    design_pattern: str = 'single_source'  # multi_scene_union / single_source
    scene_count: int = 1
    field_statistics: Optional[Dict[str, int]] = None
    scheduling_config: Optional[SchedulingConfig] = None
    execution_platform_config: Optional[ExecutionPlatformConfig] = None
    design_config: Optional[DesignConfig] = None
    data_flow: Optional[DataFlowConfig] = None


class ExcelMappingParser:
    """Excel Mapping 解析器"""

    # 标准 sheet 名称
    ENTITY_SHEET_NAMES = ['实体级mapping', '实体级', 'entity', 'Entity']
    ATTRIBUTE_SHEET_NAMES = ['属性级mapping', '属性级', 'attribute', 'Attribute']
    SCHEDULE_SHEET_NAMES = ['调度配置', 'scheduling', 'schedule']
    EXEC_PLATFORM_SHEET_NAMES = ['执行平台配置', 'execution_platform', 'execution']
    DESIGN_CONFIG_SHEET_NAMES = ['设计配置', 'design_config']
    DATA_FLOW_SHEET_NAMES = ['数据处理步骤', 'data_flow', 'DataFlow']

    # 实体级 mapping 列名映射
    ENTITY_COLUMN_MAP = {
        '源表schema': 'source_schema',
        '源表物理表名': 'source_table',
        '源表中文名': 'source_table_cn',
        '源表别名': 'source_alias',
        '目标表schema': 'target_schema',
        '目标表中文名': 'target_table_cn',
        '目标表物理表名': 'target_table',
        '关联&限定条件': 'join_condition',
        '备注': 'remark',
        '调度任务名称': 'schedule_task',
        '执行路径': 'exec_path',
        '依赖参数': 'dep_job_params',
        '分组': 'scene_group',
        '场景分组': 'scene_group',
        '数据分组': 'scene_group',
        '分组名称': 'scene_group',
        '场景': 'scene_group',
        '场景名称': 'scene_group',
    }
    
    # 属性级 mapping 列名映射（支持多种列名格式）
    ATTRIBUTE_COLUMN_MAP = {
        '源表schema': 'source_schema',
        '源表物理表名': 'source_table',
        '源表别名': 'source_alias',
        '源字段名': 'source_column',
        '源表字段名': 'source_column',
        '源字段类型': 'source_type',
        '源表字段类型': 'source_type',
        '数据类型': 'source_type',
        '字段类型': 'source_type',
        '映射规则': 'mapping_rule',
        '映射表达式': 'mapping_expression',
        '目标字段名': 'target_column',
        '目标字段中文名': 'target_column_cn',
        '目标字段类型': 'target_type',
        '分组': 'scene_group',
        '场景分组': 'scene_group',
        '数据分组': 'scene_group',
        '分组名称': 'scene_group',
        '场景': 'scene_group',
        '场景名称': 'scene_group',
    }
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.entity_df: Optional[pd.DataFrame] = None
        self.attribute_df: Optional[pd.DataFrame] = None
        self.schedule_config_df: Optional[pd.DataFrame] = None
        self.exec_platform_config_df: Optional[pd.DataFrame] = None
        self.design_config_df: Optional[pd.DataFrame] = None
        self.data_flow_df: Optional[pd.DataFrame] = None
        self.diagnostics: List[Dict[str, str]] = []
        
    def load(self) -> bool:
        """加载 Excel 文件"""
        try:
            xlsx = pd.ExcelFile(self.filepath)
            sheet_names = xlsx.sheet_names
            
            recognized_sheets = set()
            for sheet in sheet_names:
                sheet_lower = sheet.lower()
                if any(s in sheet_lower for s in ['实体级', 'entity']):
                    self.entity_df = pd.read_excel(xlsx, sheet_name=sheet)
                    recognized_sheets.add(sheet)
                elif any(s in sheet_lower for s in ['属性级', 'attribute']):
                    self.attribute_df = pd.read_excel(xlsx, sheet_name=sheet)
                    recognized_sheets.add(sheet)
                elif any(s in sheet_lower for s in [sn.lower() for sn in self.SCHEDULE_SHEET_NAMES]):
                    self.schedule_config_df = pd.read_excel(xlsx, sheet_name=sheet)
                    recognized_sheets.add(sheet)
                elif any(s in sheet_lower for s in [sn.lower() for sn in self.EXEC_PLATFORM_SHEET_NAMES]):
                    self.exec_platform_config_df = pd.read_excel(xlsx, sheet_name=sheet)
                    recognized_sheets.add(sheet)
                elif any(s in sheet_lower for s in [sn.lower() for sn in self.DESIGN_CONFIG_SHEET_NAMES]):
                    self.design_config_df = pd.read_excel(xlsx, sheet_name=sheet)
                    recognized_sheets.add(sheet)
                elif any(s in sheet_lower for s in [sn.lower() for sn in self.DATA_FLOW_SHEET_NAMES]):
                    self.data_flow_df = pd.read_excel(xlsx, sheet_name=sheet)
                    recognized_sheets.add(sheet)
            
            for sheet in sheet_names:
                if sheet not in recognized_sheets:
                    self.diagnostics.append({
                        'type': 'sheet_unrecognized',
                        'sheet': sheet,
                        'message': f'Sheet "{sheet}" 未被识别，建议使用标准名称：实体级mapping、属性级mapping、调度配置、执行平台配置、设计配置',
                    })
            
            if self.entity_df is None and self.attribute_df is None:
                self.diagnostics.append({
                    'type': 'sheet_missing_critical',
                    'sheet': '',
                    'message': '未找到实体级mapping或属性级mapping sheet，无法解析',
                })
            
            return self.entity_df is not None or self.attribute_df is not None
        except Exception as e:
            self.diagnostics.append({
                'type': 'load_error',
                'sheet': '',
                'message': f'加载文件失败: {e}',
            })
            return False
    
    def parse_entity_mapping(self) -> List[EntityMapping]:
        """解析实体级映射"""
        if self.entity_df is None:
            return []
        
        mappings = []
        
        df = self._normalize_columns(self.entity_df, self.ENTITY_COLUMN_MAP)
        self._check_column_match(self.entity_df, self.ENTITY_COLUMN_MAP, '实体级mapping',
                                 required=['source_schema', 'source_table', 'target_table', 'target_schema'])
        
        for row_idx, (_, row) in enumerate(df.iterrows()):
            try:
                mapping = EntityMapping(
                    source_schema=self._safe_str(row.get('source_schema', '')),
                    source_table=self._safe_str(row.get('source_table', '')),
                    source_table_cn=self._safe_str(row.get('source_table_cn', '')),
                    target_schema=self._safe_str(row.get('target_schema', '')),
                    target_table_cn=self._safe_str(row.get('target_table_cn', '')),
                    target_table=self._safe_str(row.get('target_table', '')),
                    join_condition=self._safe_str(row.get('join_condition', '')),
                    remark=self._safe_str(row.get('remark', '')),
                    schedule_task=self._safe_str(row.get('schedule_task', '')),
                    exec_path=self._safe_str(row.get('exec_path', '')),
                    dep_job_params=self._safe_str(row.get('dep_job_params', '')),
                    source_alias=self._safe_str(row.get('source_alias', '')),
                    scene_group=self._safe_str(row.get('scene_group', ''))
                )
                
                if mapping.source_table or mapping.target_table:
                    mappings.append(mapping)
            except Exception as e:
                self.diagnostics.append({
                    'type': 'row_parse_error',
                    'sheet': '实体级mapping',
                    'message': f'第 {row_idx + 2} 行解析失败: {e}，请检查该行数据格式',
                })
        
        return mappings
    
    def parse_scheduling_config(self) -> Optional[SchedulingConfig]:
        if self.schedule_config_df is None:
            return None
        
        config = SchedulingConfig()
        key_col = None
        val_col = None
        
        for col in self.schedule_config_df.columns:
            col_str = self._safe_str(col)
            if '配置项' in col_str:
                key_col = col
            elif '值' in col_str:
                val_col = col
        
        if key_col is None or val_col is None:
            return None
        
        key_to_field = {
            '项目名称': 'project_name',
            '任务组名称': 'task_group',
            '调度周期': 'schedule_cycle',
            '责任人': 'owner',
        }
        
        for _, row in self.schedule_config_df.iterrows():
            key = self._safe_str(row.get(key_col, ''))
            val = self._safe_str(row.get(val_col, ''))
            field_name = key_to_field.get(key)
            if field_name and val:
                setattr(config, field_name, val)
        
        if config.project_name or config.task_group or config.schedule_cycle:
            return config
        return None
    
    def parse_execution_platform_config(self) -> Optional[ExecutionPlatformConfig]:
        if self.exec_platform_config_df is None:
            return None

        config = ExecutionPlatformConfig()
        key_col = None
        val_col = None

        for col in self.exec_platform_config_df.columns:
            col_str = self._safe_str(col)
            if '配置项' in col_str:
                key_col = col
            elif '值' in col_str:
                val_col = col

        if key_col is None or val_col is None:
            return None

        key_to_field = {
            '项目编码': 'project_code',
            '项目中文名': 'project_cn_name',
            '项目英文名': 'project_en_name',
            '子项目编码': 'sub_project_code',
            '子项目中文名': 'sub_project_cn_name',
            '子项目英文名': 'sub_project_en_name',
            '数据源': 'data_source',
            '业务责任人': 'business_owner',
        }

        for _, row in self.exec_platform_config_df.iterrows():
            key = self._safe_str(row.get(key_col, ''))
            val = self._safe_str(row.get(val_col, ''))
            field_name = key_to_field.get(key)
            if field_name and val:
                setattr(config, field_name, val)

        if config.project_code or config.sub_project_code or config.data_source:
            return config
        return None

    def parse_design_config(self) -> Optional[DesignConfig]:
        if self.design_config_df is None:
            return None

        config = DesignConfig()
        key_col = None
        val_col = None

        for col in self.design_config_df.columns:
            col_str = self._safe_str(col)
            if '配置项' in col_str:
                key_col = col
            elif '值' in col_str:
                val_col = col

        if key_col is None or val_col is None:
            return None

        key_to_field = {
            '封装视图': 'wrap_view',
            '目标表粒度': 'target_grain',
            '写入策略': 'write_strategy',
            '增量键': 'incremental_key',
        }

        for _, row in self.design_config_df.iterrows():
            key = self._safe_str(row.get(key_col, ''))
            val = self._safe_str(row.get(val_col, ''))
            field_name = key_to_field.get(key)
            if field_name:
                if field_name == 'wrap_view':
                    setattr(config, field_name, val == '是')
                elif field_name in ('target_grain', 'write_strategy', 'incremental_key'):
                    setattr(config, field_name, val)

        return config

    def parse_data_flow(self) -> Optional[DataFlowConfig]:
        if self.data_flow_df is None:
            return None

        groups = []
        current_group = None

        for _, row in self.data_flow_df.iterrows():
            group_name = ''
            step_number = 0
            description = ''

            for col in self.data_flow_df.columns:
                col_str = self._safe_str(col)
                val = self._safe_str(row.get(col, ''))

                if not val:
                    continue
                if any(k in col_str for k in ['步骤组', '组名', 'step_group', 'group']):
                    group_name = val
                elif any(k in col_str for k in ['步骤', '编号', 'step']):
                    try:
                        step_number = int(val)
                    except ValueError:
                        pass
                elif any(k in col_str for k in ['说明', '描述', 'description', 'desc']):
                    description = val

            if not description:
                continue

            if current_group and current_group['name'] == group_name:
                current_group['steps'].append({
                    'step': step_number,
                    'description': description
                })
            else:
                if current_group:
                    groups.append(current_group)
                current_group = {
                    'name': group_name,
                    'steps': [{'step': step_number, 'description': description}]
                }

        if current_group:
            groups.append(current_group)

        if not groups:
            return None

        return DataFlowConfig(groups=groups)

    def parse_attribute_mapping(self) -> List[AttributeMapping]:
        """解析属性级映射"""
        if self.attribute_df is None:
            return []
        
        mappings = []
        
        df = self._normalize_columns(self.attribute_df, self.ATTRIBUTE_COLUMN_MAP)
        self._check_column_match(self.attribute_df, self.ATTRIBUTE_COLUMN_MAP, '属性级mapping',
                                 required=['target_column', 'mapping_rule'])
        
        for row_idx, (_, row) in enumerate(df.iterrows()):
            try:
                mapping = AttributeMapping(
                    source_schema=self._safe_str(row.get('source_schema', '')),
                    source_table=self._safe_str(row.get('source_table', '')),
                    source_column=self._safe_str(row.get('source_column', '')),
                    source_type=self._safe_str(row.get('source_type', '')),
                    mapping_rule=self._safe_str(row.get('mapping_rule', '直取')),
                    mapping_expression=self._safe_str(row.get('mapping_expression', '')),
                    target_column=self._safe_str(row.get('target_column', '')),
                    target_column_cn=self._safe_str(row.get('target_column_cn', '')),
                    target_type=self._safe_str(row.get('target_type', '')),
                    source_alias=self._safe_str(row.get('source_alias', '')),
                    scene_group=self._safe_str(row.get('scene_group', ''))
                )
                
                # v1.3.0: 自动推断依赖表
                if mapping.mapping_rule == '加工' and not mapping.source_table and mapping.mapping_expression:
                    inferred_table = self._infer_source_table_from_expression(
                        mapping.mapping_expression,
                        self._safe_str(row.get('source_schema', ''))
                    )
                    if inferred_table:
                        mapping = AttributeMapping(
                            source_schema=mapping.source_schema or inferred_table.get('schema', ''),
                            source_table=inferred_table.get('table', ''),
                            source_column=mapping.source_column,
                            source_type=mapping.source_type,
                            mapping_rule=mapping.mapping_rule,
                            mapping_expression=mapping.mapping_expression,
                            target_column=mapping.target_column,
                            target_column_cn=mapping.target_column_cn,
                            target_type=mapping.target_type,
                            source_alias=mapping.source_alias,
                            scene_group=mapping.scene_group
                        )
                
                if mapping.target_column:
                    mappings.append(mapping)
            except Exception as e:
                self.diagnostics.append({
                    'type': 'row_parse_error',
                    'sheet': '属性级mapping',
                    'message': f'第 {row_idx + 2} 行解析失败: {e}，请检查该行数据格式',
                })
        
        return mappings
    
    STANDARD_AUDIT_FIELDS = [
        AttributeMapping(
            source_schema='', source_table='', source_column='',
            source_type='', mapping_rule='赋值', mapping_expression="'N'",
            target_column='del_flag', target_column_cn='删除标识',
            target_type='NVARCHAR(1)', source_alias=''
        ),
        AttributeMapping(
            source_schema='', source_table='', source_column='',
            source_type='', mapping_rule='赋值', mapping_expression='${P_CYCLE_ID}',
            target_column='crt_cycle_id', target_column_cn='创建批次ID',
            target_type='BIGINT', source_alias=''
        ),
        AttributeMapping(
            source_schema='', source_table='', source_column='',
            source_type='', mapping_rule='赋值', mapping_expression='${P_CYCLE_ID}',
            target_column='last_upd_cycle_id', target_column_cn='最后更新批次ID',
            target_type='BIGINT', source_alias=''
        ),
        AttributeMapping(
            source_schema='', source_table='', source_column='',
            source_type='', mapping_rule='赋值', mapping_expression='CURRENT_TIMESTAMP',
            target_column='dw_last_update_date', target_column_cn='数仓最后更新时间',
            target_type='TIMESTAMP(0) WITHOUT TIME ZONE', source_alias=''
        ),
    ]

    def parse(self) -> MappingDocument:
        """解析完整的映射文档"""
        entity_mappings = self.parse_entity_mapping()
        attribute_mappings = self.parse_attribute_mapping()
        scheduling_config = self.parse_scheduling_config()
        execution_platform_config = self.parse_execution_platform_config()
        design_config = self.parse_design_config()
        data_flow = self.parse_data_flow()

        target_schema = ''
        target_table = ''
        target_table_cn = ''

        if entity_mappings:
            first = entity_mappings[0]
            target_schema = first.target_schema
            target_table = first.target_table
            target_table_cn = first.target_table_cn

        existing_targets = {f.target_column for f in attribute_mappings}
        for audit_field in self.STANDARD_AUDIT_FIELDS:
            if audit_field.target_column not in existing_targets:
                attribute_mappings.append(audit_field)

        design_pattern, scene_count = self._detect_design_pattern(entity_mappings)
        field_statistics = self._calculate_field_statistics(attribute_mappings)

        self._check_group_consistency(entity_mappings, attribute_mappings)

        return MappingDocument(
            target_schema=target_schema,
            target_table=target_table,
            target_table_cn=target_table_cn,
            source_tables=entity_mappings,
            field_mappings=attribute_mappings,
            parse_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            design_pattern=design_pattern,
            scene_count=scene_count,
            field_statistics=field_statistics,
            scheduling_config=scheduling_config,
            execution_platform_config=execution_platform_config,
            design_config=design_config,
            data_flow=data_flow
        )
    
    SCENE_KEYWORD_PATTERNS = [
        r'场景\s*(\d+)',
        r'SCENE\s*(\d+)',
        r'分组\s*(\d+)',
        r'第\s*(\d+)\s*组',
        r'GROUP\s*(\d+)',
        r'组\s*(\d+)',
        r'来源\s*(\d+)',
        r'逻辑\s*(\d+)',
    ]

    def _check_group_consistency(self, entity_mappings: List[EntityMapping], 
                                  attribute_mappings: List[AttributeMapping]) -> None:
        """校验实体级和属性级 mapping 的分组一致性"""
        entity_groups = {m.scene_group for m in entity_mappings if m.scene_group}
        attr_groups = {m.scene_group for m in attribute_mappings if m.scene_group}
        
        if not entity_groups and not attr_groups:
            return
        
        PLACEHOLDER_VALUES = {'default', '默认', 'DEFAULT', '无', 'N/A', 'na', 'NA', '-'}
        bad_entity_groups = entity_groups & PLACEHOLDER_VALUES
        if bad_entity_groups and (attr_groups - PLACEHOLDER_VALUES):
            real_attr_groups = attr_groups - PLACEHOLDER_VALUES
            self.diagnostics.append({
                'type': 'group_placeholder_detected',
                'sheet': '实体级mapping',
                'message': f'实体级 mapping 的「分组」列包含占位值 {bad_entity_groups}，'
                           f'但属性级 mapping 有实际分组: {real_attr_groups}。'
                           f'请将实体级的「分组」列修改为与属性级一致',
            })
        
        valid_entity_groups = entity_groups - PLACEHOLDER_VALUES
        if valid_entity_groups and attr_groups:
            orphan_groups = attr_groups - valid_entity_groups - PLACEHOLDER_VALUES
            if orphan_groups:
                self.diagnostics.append({
                    'type': 'group_mismatch',
                    'sheet': '属性级mapping',
                    'message': f'属性级 mapping 存在实体级未定义的分组: {orphan_groups}，'
                               f'实体级已有分组: {valid_entity_groups}。'
                               f'请在实体级 mapping 补充对应的源表行，或修改属性级的分组名称',
                })

    def _detect_design_pattern(self, source_tables: List[EntityMapping]) -> tuple:
        scenes = set()
        
        # 优先从 scene_group 字段提取（显式分组列）
        for s in source_tables:
            if s.scene_group:
                group = s.scene_group.strip()
                # 提取分组中的数字编号
                match = re.search(r'(\d+)', group)
                if match:
                    scenes.add(int(match.group(1)))
        
        # 补充: 从 remark 中提取（兼容旧格式）
        if not scenes:
            for s in source_tables:
                for pattern in self.SCENE_KEYWORD_PATTERNS:
                    match = re.search(pattern, s.remark, re.IGNORECASE)
                    if match:
                        scenes.add(int(match.group(1)))
                        break
        
        scene_count = len(scenes)
        if scene_count >= 2:
            return ('multi_scene_union', scene_count)
        return ('single_source', 1)
    
    def _calculate_field_statistics(self, field_mappings: List[AttributeMapping]) -> Dict[str, int]:
        """v1.4.0: 计算字段统计"""
        total = len(field_mappings)
        unique_fields = len(set(f.target_column for f in field_mappings if f.target_column))
        direct = sum(1 for f in field_mappings if f.mapping_rule == '直取')
        processed = sum(1 for f in field_mappings if f.mapping_rule == '加工')
        
        return {
            'total_records': total,
            'unique_fields': unique_fields,
            'direct_mapping': direct,
            'processed_mapping': processed
        }
    
    def _normalize_columns(self, df: pd.DataFrame, column_map: Dict[str, str]) -> pd.DataFrame:
        rename_dict = {}
        matched_keys = set()
        remaining_keys = list(column_map.keys())
        used_targets = set()

        for col in df.columns:
            col_clean = self._clean_column_name(col)

            best_key = None

            # Layer 1: exact match
            if col_clean in column_map:
                best_key = col_clean

            # Layer 2: substring match (longest key first)
            if best_key is None:
                for key in sorted(remaining_keys, key=len, reverse=True):
                    if key in col_clean:
                        best_key = key
                        break

            # Layer 3: fuzzy match (SequenceMatcher, threshold 0.75)
            if best_key is None and remaining_keys:
                fuzzy = self._fuzzy_match(col_clean, remaining_keys)
                if fuzzy:
                    best_key, score = fuzzy
                    self.diagnostics.append({
                        'type': 'column_fuzzy_match',
                        'sheet': '',
                        'message': f'列 "{col}" 模糊匹配到 "{best_key}"（相似度: {score:.0%}）',
                    })

            if best_key is None:
                continue

            target = column_map[best_key]

            # 防重复: 同一个 target 不允许被多列映射
            if target in used_targets:
                self.diagnostics.append({
                    'type': 'duplicate_column_mapping',
                    'sheet': '',
                    'message': f'列 "{col}" 映射到 "{target}" 失败: 已有其他列映射到该字段，'
                               f'请检查 Excel 中是否存在重复或含义重叠的列（如同时存在"源字段名"和"源表字段名"）',
                })
                continue

            rename_dict[col] = target
            matched_keys.add(best_key)
            remaining_keys = [k for k in remaining_keys if k != best_key]
            used_targets.add(target)

        return df.rename(columns=rename_dict)
    
    def _check_column_match(self, df: pd.DataFrame, column_map: Dict[str, str], sheet_label: str, required: Optional[List[str]] = None):
        actual_cols = set()
        for col in df.columns:
            col_clean = self._clean_column_name(col)
            if col_clean in column_map:
                actual_cols.add(column_map[col_clean])
            else:
                matched = False
                for key in sorted(column_map.keys(), key=len, reverse=True):
                    if key in col_clean and column_map[key] not in actual_cols:
                        actual_cols.add(column_map[key])
                        matched = True
                        break
                if not matched:
                    fuzzy = self._fuzzy_match(col_clean, list(column_map.keys()))
                    if fuzzy and column_map[fuzzy[0]] not in actual_cols:
                        actual_cols.add(column_map[fuzzy[0]])
        
        if required:
            for req_field in required:
                if req_field not in actual_cols:
                    self.diagnostics.append({
                        'type': 'column_missing',
                        'sheet': sheet_label,
                        'message': f'{sheet_label}缺少必填列 "{req_field}"，请检查列名是否正确（当前列名: {list(df.columns)}）',
                    })
    
    def _write_diagnostics(self, output_dir: str) -> bool:
        if not self.diagnostics:
            return False
        
        os.makedirs(output_dir, exist_ok=True)
        lines = [f'# 解析诊断 — {len(self.diagnostics)} 个问题', '']
        
        col_issues = [d for d in self.diagnostics if d['type'] == 'column_missing']
        sheet_issues = [d for d in self.diagnostics if d['type'] in ('sheet_unrecognized', 'sheet_missing_critical')]
        other_issues = [d for d in self.diagnostics if d['type'] not in ('column_missing', 'sheet_unrecognized', 'sheet_missing_critical')]
        
        if col_issues:
            lines.append('## 列匹配问题')
            lines.append('| Sheet | 问题 |')
            lines.append('|-------|------|')
            for d in col_issues:
                lines.append(f"| {d['sheet']} | {d['message']} |")
            lines.append('')
        
        if sheet_issues:
            lines.append('## Sheet识别问题')
            lines.append('| Sheet | 问题 |')
            lines.append('|-------|------|')
            for d in sheet_issues:
                lines.append(f"| {d['sheet'] or '-'} | {d['message']} |")
            lines.append('')
        
        if other_issues:
            lines.append('## 其他问题')
            for d in other_issues:
                lines.append(f"- {d['message']}")
            lines.append('')
        
        filepath = os.path.join(output_dir, 'parse_diagnostics.md')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return True
    
    def _safe_str(self, value: Any) -> str:
        """安全转换为字符串，防御 Series/NaN/None 等异常类型"""
        # 防御: 如果 value 是 pandas Series（由重复列名等导致），取第一个非 NaN 值
        if isinstance(value, pd.Series):
            non_null = value.dropna()
            if len(non_null) > 0:
                value = non_null.iloc[0]
            else:
                return ''
        if value is None:
            return ''
        try:
            if pd.isna(value):
                return ''
        except (ValueError, TypeError):
            # pd.isna on some types (e.g. complex) may raise
            pass
        return str(value).strip()

    @staticmethod
    def _clean_column_name(col: str) -> str:
        """预处理列名：strip 空白/尾部*、全角→半角"""
        s = str(col).strip()
        s = s.rstrip('*').strip()
        s = s.translate(str.maketrans(
            'ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ'
            'ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ'
            '０１２３４５６７８９＆',
            'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
            'abcdefghijklmnopqrstuvwxyz'
            '0123456789&',
        ))
        return s

    @staticmethod
    def _fuzzy_match(col: str, keys: List[str], threshold: float = 0.75) -> Optional[Tuple[str, float]]:
        best_key = ''
        best_score = 0.0
        for key in keys:
            score = SequenceMatcher(None, col.strip(), key).ratio()
            if score > best_score:
                best_key, best_score = key, score
        return (best_key, best_score) if best_score >= threshold else None
    
    def _infer_source_table_from_expression(self, expression: str, default_schema: str = '') -> Optional[Dict[str, str]]:
        """
        v1.3.0: 从 mapping_expression 中自动推断依赖表
        
        匹配模式：
        - "从 dwd_order_detail_f 按xxx汇总..."
        - "从 dwd_review_f 按xxx统计..."
        - "从 dim_user_f 关联..."
        - "从dwd_xxx按..."（无空格）
        
        Returns:
            Dict with 'schema' and 'table', or None if no match found
        """
        # 常见表名模式：schema.table 或 table
        # 匹配：从 dwd_xxx / dim_xxx / ods_xxx 等开头
        patterns = [
            r'从\s*([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)\s*按',  # 从...按
            r'从\s*([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)\s*(?:统计|计算|汇总|关联|获取)',  # 从...统计
            r'FROM\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)\s+',
            r'join\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)\s+',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, expression, re.IGNORECASE)
            if match:
                table_ref = match.group(1)
                
                # 如果包含 schema
                if '.' in table_ref:
                    parts = table_ref.split('.')
                    return {'schema': parts[0], 'table': parts[1]}
                else:
                    # 只有表名，使用默认 schema 或从 source_tables 推断
                    schema = default_schema
                    if not schema and hasattr(self, 'entity_df') and self.entity_df is not None:
                        # 从实体级映射中推断 schema
                        df = self._normalize_columns(self.entity_df, self.ENTITY_COLUMN_MAP)
                        for _, row in df.iterrows():
                            source_table = self._safe_str(row.get('source_table', ''))
                            if source_table == table_ref:
                                schema = self._safe_str(row.get('source_schema', ''))
                                break
                    
                    return {'schema': schema, 'table': table_ref}
        
        return None


class MappingExporter:
    """映射文档导出器"""
    
    @staticmethod
    def to_json(doc: MappingDocument, filepath: str):
        """导出为 JSON"""
        data = {
            'target_schema': doc.target_schema,
            'target_table': doc.target_table,
            'target_table_cn': doc.target_table_cn,
            'parse_time': doc.parse_time,
            'source_tables': [asdict(m) for m in doc.source_tables],
            'field_mappings': [asdict(m) for m in doc.field_mappings],
            'design_pattern': doc.design_pattern,
            'scene_count': doc.scene_count,
            'field_statistics': doc.field_statistics,
        }
        
        if doc.scheduling_config:
            data['scheduling_config'] = asdict(doc.scheduling_config)
        
        if doc.execution_platform_config:
            data['execution_platform_config'] = asdict(doc.execution_platform_config)

        if doc.design_config:
            data['design_config'] = asdict(doc.design_config)

        if doc.data_flow:
            data['data_flow'] = {
                'groups': doc.data_flow.groups
            }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"JSON 已导出: {filepath}")
    
    @staticmethod
    def to_markdown(doc: MappingDocument, filepath: str):
        """导出为 Markdown"""
        lines = []
        
        lines.append(f"# {doc.target_table_cn or doc.target_table} 映射文档")
        lines.append("")
        lines.append(f"**目标表**: `{doc.target_schema}.{doc.target_table}`")
        lines.append(f"**解析时间**: {doc.parse_time}")
        lines.append("")
        
        lines.append("## 1. 实体级映射")
        lines.append("")
        
        if doc.source_tables:
            lines.append("| 源表 | 别名 | 中文名 | 目标表 | 关联条件 |")
            lines.append("|------|------|--------|--------|----------|")

            for m in doc.source_tables:
                source = f"{m.source_schema}.{m.source_table}" if m.source_schema else m.source_table
                target = f"{m.target_schema}.{m.target_table}" if m.target_schema else m.target_table
                alias = m.source_alias or '-'
                lines.append(f"| `{source}` | {alias} | {m.source_table_cn} | `{target}` | {m.join_condition or '-'} |")
        else:
            lines.append("无实体级映射数据")
        
        lines.append("")
        lines.append("## 2. 属性级映射")
        lines.append("")
        
        if doc.field_mappings:
            lines.append("| 目标字段 | 目标类型 | 目标中文名 | 来源表 | 来源字段 | 映射规则 | 转换逻辑 |")
            lines.append("|----------|----------|------------|--------|----------|----------|----------|")
            
            for m in doc.field_mappings:
                if m.source_alias:
                    source_display = m.source_alias
                elif m.source_schema:
                    source_display = f"{m.source_schema}.{m.source_table}"
                else:
                    source_display = m.source_table
                lines.append(
                    f"| `{m.target_column}` | {m.target_type} | {m.target_column_cn} | "
                    f"`{source_display}` | `{m.source_column}` | {m.mapping_rule} | {m.mapping_expression or '-'} |"
                )
        else:
            lines.append("无属性级映射数据")
        
        lines.append("")
        lines.append("## 3. 统计信息")
        lines.append("")
        lines.append(f"| 项目 | 数量 |")
        lines.append("|------|------|")
        lines.append(f"| 设计模式 | {doc.design_pattern} |")
        if doc.design_pattern == 'multi_scene_union':
            lines.append(f"| 场景数量 | {doc.scene_count} |")
        lines.append(f"| 源表数量 | {len(doc.source_tables)} |")
        lines.append(f"| 字段数量 | {len(doc.field_mappings)} |")
        
        mapping_rules = {}
        for m in doc.field_mappings:
            mapping_rules[m.mapping_rule] = mapping_rules.get(m.mapping_rule, 0) + 1
        
        for rule, count in mapping_rules.items():
            lines.append(f"| {rule}字段 | {count} |")
        
        if doc.field_statistics:
            lines.append(f"| 去重字段数 | {doc.field_statistics.get('unique_fields', '-')} |")
        
        lines.append("")
        lines.append("## 4. 调度配置")
        lines.append("")
        
        if doc.scheduling_config:
            sc = doc.scheduling_config
            lines.append("| 配置项 | 值 |")
            lines.append("|--------|-----|")
            if sc.project_name:
                lines.append(f"| 项目名称 | {sc.project_name} |")
            if sc.task_group:
                lines.append(f"| 任务组名称 | {sc.task_group} |")
            if sc.schedule_cycle:
                lines.append(f"| 调度周期 | {sc.schedule_cycle} |")
            if sc.owner:
                lines.append(f"| 责任人 | {sc.owner} |")
            
            has_scheduled_tables = any(m.schedule_task for m in doc.source_tables)
            if has_scheduled_tables:
                lines.append("")
                lines.append("### 源表调度任务映射")
                lines.append("")
                lines.append("| 源表 | 调度任务名称 | 执行路径 |")
                lines.append("|------|-------------|----------|")
                for m in doc.source_tables:
                    if m.schedule_task:
                        source = f"{m.source_schema}.{m.source_table}" if m.source_schema else m.source_table
                        lines.append(f"| `{source}` | {m.schedule_task} | {m.exec_path or '-'} |")
        else:
            lines.append("无调度配置")
        
        if doc.execution_platform_config:
            ep = doc.execution_platform_config
            lines.append("")
            lines.append("## 5. 执行平台配置")
            lines.append("")
            lines.append("| 配置项 | 值 |")
            lines.append("|--------|-----|")
            if ep.project_code:
                lines.append(f"| 项目编码 | {ep.project_code} |")
            if ep.project_cn_name:
                lines.append(f"| 项目中文名 | {ep.project_cn_name} |")
            if ep.project_en_name:
                lines.append(f"| 项目英文名 | {ep.project_en_name} |")
            if ep.sub_project_code:
                lines.append(f"| 子项目编码 | {ep.sub_project_code} |")
            if ep.sub_project_cn_name:
                lines.append(f"| 子项目中文名 | {ep.sub_project_cn_name} |")
            if ep.sub_project_en_name:
                lines.append(f"| 子项目英文名 | {ep.sub_project_en_name} |")
            if ep.data_source:
                lines.append(f"| 数据源 | {ep.data_source} |")
            if ep.business_owner:
                lines.append(f"| 业务责任人 | {ep.business_owner} |")

        if doc.design_config:
            dc = doc.design_config
            lines.append("")
            lines.append("## 6. 设计配置")
            lines.append("")
            lines.append("| 配置项 | 值 |")
            lines.append("|--------|-----|")
            lines.append(f"| 封装视图 | {'是' if dc.wrap_view else '否'} |")
            if dc.target_grain:
                lines.append(f"| 目标表粒度 | {dc.target_grain} |")
            if dc.write_strategy:
                lines.append(f"| 写入策略 | {dc.write_strategy} |")
            if dc.incremental_key:
                lines.append(f"| 增量键 | {dc.incremental_key} |")

        if doc.data_flow:
            lines.append("")
            lines.append("## 7. 数据处理步骤")
            lines.append("")
            for group in doc.data_flow.groups:
                lines.append(f"### {group['name']}")
                lines.append("")
                lines.append("| 步骤 | 说明 |")
                lines.append("|------|------|")
                for s in group['steps']:
                    lines.append(f"| {s['step']} | {s['description']} |")
                lines.append("")

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"Markdown 已导出: {filepath}")
    
    @staticmethod
    def to_summary(doc: MappingDocument) -> str:
        lines = []
        lines.append(f"目标表: {doc.target_schema}.{doc.target_table} ({doc.target_table_cn})")
        if doc.design_pattern == 'multi_scene_union':
            lines.append(f"设计模式: 多场景UNION ({doc.scene_count}个场景)")
        lines.append(f"源表数量: {len(doc.source_tables)}")
        lines.append(f"字段数量: {len(doc.field_mappings)}")
        if doc.field_statistics:
            lines.append(f"去重字段数: {doc.field_statistics.get('unique_fields', '-')}")
        
        mapping_rules = {}
        for m in doc.field_mappings:
            mapping_rules[m.mapping_rule] = mapping_rules.get(m.mapping_rule, 0) + 1
        
        lines.append("映射规则分布:")
        for rule, count in mapping_rules.items():
            lines.append(f"  - {rule}: {count}")
        
        if doc.scheduling_config:
            sc = doc.scheduling_config
            lines.append(f"调度配置: 项目={sc.project_name}, 任务组={sc.task_group}, 周期={sc.schedule_cycle}, 责任人={sc.owner or '-'}")
            has_scheduled = any(m.schedule_task for m in doc.source_tables)
            if has_scheduled:
                lines.append("源表调度任务:")
                for m in doc.source_tables:
                    if m.schedule_task:
                        if m.source_alias:
                            source_display = m.source_alias
                        elif m.source_schema:
                            source_display = f"{m.source_schema}.{m.source_table}"
                        else:
                            source_display = m.source_table
                        lines.append(f"  - {source_display}: {m.schedule_task}" + (f" ({m.exec_path})" if m.exec_path else ""))
        
        if doc.execution_platform_config:
            ep = doc.execution_platform_config
            lines.append(f"执行平台配置: 项目编码={ep.project_code}, 子项目编码={ep.sub_project_code}, 数据源={ep.data_source}")

        if doc.design_config and doc.design_config.wrap_view:
            lines.append(f"封装视图: 是")

        if doc.design_config:
            dc = doc.design_config
            if dc.target_grain:
                lines.append(f"目标表粒度: {dc.target_grain}")
            if dc.write_strategy:
                lines.append(f"写入策略: {dc.write_strategy}")
            if dc.incremental_key:
                lines.append(f"增量键: {dc.incremental_key}")

        if doc.data_flow:
            lines.append(f"数据处理步骤: {len(doc.data_flow.groups)} 个步骤组")
            for group in doc.data_flow.groups:
                lines.append(f"  - {group['name']}: {len(group['steps'])} 个步骤")

        return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='ETL Mapping Excel 解析工具')
    parser.add_argument('--input', '-i', required=True, help='输入 Excel 文件路径')
    parser.add_argument('--output', '-o', required=True,
                        help='输出目录（自动创建 {目标表名}/01_input/ 子目录）或文件路径')
    parser.add_argument('--format', '-f', choices=['json', 'markdown', 'both'], 
                        default='both', help='输出格式 (json/markdown/both)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"文件不存在: {args.input}")
        return 1
    
    excel_parser = ExcelMappingParser(args.input)
    
    if not excel_parser.load():
        print("加载 Excel 文件失败")
        return 1
    
    doc = excel_parser.parse()
    
    output_path = Path(args.output)
    
    # 判断 --output 是文件路径还是目录
    is_file_path = output_path.suffix in ('.json', '.md')
    
    if is_file_path:
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_table = doc.target_table or 'unknown_target'
        base = output_path.parent if output_path.name == '01_input' else output_path
        output_dir = base / target_table / '01_input'
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"目标表: {target_table}")
        print(f"输出目录: {output_dir}")
        print()
    
    if args.format in ['json', 'both']:
        if is_file_path and output_path.suffix == '.json':
            json_path = str(output_path)
        else:
            json_path = str(output_dir / 'mapping.json')
        MappingExporter.to_json(doc, json_path)
    
    if args.format in ['markdown', 'both']:
        if is_file_path and output_path.suffix == '.md':
            md_path = str(output_path)
        else:
            md_path = str(output_dir / 'mapping.md')
        MappingExporter.to_markdown(doc, md_path)
    
    print(MappingExporter.to_summary(doc))
    
    if excel_parser._write_diagnostics(str(output_dir)):
        diag_path = os.path.join(str(output_dir), 'parse_diagnostics.md')
        print(f"\n⚠️ 解析发现问题，诊断报告已生成: {diag_path}")
    
    return 0


if __name__ == '__main__':
    exit(main())
