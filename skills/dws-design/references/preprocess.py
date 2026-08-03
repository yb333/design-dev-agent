#!/usr/bin/env python3
"""
输入预处理: mapping.xlsx + RS.md -> rs_input.json

合并了 Excel 解析 (原 excel_parser.py) + RS 表格提取 + 预检校验。
"""

import os
import re
import sys
import json
import argparse
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# ============================================================
# Excel Mapping 解析器
# ============================================================

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
    remark: str = ''
    source_column_cn: str = ''


class ExcelMappingParser:
    """Excel Mapping 解析器"""

    # 标准 sheet 名称
    ENTITY_SHEET_NAMES = ['实体级mapping', '实体级', 'entity', 'Entity']
    ATTRIBUTE_SHEET_NAMES = ['属性级mapping', '属性级', 'attribute', 'Attribute']
    SCHEDULE_SHEET_NAMES = ['调度配置', 'scheduling', 'schedule']
    EXEC_PLATFORM_SHEET_NAMES = ['执行平台配置', 'execution_platform', 'execution']
    DESIGN_CONFIG_SHEET_NAMES = ['设计配置', 'design_config']
    DATA_FLOW_SHEET_NAMES = ['数据处理步骤', 'data_flow', 'DataFlow']

    # 实体级 mapping 列名映射（按 mapping模板.xlsx 权威列名，不做模糊匹配）
    ENTITY_COLUMN_MAP = {
        '源表schema': 'source_schema',
        '源表物理表名': 'source_table',
        '源表中文名': 'source_table_cn',
        '源表别名': 'source_alias',
        '目标表逻辑schema': 'target_schema',
        '目标表中文名': 'target_table_cn',
        '目标表物理名称': 'target_table',
        '关联&限定条件': 'join_condition',
        '备注': 'remark',
        '分组': 'scene_group',
    }
    
    # 属性级 mapping 列名映射（按 mapping模板.xlsx 权威列名，不做模糊匹配）
    ATTRIBUTE_COLUMN_MAP = {
        '源Schema': 'source_schema',
        '源表物理表名': 'source_table',
        '源表物理表别名': 'source_alias',
        '源表字段名': 'source_column',
        '源表字段中文名': 'source_column_cn',
        '源表字段类型': 'source_type',
        '映射规则': 'mapping_rule',
        '映射表达式': 'mapping_expression',
        '目标字段名': 'target_column',
        '目标字段中文名': 'target_column_cn',
        '目标字段类型': 'target_type',
        '备注': 'remark',
        '分组': 'scene_group',
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
                        'message': f'Sheet "{sheet}" 未被识别, 建议使用标准名称: 实体级mapping, 属性级mapping, 调度配置, 执行平台配置, 设计配置',
                    })
            
            if self.entity_df is None and self.attribute_df is None:
                self.diagnostics.append({
                    'type': 'sheet_missing_critical',
                    'sheet': '',
                    'message': '未找到实体级mapping或属性级mapping sheet, 无法解析',
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
                    'message': f'第 {row_idx + 2} 行解析失败: {e}, 请检查该行数据格式',
                })
        
        return mappings
    
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
                    source_column_cn=self._safe_str(row.get('source_column_cn', '')),
                    mapping_rule=self._safe_str(row.get('mapping_rule', '直取')),
                    mapping_expression=self._safe_str(row.get('mapping_expression', '')),
                    target_column=self._safe_str(row.get('target_column', '')),
                    target_column_cn=self._safe_str(row.get('target_column_cn', '')),
                    target_type=self._safe_str(row.get('target_type', '')),
                    source_alias=self._safe_str(row.get('source_alias', '')),
                    scene_group=self._safe_str(row.get('scene_group', '')),
                    remark=self._safe_str(row.get('remark', ''))
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
                            source_column_cn=mapping.source_column_cn,
                            mapping_rule=mapping.mapping_rule,
                            mapping_expression=mapping.mapping_expression,
                            target_column=mapping.target_column,
                            target_column_cn=mapping.target_column_cn,
                            target_type=mapping.target_type,
                            source_alias=mapping.source_alias,
                            scene_group=mapping.scene_group,
                            remark=mapping.remark
                        )
                
                if mapping.target_column:
                    mappings.append(mapping)
            except Exception as e:
                self.diagnostics.append({
                    'type': 'row_parse_error',
                    'sheet': '属性级mapping',
                    'message': f'第 {row_idx + 2} 行解析失败: {e}, 请检查该行数据格式',
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
                'message': f'实体级 mapping 的「分组」列包含占位值 {bad_entity_groups}, '
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
                    'message': f'属性级 mapping 存在实体级未定义的分组: {orphan_groups}, '
                               f'实体级已有分组: {valid_entity_groups}。'
                               f'请在实体级 mapping 补充对应的源表行, 或修改属性级的分组名称',
                })

    def _detect_design_pattern(self, source_tables: List[EntityMapping]) -> tuple:
        scenes = set()
        
        # 优先从 scene_group 字段提取(显式分组列)
        for s in source_tables:
            if s.scene_group:
                group = s.scene_group.strip()
                # 提取分组中的数字编号
                match = re.search(r'(\d+)', group)
                if match:
                    scenes.add(int(match.group(1)))
        
        # 补充: 从 remark 中提取(兼容旧格式)
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
                        'message': f'列 "{col}" 模糊匹配到 "{best_key}"(相似度: {score:.0%})',
                    })

            if best_key is None:
                continue

            target = column_map[best_key]

            # 防重复: 同一个 target 不允许被多列映射
            if target in used_targets:
                self.diagnostics.append({
                    'type': 'duplicate_column_mapping',
                    'sheet': '',
                    'message': f'列 "{col}" 映射到 "{target}" 失败: 已有其他列映射到该字段, '
                               f'请检查 Excel 中是否存在重复或含义重叠的列(如同时存在"源字段名"和"源表字段名")',
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
                        'message': f'{sheet_label}缺少必填列 "{req_field}", 请检查列名是否正确(当前列名: {list(df.columns)})',
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
        """安全转换为字符串, 防御 Series/NaN/None 等异常类型"""
        # 防御: 如果 value 是 pandas Series(由重复列名等导致), 取第一个非 NaN 值
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
        """预处理列名: strip 空白/尾部*, 全角->半角"""
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
        
        匹配模式: 
        - "从 dwd_order_detail_f 按xxx汇总..."
        - "从 dwd_review_f 按xxx统计..."
        - "从 dim_user_f 关联..."
        - "从dwd_xxx按..."(无空格)
        
        Returns:
            Dict with 'schema' and 'table', or None if no match found
        """
        # 常见表名模式: schema.table 或 table
        # 匹配: 从 dwd_xxx / dim_xxx / ods_xxx 等开头
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
                    # 只有表名, 使用默认 schema 或从 source_tables 推断
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

# ============================================================
# RS.md 表格解析
# ============================================================


def parse_mapping(xlsx_path: str) -> dict[str, Any]:
    """解析 mapping.xlsx, 返回原始 dict(含 source_tables + field_mappings + 目标表信息)"""
    parser = ExcelMappingParser(xlsx_path)
    if not parser.load():
        raise RuntimeError(f"mapping.xlsx 加载失败: {xlsx_path}")
    entity_mappings = parser.parse_entity_mapping()
    attribute_mappings = parser.parse_attribute_mapping()

    # 从实体级 mapping 提取目标表信息
    target_schema = ""
    target_table = ""
    target_table_cn = ""
    if entity_mappings:
        first = entity_mappings[0]
        target_schema = first.target_schema
        target_table = first.target_table
        target_table_cn = first.target_table_cn

    return {
        "target_schema": target_schema,
        "target_table": target_table,
        "target_table_cn": target_table_cn,
        "source_tables": [asdict(m) for m in entity_mappings],
        "field_mappings": [asdict(m) for m in attribute_mappings],
    }


# ============================================================
# RS.md markdown 表格解析
# RS 是 BA 写的纯 markdown 文档(有固定模板)。
# 按章节标题定位表格 + 按表头列名匹配提取, 不依赖 YAML 标记块。
# ============================================================

# RS 各章节的标题关键词 -> 用于定位
RS_SECTION_KEYWORDS = {
    "asset": ["资产基本信息"],
    "sched": ["L07", "初始化及调度"],
    "upstream": ["湖表调度"],
    "dq": ["L06", "数据质量检查规则"],
}

# 资产基本信息表格: 表头列名 -> rs_input 字段名
ASSET_HEADER_MAP = {
    "SCHEMA": "target_full",       # 匹配 "资产 SCHEMA.接口视图"
    "资产描述": "description",
    "业务对象": "business_object",
    "逻辑数据实体": "grain",
    "owner 部门": "owner_dept",    # 匹配 "数据 owner 部门"
    "owner 人员": "owner_person",  # 匹配 "数据 owner 人员"
    "重点资产": "is_key_asset",
    "消费情况": "consumption",
}

# 调度配置表格: 表头列名 -> rs_input 字段名
SCHED_HEADER_MAP = {
    "调度方案": "strategy",
    "调度频率": "frequency",
    "调度完成时间要求": "sla",
    "初始化时间范围": "init_time_range",
    "增量识别方式": "incremental_key",
}

# 湖表调度表格: 表头列名 -> upstream 字段名
UPSTREAM_HEADER_MAP = {
    "湖表": "table",
    "任务名": "task",
    "环境": "env",
    "应用": "app",
    "项目": "project",
    "任务组": "group",
}

# DQ 规则表格: 表头列名 -> dq 字段名
DQ_HEADER_MAP = {
    "检查范围": "scope",
    "检查类型": "check_type",
    "规则名称": "rule_name",
    "规则描述": "rule_desc",
}


def _find_section(content: str, keywords: list[str]) -> str:
    """按标题关键词或加粗文字定位章节, 返回章节内容到下一个同级标记。
    支持两种定位: 
    - markdown 标题(### xxx)
    - 加粗文字(**xxx**)—— RS 模板里 L01-L09 用加粗而非标题
    """
    lines = content.split("\n")
    in_section = False
    match_level = 0       # 匹配到的标题级别(0=加粗定位)
    result: list[str] = []

    for line in lines:
        stripped = line.strip()

        if not in_section:
            # 查找章节起点
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                title = stripped.lstrip("# ").strip()
                if any(kw in title for kw in keywords):
                    in_section = True
                    match_level = level
                    continue
            elif stripped.startswith("**") and stripped.endswith("**") and stripped.count("**") == 2:
                bold_text = stripped.strip("*").strip()
                if any(kw in bold_text for kw in keywords):
                    in_section = True
                    match_level = 0  # 加粗定位
                    continue
        else:
            # 在章节内, 检查结束条件
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                # 标题定位的章节: 遇到同级或更高级标题结束
                if match_level > 0 and level <= match_level:
                    break
                # 加粗定位的章节: 遇到三级及以上标题结束
                if match_level == 0 and level <= 3:
                    break
            elif stripped.startswith("**") and stripped.endswith("**") and stripped.count("**") == 2:
                bold_text = stripped.strip("*").strip()
                # 遇到另一个 Lxx 或湖表标记时结束
                if bold_text.startswith("L0") or bold_text.startswith("湖表"):
                    break
            result.append(line)

    return "\n".join(result)


def _parse_md_table(table_text: str) -> tuple[list[str], list[list[str]]]:
    """解析 markdown 表格, 返回 (表头列表, 数据行列表)。"""
    lines = table_text.strip().split("\n")
    headers: list[str] = []
    rows: list[list[str]] = []

    for line in lines:
        line = line.strip()
        if not line or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        # 去掉首尾空(| 分割产生的空串)
        cells = [c for c in cells if c != "" or True]
        cells = [c for c in line.split("|")]
        cells = cells[1:-1] if len(cells) >= 2 else cells  # 去掉首尾 |
        cells = [c.strip() for c in cells]

        # 跳过分隔行(|---|---|)
        if all(re.match(r"^[-:]+$", c) for c in cells if c):
            continue

        if not headers:
            headers = cells
        else:
            rows.append(cells)

    return headers, rows


def _extract_kv_table(section: str, header_map: dict[str, str]) -> dict[str, str]:
    """从章节里提取键值表格(| 属性 | 内容 | 格式), 按表头列名匹配。"""
    headers, rows = _parse_md_table(section)
    if not headers or not rows:
        return {}

    result: dict[str, str] = {}
    # 找到"内容"列的索引(通常是第二列)
    value_col = 1 if len(headers) >= 2 else 0
    key_col = 0

    for row in rows:
        if len(row) <= key_col:
            continue
        key_text = row[key_col].strip()
        value_text = row[value_col].strip() if len(row) > value_col else ""

        # 模糊匹配表头
        for rs_key, target_key in header_map.items():
            if rs_key in key_text or key_text in rs_key:
                result[target_key] = value_text
                break

    return result


def _extract_list_table(section: str, header_map: dict[str, str]) -> list[dict[str, str]]:
    """从章节里提取列表表格(多行数据), 按表头列名匹配。"""
    headers, rows = _parse_md_table(section)
    if not headers or not rows:
        return []

    # 建立列名 -> 索引的映射(模糊匹配)
    col_map: dict[str, int] = {}
    for rs_key, target_key in header_map.items():
        for i, h in enumerate(headers):
            if rs_key in h or h in rs_key:
                col_map[target_key] = i
                break

    result: list[dict[str, str]] = []
    for row in rows:
        item: dict[str, str] = {}
        for target_key, col_idx in col_map.items():
            item[target_key] = row[col_idx].strip() if len(row) > col_idx else ""
        if any(v for v in item.values()):  # 至少有一个非空值
            result.append(item)

    return result


def extract_rs_data(rs_path: str) -> dict[str, Any]:
    """从 RS.md 的 markdown 表格提取结构化数据。
    必填项缺失->error；非必填项缺失->warning+容错为空。
    """
    content = Path(rs_path).read_text(encoding="utf-8")
    rs_data: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []

    # 1. 资产基本信息(必填)
    section = _find_section(content, RS_SECTION_KEYWORDS["asset"])
    asset = _extract_kv_table(section, ASSET_HEADER_MAP)
    if asset:
        target_full = asset.pop("target_full", "")
        if target_full and "." in target_full:
            parts = target_full.split(".")
            asset.setdefault("schema", parts[0])
            asset.setdefault("table", ".".join(parts[1:]))
        rs_data["meta"] = asset
    else:
        errors.append("资产基本信息表格未找到或为空(必填)")

    # 2. 调度配置(非必填, 容错为空)
    section = _find_section(content, RS_SECTION_KEYWORDS["sched"])
    sched = _extract_kv_table(section, SCHED_HEADER_MAP)
    if sched:
        rs_data["schedule"] = sched
    else:
        warnings.append("调度配置未找到(非必填, 使用默认值)")
        rs_data["schedule"] = {}

    # 3. 湖表调度(非必填, 容错为空列表)
    section = _find_section(content, RS_SECTION_KEYWORDS["upstream"])
    upstream = _extract_list_table(section, UPSTREAM_HEADER_MAP)
    rs_data["schedule"]["upstream"] = upstream if upstream else []
    if not upstream:
        warnings.append("湖表调度信息未找到(非必填)")

    # 4. DQ 规则(可选, 容错为空列表)
    section = _find_section(content, RS_SECTION_KEYWORDS["dq"])
    dq = _extract_list_table(section, DQ_HEADER_MAP)
    rs_data["dq_requirements"] = dq if dq else []
    if not dq:
        warnings.append("DQ 规则未找到(可选)")

    rs_data["_extract_errors"] = errors
    rs_data["_extract_warnings"] = warnings
    return rs_data


# ============================================================
# mapping 数据精简(去掉已移到 RS 的字段)
# ============================================================

# source_tables 里要删除的字段(已移到 RS @upstream)
SOURCE_TABLE_DROP_FIELDS = {"schedule_task", "exec_path", "dep_job_params"}

# field_mappings 里映射规则字段名统一
FIELD_MAPPING_RULE_MAP = {
    "mapping_rule": "transform_rule",  # 旧名 -> 新名
    "mapping_expression": "transform_detail",
}


def slim_mapping_data(mapping_raw: dict[str, Any]) -> dict[str, Any]:
    """精简 mapping 数据: 去掉已移到 RS 的字段, 统一字段名。"""
    # source_tables 精简
    source_tables = []
    for st in mapping_raw.get("source_tables", []):
        slim_st = {k: v for k, v in st.items() if k not in SOURCE_TABLE_DROP_FIELDS}
        source_tables.append(slim_st)

    # field_mappings 精简 + 字段名统一
    field_mappings = []
    for fm in mapping_raw.get("field_mappings", []):
        slim_fm = {}
        for k, v in fm.items():
            new_key = FIELD_MAPPING_RULE_MAP.get(k, k)
            slim_fm[new_key] = v
        field_mappings.append(slim_fm)

    return {
        "source_tables": source_tables,
        "field_mappings": field_mappings,
    }


# ============================================================
# 合并 mapping + RS -> rs_input.json
# ============================================================

def build_rs_input(mapping_raw: dict[str, Any], rs_data: dict[str, Any]) -> dict[str, Any]:
    """合并 mapping 数据和 RS 数据, 产出 rs_input.json 结构。"""
    slim_mapping = slim_mapping_data(mapping_raw)

    # 从 mapping 提取目标表基本信息
    target_schema = mapping_raw.get("target_schema", "")
    target_table = mapping_raw.get("target_table", "")
    target_table_cn = mapping_raw.get("target_table_cn", "")

    # 从 RS @asset 提取目标表信息(RS 优先)
    rs_meta = rs_data.get("meta", {})
    rs_target = rs_meta.get("target", {}) if isinstance(rs_meta, dict) else {}

    rs_input: dict[str, Any] = {
        "meta": {
            "target": {
                "schema": rs_target.get("schema", target_schema),
                "table": rs_target.get("table", target_table),
                "cn": rs_target.get("cn", target_table_cn),
                "description": rs_meta.get("target", {}).get("description", "") if isinstance(rs_meta, dict) else "",
            },
            "owner": rs_meta.get("owner", {}) if isinstance(rs_meta, dict) else {},
            "grain": rs_meta.get("grain", "") if isinstance(rs_meta, dict) else "",
            "load_strategy": {
                "strategy": rs_data.get("schedule", {}).get("strategy", ""),
                "incremental_key": rs_data.get("schedule", {}).get("incremental_key", ""),
            },
        },
        "source_tables": slim_mapping["source_tables"],
        "field_mappings": slim_mapping["field_mappings"],
        "schedule": rs_data.get("schedule", {}),
        "data_flow_hint": rs_data.get("data_flow_hint", {}),
        "dq_requirements": rs_data.get("dq_requirements", []),
    }

    # 可选: 数据探索信息
    if "data_exploration" in rs_data:
        rs_input["data_exploration"] = rs_data["data_exploration"]

    return rs_input


# ============================================================
# 预检
# ============================================================

class PrecheckResult:
    def __init__(self):
        self.passed: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []

    @property
    def return_code(self) -> int:
        if self.errors:
            return 2  # INCOMPLETE
        if self.warnings:
            return 1  # WARNING
        return 0  # PASS

    def add_pass(self, msg: str):
        self.passed.append(msg)

    def add_warn(self, msg: str):
        self.warnings.append(msg)

    def add_error(self, msg: str):
        self.errors.append(msg)

    def summary(self) -> str:
        lines = [
            f"预检结果: {'PASS' if self.return_code == 0 else 'WARNING' if self.return_code == 1 else 'INCOMPLETE'}",
            f"  通过: {len(self.passed)}  警告: {len(self.warnings)}  错误: {len(self.errors)}",
        ]
        if self.warnings:
            lines.append("警告:")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
        if self.errors:
            lines.append("错误:")
            for e in self.errors:
                lines.append(f"  ✗ {e}")
        return "\n".join(lines)


def precheck(rs_input: dict[str, Any]) -> PrecheckResult:
    """预检 rs_input.json 完整性。"""
    result = PrecheckResult()

    # 1. 目标表基本信息
    target = rs_input.get("meta", {}).get("target", {})
    if not target.get("schema") or not target.get("table"):
        result.add_error("目标表 schema/table 缺失")
    else:
        result.add_pass(f"目标表: {target['schema']}.{target['table']}")

    # 2. 源表
    source_tables = rs_input.get("source_tables", [])
    if not source_tables:
        result.add_error("无源表(source_tables 为空)")
    else:
        result.add_pass(f"源表数: {len(source_tables)}")
        for st in source_tables:
            if not st.get("source_alias"):
                result.add_warn(f"源表 {st.get('source_table', '?')} 缺少别名(source_alias)")

    # 3. 字段映射(含映射规则交叉校验)
    field_mappings = rs_input.get("field_mappings", [])
    if not field_mappings:
        result.add_error("无字段映射(field_mappings 为空)")
    else:
        result.add_pass(f"字段映射数: {len(field_mappings)}")

        # 合法的映射规则类型
        VALID_RULES = {"直接复制", "数据加工", "赋值", "序列"}

        for fm in field_mappings:
            target_field = fm.get("target_column", "")
            if not target_field:
                result.add_error("存在无目标字段名的映射行")
                continue

            rule = (fm.get("transform_rule") or fm.get("mapping_rule") or "").strip()
            expr = (fm.get("transform_detail") or fm.get("mapping_expression") or "").strip()
            source_field = (fm.get("source_column") or "").strip()

            # 3a. 映射规则必须有值且合法
            if not rule:
                result.add_error(f"字段 {target_field} 缺少映射规则")
                continue
            if rule not in VALID_RULES:
                result.add_error(f"字段 {target_field} 的映射规则 '{rule}' 不合法(应为: 直接复制/数据加工/赋值/序列)")
                continue

            # 3b. 交叉校验: 规则类型 vs 映射表达式 vs 来源字段
            if rule == "直接复制":
                # 直接复制: 不该有加工表达式
                if expr and expr != "-":
                    result.add_warn(f"字段 {target_field} 是'直接复制'但填了映射表达式 '{expr[:30]}', 若有加工逻辑应改为'数据加工'")
                # 直接复制: 必须有来源字段
                if not source_field:
                    result.add_error(f"字段 {target_field} 是'直接复制'但缺少来源字段(source_column)")

            elif rule == "数据加工":
                # 数据加工: 必须有加工表达式
                if not expr or expr == "-":
                    result.add_error(f"字段 {target_field} 是'数据加工'但映射表达式为空(必须描述加工逻辑)")
                # 数据加工: 通常需要来源字段(除非是纯派生字段)
                if not source_field:
                    result.add_warn(f"字段 {target_field} 是'数据加工'但没有来源字段, 确认是否为纯派生字段")

            elif rule == "赋值":
                # 赋值: 必须有赋值表达式(说明赋什么值)
                if not expr or expr == "-":
                    result.add_error(f"字段 {target_field} 是'赋值'但映射表达式为空(必须说明赋什么值, 如 'N' 或 ${{P_CYCLE_ID}})")
                # 赋值: 不需要来源字段(正常)

            elif rule == "序列":
                # 序列: 极少见, 标记一下
                result.add_pass(f"字段 {target_field} 是'序列'类型(自增序列, 特殊处理)")

    # 4. 目标字段重复检查
    seen_fields: dict[str, int] = {}
    for fm in field_mappings:
        tf = fm.get("target_column", "")
        if tf:
            seen_fields[tf] = seen_fields.get(tf, 0) + 1
    for field, count in seen_fields.items():
        if count > 1:
            result.add_error(f"目标字段 '{field}' 重复出现 {count} 次")

    # 5. 调度信息(来自 RS)
    schedule = rs_input.get("schedule", {})
    if not schedule.get("frequency"):
        result.add_warn("调度频率缺失(RS L07 调度频率)")
    if not schedule.get("upstream"):
        result.add_warn("上游调度任务缺失(RS L07 湖表调度信息)")

    # 6. 别名一致性(属性级的别名必须在实体级存在)
    entity_aliases = {st.get("source_alias") for st in source_tables if st.get("source_alias")}
    for fm in field_mappings:
        fm_alias = fm.get("source_alias", "")
        if fm_alias and fm_alias not in entity_aliases:
            result.add_error(f"字段 {fm.get('target_column', '?')} 的来源别名 '{fm_alias}' 在实体级 mapping 中不存在")

    # 7. 映射表达式模糊术语检查
    biz_terms = ["等等", "之类", "相关", "之类的", "等等等"]
    for fm in field_mappings:
        expr = fm.get("transform_detail") or fm.get("mapping_expression") or ""
        for term in biz_terms:
            if term in str(expr):
                result.add_warn(f"字段 {fm.get('target_column', '?')} 的映射表达式含模糊术语: '{term}'")

    return result


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="输入预处理: mapping.xlsx + RS.md -> rs_input.json (只做转换)")
    parser.add_argument("--mapping", required=True, help="mapping.xlsx 路径")
    parser.add_argument("--rs", help="RS.md 路径(可选, 无则只解析 mapping)")
    parser.add_argument("--output", required=True, help="rs_input.json 输出路径")
    args = parser.parse_args()

    # 1. 解析 mapping.xlsx
    print(f"解析 mapping: {args.mapping}")
    try:
        mapping_raw = parse_mapping(args.mapping)
    except Exception as e:
        print(f"错误: mapping 解析失败: {e}", file=sys.stderr)
        sys.exit(1)
    if not mapping_raw.get("source_tables"):
        print("错误: mapping 解析失败", file=sys.stderr)
        sys.exit(1)
    print(f"  源表数: {len(mapping_raw.get('source_tables', []))}")
    print(f"  字段映射数: {len(mapping_raw.get('field_mappings', []))}")

    # 2. 提取 RS(如果有)
    rs_data = {}
    if args.rs:
        rs_path = Path(args.rs)
        if rs_path.exists():
            print(f"提取 RS: {args.rs}")
            rs_data = extract_rs_data(str(rs_path))
            print(f"  提取的 RS 数据块: {list(rs_data.keys())}")
        else:
            print(f"警告: RS 文件不存在: {args.rs}", file=sys.stderr)

    # 3. 合并
    rs_input = build_rs_input(mapping_raw, rs_data)

    # 4. 写出
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rs_input, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"产出 rs_input.json: {output_path}")


if __name__ == "__main__":
    main()
