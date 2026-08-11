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
    # ★ 实体级和属性级的来源表别名统一叫"源表别名"（不区分"物理"前缀，减少 BA 困惑）
    ATTRIBUTE_COLUMN_MAP = {
        '源schema': 'source_schema',
        '源表物理表名': 'source_table',
        '源表别名': 'source_alias',
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
                    self.entity_df = pd.read_excel(xlsx, sheet_name=sheet, keep_default_na=False)
                    recognized_sheets.add(sheet)
                elif any(s in sheet_lower for s in ['属性级', 'attribute']):
                    self.attribute_df = pd.read_excel(xlsx, sheet_name=sheet, keep_default_na=False)
                    recognized_sheets.add(sheet)
                elif any(s in sheet_lower for s in [sn.lower() for sn in self.SCHEDULE_SHEET_NAMES]):
                    self.schedule_config_df = pd.read_excel(xlsx, sheet_name=sheet, keep_default_na=False)
                    recognized_sheets.add(sheet)
                elif any(s in sheet_lower for s in [sn.lower() for sn in self.EXEC_PLATFORM_SHEET_NAMES]):
                    self.exec_platform_config_df = pd.read_excel(xlsx, sheet_name=sheet, keep_default_na=False)
                    recognized_sheets.add(sheet)
                elif any(s in sheet_lower for s in [sn.lower() for sn in self.DESIGN_CONFIG_SHEET_NAMES]):
                    self.design_config_df = pd.read_excel(xlsx, sheet_name=sheet, keep_default_na=False)
                    recognized_sheets.add(sheet)
                elif any(s in sheet_lower for s in [sn.lower() for sn in self.DATA_FLOW_SHEET_NAMES]):
                    self.data_flow_df = pd.read_excel(xlsx, sheet_name=sheet, keep_default_na=False)
                    recognized_sheets.add(sheet)

            # 多余的 sheet（不在标准名清单里的）静默跳过，不告警。
            # mapping 模板可能有各种辅助 sheet（说明页/备注页/模板自带页等），不影响产出。
            # 真正的问题（实体级+属性级都没有）由下面的 sheet_missing_critical 覆盖。
            # 这与列处理的"未匹配列静默跳过"逻辑一致。

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
                                 optional=['remark', 'scene_group', 'join_condition'])
        
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
                                 optional=['remark', 'scene_group', 'source_column_cn'])
        
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

        # 已知的非标准列（模板里的辅助列，不是数据列），静默忽略不报警告
        IGNORE_COLUMNS = {"序号", "备注", "说明", "note", "comment", "no", "index"}

        for col in df.columns:
            col_clean = self._clean_column_name(col)

            # 只精确匹配，不做子串/模糊匹配
            best_key = col_clean if col_clean in column_map else None

            if best_key is None:
                # 未匹配的列直接跳过，不报警告。
                # mapping 模板可能有各种辅助列（序号/备注/空列等），不影响产出。
                # 真正的问题（标准列缺失）由 column_missing 检查覆盖。
                continue

            target = column_map[best_key]

            # 防重复: 同一个 target 不允许被多列映射
            if target in used_targets:
                self.diagnostics.append({
                    'type': 'duplicate_column_mapping',
                    'sheet': '',
                    'message': f'列 "{col}" 映射到 "{target}" 失败: 已有其他列映射到该字段',
                })
                continue

            rename_dict[col] = target
            matched_keys.add(best_key)
            remaining_keys = [k for k in remaining_keys if k != best_key]
            used_targets.add(target)

        return df.rename(columns=rename_dict)
    
    def _check_column_match(self, df: pd.DataFrame, column_map: Dict[str, str], sheet_label: str,
                            required: Optional[List[str]] = None, optional: Optional[List[str]] = None):
        """校验 column_map 里的所有标准列是否都在 df 里匹配上了。

        ★ 任一标准列没匹配上 → 报 column_missing（不再只查 required）。
        optional 里的列（如备注/分组）缺失不报——它们是可选注释/条件性字段。
        """
        actual_cols = set()
        for col in df.columns:
            col_clean = self._clean_column_name(col)
            if col_clean in column_map:
                actual_cols.add(column_map[col_clean])

        # 可选列（缺失不报）
        optional_targets = set(optional or [])
        # 查所有标准列：column_map 的所有 target 字段都该匹配上（除可选列）
        # 构建反向映射（target → 期望的中文列名）用于报错信息
        target_to_cnname = {v: k for k, v in column_map.items()}
        for target_field, cn_name in target_to_cnname.items():
            if target_field in optional_targets:
                continue  # 可选列缺失不报
            if target_field not in actual_cols:
                self.diagnostics.append({
                    'type': 'column_missing',
                    'sheet': sheet_label,
                    'message': f'{sheet_label}缺少必要列（期望列名 "{cn_name}" 未匹配上），'
                               f'请检查列名拼写/是否多了空格（当前列名: {list(df.columns)}）',
                })
    
    def _write_diagnostics(self, output_dir: str) -> bool:
        if not self.diagnostics:
            return False
        
        os.makedirs(output_dir, exist_ok=True)
        lines = [f'# 解析诊断 — {len(self.diagnostics)} 个问题', '']
        
        col_issues = [d for d in self.diagnostics if d['type'] == 'column_missing']
        sheet_issues = [d for d in self.diagnostics if d['type'] in ('sheet_missing_critical',)]
        other_issues = [d for d in self.diagnostics if d['type'] not in ('column_missing', 'sheet_missing_critical')]
        
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
        """预处理列名: strip 空白/尾部*, 全角->半角, 英文统一小写"""
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
        s = s.lower()  # 英文统一小写，不区分 Schema/schema
        return s
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

    # 打印诊断信息（列名没匹配上等）
    if parser.diagnostics:
        for d in parser.diagnostics:
            print(f"  ⚠️ {d['type']}: {d['message']}")
        # column_missing 是结构性问题（列名错了整列数据丢失），阻断退出
        col_missing = [d for d in parser.diagnostics if d['type'] == 'column_missing']
        if col_missing:
            raise RuntimeError(
                f"mapping.xlsx 列名校验失败（{len(col_missing)} 个必要列未匹配上），"
                f"请修正列名后重跑。详见上方诊断信息。"
            )

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
    "explore": ["L01", "数据探索"],
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

# 增量表及增量字段表格: 表头列名 -> rs_input 字段名（RS L07 子段）
# 增量驱动表 + 增量字段，给 designer 做增量识别用
INCREMENTAL_HEADER_MAP = {
    "来源表": "source_table",
    "增量字段": "incremental_key",
}

# DQ 规则表格: 表头列名 -> dq 字段名
DQ_HEADER_MAP = {
    "检查范围": "scope",
    "检查类型": "check_type",
    "规则名称": "rule_name",
    "规则描述": "rule_desc",
}

# 数据探索 - 数据量级表格: 表头列名 -> 字段名
EXPLORE_VOLUME_HEADER_MAP = {
    "来源表": "table",
    "数据量": "volume",
    "字段个数": "field_count",
}

# 数据探索 - 空值率表格: 表头列名 -> 字段名
EXPLORE_NULL_HEADER_MAP = {
    "字段": "field",
    "空值率": "null_rate",
    "说明": "note",
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


def _find_bold_labeled_block(section: str, label: str) -> str:
    """从 section 里提取"加粗标签下、到下一个加粗标签止"的子块文本。

    RS 模板里 L07 同一段含三个表格（调度配置/增量表/湖表调度），后两者前面有
    加粗行（如 `**增量表及增量字段**`、`**湖表调度信息**：`）作为子段标记。
    本函数按 label 子串匹配加粗行，返回该行之后、下一个加粗行之前的内容。

    Args:
        section: _find_section 返回的整段文本。
        label: 要匹配的加粗文字子串（如 "增量表及增量字段"）。

    Returns:
        子块文本（不含加粗标记行）。找不到返回空串。
    """
    result: list[str] = []
    in_sub = False
    for line in section.split("\n"):
        stripped = line.strip()
        # 识别加粗标记行：**xxx** 形式（**xxx**：这种尾部带冒号的也算）
        # 用正则匹配，兼容尾部全角/半角冒号
        m = re.match(r"^\*\*(.+?)\*\*[：:]?\s*$", stripped)
        if m:
            bold_text = m.group(1).strip()
            if not in_sub:
                if label in bold_text:
                    in_sub = True
                continue  # 标签行本身不入结果
            else:
                # 已在子段内遇到下一个加粗标签 -> 子段结束
                break
        if in_sub:
            result.append(line)
    return "\n".join(result)


def _parse_incremental_tables(sched_section: str) -> list[dict[str, str]]:
    """解析 RS L07 的"增量表及增量字段"子段表格。

    返回 [{"source_table": "ods.ods_order_f", "incremental_key": "update_time"}, ...]。
    容错：
    - 子段不存在（全量资产 / 旧 RS）-> 空列表
    - 只有占位行（xxxx.xxxx | xxxx）-> 过滤掉
    - 行缺列 / 空行 -> 跳过
    """
    block = _find_bold_labeled_block(sched_section, "增量表及增量字段")
    if not block:
        return []
    rows = _extract_list_table(block, INCREMENTAL_HEADER_MAP)
    result: list[dict[str, str]] = []
    for item in rows:
        src = (item.get("source_table") or "").strip()
        key = (item.get("incremental_key") or "").strip()
        if not src or not key:
            continue
        # 过滤模板占位行（RS 模板示例行如 xxxx.xxxx | xxxx）
        if re.fullmatch(r"[xX.]+", src) and re.fullmatch(r"[xX]+", key):
            continue
        result.append({"source_table": src, "incremental_key": key})
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
    asset_section_found = bool(_find_section(content, RS_SECTION_KEYWORDS["asset"]))
    section = _find_section(content, RS_SECTION_KEYWORDS["asset"])
    asset = _extract_kv_table(section, ASSET_HEADER_MAP)
    if asset:
        target_full = asset.pop("target_full", "")
        if target_full and "." in target_full:
            parts = target_full.split(".")
            asset.setdefault("schema", parts[0])
            asset.setdefault("table", ".".join(parts[1:]))
        rs_data["meta"] = asset
        # 核心字段校验：段在且解析出内容，但 schema/table 没提取到
        # （源端表头写法变了导致"资产 SCHEMA.接口视图"没匹配上）
        if not asset.get("schema") and not asset.get("table"):
            errors.append(
                "资产基本信息段找到了，但目标表 schema/table 未提取到"
                "（检查 RS 的'资产 SCHEMA.接口视图'行写法是否标准）"
            )
    else:
        if asset_section_found:
            errors.append(
                "资产基本信息段找到了，但表格未解析出任何字段"
                "（检查 RS 表头格式：应为 | 属性 | 内容 |）"
            )
        else:
            errors.append("资产基本信息表格未找到(必填)")

    # 2. 调度配置(非必填, 容错为空)
    sched_section_found = bool(_find_section(content, RS_SECTION_KEYWORDS["sched"]))
    section = _find_section(content, RS_SECTION_KEYWORDS["sched"])
    sched = _extract_kv_table(section, SCHED_HEADER_MAP)
    if sched:
        rs_data["schedule"] = sched
    else:
        if sched_section_found:
            warnings.append(
                "调度配置段找到了，但表格未解析出任何字段"
                "（检查 RS 表头写法，如'调度方案'/'调度频率'等列名）"
            )
        else:
            warnings.append("调度配置未找到(非必填, 使用默认值)")
        rs_data["schedule"] = {}

    # 2b. 增量表及增量字段(RS L07 子段, 非必填, 容错为空列表)
    #     designer 拿这个做增量识别（哪些驱动表、用哪个字段做增量键）。
    #     全量资产的 RS 没有这段（或只有占位行），incremental_tables 为 []。
    incremental_tables = _parse_incremental_tables(section)
    rs_data["schedule"]["incremental_tables"] = incremental_tables

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

    # 5. 数据探索(可选, 容错为空)
    section = _find_section(content, RS_SECTION_KEYWORDS["explore"])
    data_exploration = {}
    if section:
        import re

        # 按子标题切分 section，分别提取两个表格
        # 数据量级子段：从"数据量级"到下一个加粗标题
        vol_section = ""
        null_section = ""
        lines_list = section.split("\n")
        current_sub = ""
        for line in lines_list:
            stripped = line.strip().strip("*").strip()
            if stripped == "数据量级：":
                current_sub = "vol"
                continue
            elif stripped == "核心字段空值率分析：":
                current_sub = "null"
                continue
            elif stripped.startswith("关联方式") or stripped.startswith("关联路径") or stripped.startswith("筛选条件") or stripped.startswith("数据发散说明"):
                current_sub = ""
                continue

            if current_sub == "vol":
                vol_section += line + "\n"
            elif current_sub == "null":
                null_section += line + "\n"

        # 数据量级表
        volume = _extract_list_table(vol_section, EXPLORE_VOLUME_HEADER_MAP)
        if volume:
            data_exploration["table_stats"] = volume

        # 空值率表
        null_rates = _extract_list_table(null_section, EXPLORE_NULL_HEADER_MAP)
        if null_rates:
            data_exploration["null_rates"] = null_rates

        # 数据发散说明
        div_match = re.search(r'数据发散说明[：:]\s*\*{0,2}(.*?)(?:\n\n|\n\*\*|\Z)', section, re.DOTALL)
        if div_match:
            data_exploration["divergence_note"] = div_match.group(1).strip()

    rs_data["data_exploration"] = data_exploration if data_exploration else {}
    if not data_exploration:
        warnings.append("数据探索信息未找到(可选)")

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

def validate_target_table(rs_schema: str, rs_table: str,
                          mapping_schema: str, mapping_table: str
                          ) -> Tuple[str, str, List[str], List[str]]:
    """校验目标表 schema/table 在 RS 和 mapping 之间的一致性（分级）。

    校验规则（schema 和 table 各自独立判定）：
    - 两边都没写 → 阻断 error（必须确认）
    - 两边都写了但不一致 → 阻断 error（必须确认）
    - 一边写了一边没写 → 告警 warning（互补，不阻断）
    - 两边都写了且一致 → 正常

    Args:
        rs_schema: RS @asset 提取的目标 schema。
        rs_table: RS @asset 提取的目标 table。
        mapping_schema: mapping 实体级的目标 schema。
        mapping_table: mapping 实体级的目标 table。

    Returns:
        (final_schema, final_table, errors, warnings)
        - final_schema/final_table: 互补后的最终值（RS 有用 RS 的，否则用 mapping 的）。
        - errors: 阻断级问题（非空表示必须人工确认，不应继续）。
        - warnings: 告警级问题（互补情况，不阻断）。
    """
    errors: List[str] = []
    warnings: List[str] = []

    # schema 校验（4 种情况）
    if not rs_schema and not mapping_schema:
        errors.append("目标表 schema：RS 和 mapping 都没写，无法确定 schema")
    elif rs_schema and mapping_schema and rs_schema != mapping_schema:
        errors.append(f"目标表 schema 不一致：RS='{rs_schema}', mapping='{mapping_schema}'")
    elif rs_schema and not mapping_schema:
        warnings.append(f"目标表 schema：mapping 没写 schema，用 RS 的 '{rs_schema}'")
    elif mapping_schema and not rs_schema:
        warnings.append(f"目标表 schema：RS 没写 schema，用 mapping 的 '{mapping_schema}'")

    # table 校验（4 种情况）
    if not rs_table and not mapping_table:
        errors.append("目标表名：RS 和 mapping 都没写，无法确定表名")
    elif rs_table and mapping_table and rs_table != mapping_table:
        errors.append(f"目标表名不一致：RS='{rs_table}', mapping='{mapping_table}'")
    elif rs_table and not mapping_table:
        warnings.append(f"目标表名：mapping 没写表名，用 RS 的 '{rs_table}'")
    elif mapping_table and not rs_table:
        warnings.append(f"目标表名：RS 没写表名，用 mapping 的 '{mapping_table}'")

    # 互补：RS 有用 RS 的，否则用 mapping 的
    final_schema = rs_schema or mapping_schema
    final_table = rs_table or mapping_table

    return final_schema, final_table, errors, warnings


def build_compact(rs_input: dict[str, Any]) -> dict[str, Any]:
    """从 field_mappings 生成分块紧凑视图（给 designer 读）。

    三段结构，各服务一种认知粒度：
    - tables：表级清单（哪些源表、规模、关联）——理解全貌
    - direct：直取/赋值按表分块——批量搬运字段扫一眼过
    - processed：加工字段逐个平铺——逐个拆解加工链（多表来源合并）

    跳过"在某场景被赋 NULL"的赋值字段（对 designer 是噪音），但保留
    null_in_scene 标记列表，让 designer 知道哪些字段在部分场景是 NULL。

    去噪：空 remark 不出 note、scene_group 不出现、与 source_column
    重复的 source_column_cn 不出现。
    """
    fms = rs_input.get("field_mappings", [])
    source_tables = rs_input.get("source_tables", [])

    # ① 表级清单
    table_list = []
    for st in source_tables:
        sch = st.get("source_schema", "")
        tbl = st.get("source_table", "")
        alias = st.get("source_alias", "")
        cnt = sum(1 for fm in fms
                  if fm.get("source_table") == tbl
                  and fm.get("source_alias", "") == alias)
        table_list.append({
            "schema": sch, "table": tbl, "alias": alias,
            "fields": cnt, "join": st.get("join_condition", ""),
        })

    # 增量驱动表（来自 RS L07 增量表段，给 designer 看增量识别方式）
    incremental_tables = rs_input.get("schedule", {}).get("incremental_tables", [])

    # ② 直取/赋值 按表分块；③ 加工平铺；NULL 赋值收集到标记
    direct_blocks: dict = {}
    proc_fields: list = []
    null_fields: list = []
    for fm in fms:
        rule = fm.get("transform_rule", "直接复制")
        # 兼容旧字段名 mapping_rule
        if not fm.get("transform_rule"):
            rule = fm.get("mapping_rule", "直接复制")
        detail = fm.get("transform_detail", "") or fm.get("mapping_expression", "")

        # NULL 赋值字段跳过（多场景里某场景无值的字段，对 designer 是噪音）
        is_null_assign = (rule == "赋值" and detail.strip().upper() in ("NULL", "'NULL'", "无", ""))
        if is_null_assign:
            null_fields.append(fm.get("target_column", ""))
            continue

        if rule in ("赋值", "直接复制"):
            key = (fm.get("source_schema", ""), fm.get("source_table", ""),
                   fm.get("source_alias", ""), rule)
            direct_blocks.setdefault(key, []).append(fm)
        elif rule == "数据加工":
            proc_fields.append(fm)
        else:
            # 未知规则归直取
            key = (fm.get("source_schema", ""), fm.get("source_table", ""),
                   fm.get("source_alias", ""), "直接复制")
            direct_blocks.setdefault(key, []).append(fm)

    direct_section = []
    for (sch, tbl, alias, rule), fields in direct_blocks.items():
        rows = []
        for f in fields:
            row = {"src": f.get("source_column", ""),
                   "tgt": f.get("target_column", ""),
                   "type": f.get("target_type", "")}
            remark = f.get("remark", "")
            if remark:
                row["note"] = remark
            if rule == "赋值":
                row["val"] = f.get("transform_detail", "") or f.get("mapping_expression", "")
            rows.append(row)
        direct_section.append({"schema": sch, "table": tbl, "alias": alias,
                               "rule": rule, "fields": rows})

    # ③ 加工字段：按 target_column 聚合（多表来源合并成一段）
    target_groups: dict = {}
    for f in proc_fields:
        target_groups.setdefault(f.get("target_column", ""), []).append(f)
    proc_section = []
    for target, fields in target_groups.items():
        f0 = fields[0]
        entry = {"tgt": target, "type": f0.get("target_type", "")}
        cn = f0.get("target_column_cn", "")
        if cn and cn != target:
            entry["cn"] = cn
        sources = [[f.get("source_schema", ""), f.get("source_table", ""),
                    f.get("source_alias", ""), f.get("source_column", "")]
                   for f in fields]
        entry["sources"] = sources if len(sources) > 1 else sources[0]
        detail = f0.get("transform_detail", "") or f0.get("mapping_expression", "")
        if detail and detail not in ("-", "无", ""):
            entry["logic"] = detail
        proc_section.append(entry)

    compact = {"tables": table_list, "direct": direct_section, "processed": proc_section}

    # 目标表信息（告知 designer：设计目标是 F 表，I 视图由 assemble_ddl 按 i_view 生成）
    meta_target = rs_input.get("meta", {}).get("target", {})
    f_table = meta_target.get("f_table", {})
    i_view = meta_target.get("i_view", {})
    if f_table or i_view:
        compact["target"] = {
            "f_table": f_table,
            "i_view": i_view,
            "说明": ("设计目标表是 F 表（_f 后缀）。design_decisions 的 target_table 填 F 表名。"
                     "I 视图是 F 表的固定镜像，由 assemble_ddl 按 meta.target.i_view 自动生成（i_view 为空则不建）。"),
        }

    if null_fields:
        compact["null_in_scene"] = sorted(set(null_fields))
    if incremental_tables:
        compact["incremental_tables"] = incremental_tables

    # DQ 需求（来自 RS L06，告知 designer 该不该产 DQ + 需要翻译的需求内容）
    # DQ 完全跟随 RS：有需求 designer 翻译产 dq_rules，无需求 dq_rules 留空
    dq_reqs = rs_input.get("dq_requirements", [])
    if dq_reqs:
        compact["dq"] = {
            "requirements": dq_reqs,
            "说明": ("RS 有 DQ 需求，designer 必须翻译成 coder 可执行的 DQ 规格写进 dq_rules。"
                     "scope/check_type/rule_name 跟 RS 保持一致（分类不变），"
                     "rule_desc 写技术口径（检查字段/条件/阈值/告警级），给 coder 写 SQL 用。"
                     "翻译后条数可增加（一条模糊需求可拆多条），但不应少于 RS。"),
        }
    else:
        compact["dq"] = {
            "requirements": [],
            "说明": "RS 无 DQ 需求（dq_requirements 为空）→ dq_rules 留空，不产 DQ（coder 不调，无 DQ 调度任务）。",
        }
    return compact


def _schedule_with_defaults(schedule: dict) -> dict:
    """给 schedule 补默认值（无RS模式下 RS 的段是空的）。

    无RS模式时 RS 没提供调度信息，这里给合理默认：
    - strategy: 全量调度
    - frequency: T+1
    - incremental_key: 不涉及（全量）
    - incremental_tables: []（无增量驱动表）
    - upstream: []（湖表调度空）

    RS 提供了的字段优先（不覆盖）。
    """
    defaults = {
        "strategy": "全量调度",
        "frequency": "T+1",
        "incremental_key": "不涉及",
        "incremental_tables": [],
        "upstream": [],
    }
    result = dict(defaults)
    result.update(schedule)  # RS 提供的覆盖默认
    return result


def build_rs_input(mapping_raw: dict[str, Any], rs_data: dict[str, Any]) -> dict[str, Any]:
    """合并 mapping 数据和 RS 数据, 产出 rs_input.json 结构。"""
    slim_mapping = slim_mapping_data(mapping_raw)

    # 从 mapping 提取目标表基本信息
    # mapping 标准写法：目标表物理名称写 I视图名（_i 结尾）
    # 从 _i 推导 _f（F表 = I视图去掉 _i 换成 _f）
    target_schema = mapping_raw.get("target_schema", "")
    target_table_raw = mapping_raw.get("target_table", "")  # 可能是 _i 或 _f
    target_table_cn = mapping_raw.get("target_table_cn", "")

    # 推导 f_table 和 i_view
    if target_table_raw.endswith("_i"):
        i_view_name = target_table_raw
        f_table_name = target_table_raw[:-2] + "_f"
    elif target_table_raw.endswith("_f"):
        f_table_name = target_table_raw
        i_view_name = target_table_raw[:-2] + "_i"
    else:
        # 没有标准后缀，用原名做 f_table，推导 i
        f_table_name = target_table_raw
        i_view_name = target_table_raw + "_i"

    # 从 RS @asset 提取目标表信息
    rs_meta = rs_data.get("meta", {})
    rs_target = rs_meta.get("target", {}) if isinstance(rs_meta, dict) else {}
    # RS 提取的 schema/table 在 meta 顶层（extract_rs_data 的输出格式）
    rs_schema = rs_meta.get("schema", "") or rs_target.get("schema", "")
    rs_table = rs_meta.get("table", "") or rs_target.get("table", "")

    # 校验目标表 schema/table（分级：阻断 vs 告警），并得到互补后的最终值
    final_schema, final_table, fatal_errors, warnings = validate_target_table(
        rs_schema, rs_table, target_schema, target_table_raw
    )
    final_cn = rs_meta.get("cn", "") or rs_target.get("cn", "") or target_table_cn

    # 告警打印到 stdout（不阻断）
    for w in warnings:
        print(f"  ⚠️ 告警: {w}")

    if fatal_errors:
        print(f"\n❌ 目标表信息校验失败，请确认正确值：", file=sys.stderr)
        for e in fatal_errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    # 推导 f_table 和 i_view（用最终表名）
    if final_table.endswith("_i"):
        i_view_name = final_table
        f_table_name = final_table[:-2] + "_f"
    elif final_table.endswith("_f"):
        f_table_name = final_table
        i_view_name = final_table[:-2] + "_i"
    else:
        f_table_name = final_table
        i_view_name = final_table + "_i"

    rs_input: dict[str, Any] = {
        "meta": {
            "target": {
                "f_table": {"schema": final_schema, "table": f_table_name, "cn": final_cn},
                "i_view": {"schema": final_schema, "table": i_view_name, "cn": final_cn},
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
        "schedule": _schedule_with_defaults(rs_data.get("schedule", {})),
        "data_flow_hint": rs_data.get("data_flow_hint", {}),
        "dq_requirements": rs_data.get("dq_requirements", []),
    }

    # 可选: 数据探索信息
    if "data_exploration" in rs_data:
        rs_input["data_exploration"] = rs_data["data_exploration"]

    # 无RS模式标记：rs_data 为空（preprocess 没 --rs 或文件不存在）
    # precheck 据此区分"调度信息缺失因为无RS" vs "RS写了但没解析出来"
    if not rs_data:
        rs_input["_no_rs_mode"] = True

    return rs_input



# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="输入预处理: mapping.xlsx + RS.md -> rs_input.json (只做转换)")
    parser.add_argument("--mapping", required=True, help="mapping.xlsx 路径")
    parser.add_argument("--rs", help="RS.md 路径(可选, 无则只解析 mapping)")
    parser.add_argument("--output", required=True, help="rs_input.json 输出路径")
    parser.add_argument("--view-output", default="",
                        help="rs_input_view.json 输出路径（compact 视图，给 designer 读）。"
                             "默认 output 同目录的 rs_input_view.json")
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
    if not mapping_raw.get("target_schema"):
        print(f"  ⚠️ 目标表 schema 未从 mapping 提取到（检查实体级'目标表逻辑schema'列名和数据）")
    if not mapping_raw.get("target_table"):
        print(f"  ⚠️ 目标表名未从 mapping 提取到（检查实体级'目标表物理名称'列名和数据）")

    # 2. 提取 RS(可选——无RS时进入"无RS模式"，用默认值兜底)
    rs_data = {}
    no_rs_mode = True
    if args.rs:
        rs_path = Path(args.rs)
        if rs_path.exists():
            print(f"提取 RS: {args.rs}")
            rs_data = extract_rs_data(str(rs_path))
            print(f"  提取的 RS 数据块: {list(rs_data.keys())}")
            # RS 解析的 errors/warnings 必须报告（之前静默吞掉）
            rs_errors = rs_data.pop("_extract_errors", [])
            rs_warnings = rs_data.pop("_extract_warnings", [])
            for w in rs_warnings:
                print(f"  ⚠️ RS 解析告警: {w}")
            if rs_errors:
                print(f"\n❌ RS 解析错误（必填项缺失）:", file=sys.stderr)
                for e in rs_errors:
                    print(f"  - {e}", file=sys.stderr)
                # 必填项缺失不应继续——rs_data 关键段是空的，下游会出错
                sys.exit(1)
            no_rs_mode = False
        else:
            print(f"⚠️ RS 文件不存在: {args.rs}，进入无RS模式", file=sys.stderr)

    if no_rs_mode:
        # 无RS模式：mapping 独立驱动。以下信息用默认值兜底。
        print("⚠️ 无RS模式：以下信息将用默认值（后续可补充RS再重跑）:")
        print("     调度方案 → 全量调度(默认)")
        print("     调度频率 → T+1(默认)")
        print("     增量识别 → 不涉及(全量)")
        print("     DQ规则   → 空(用标准检查:主键唯一/非空/行数 兜底)")
        print("     湖表调度 → 空(export时上游依赖需手补)")
        print("     目标表schema/table → 用 mapping 实体级的")

    # 3. 合并
    rs_input = build_rs_input(mapping_raw, rs_data)

    # 4. 写出
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rs_input, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"产出 rs_input.json: {output_path}")

    # 5. 写 compact 视图（给 designer 读的紧凑格式，独立文件，只含 compact 块）
    #    designer 用 Read 读这个文件（23KB），不读 rs_input.json 全文（120KB+）
    view_path = Path(args.view_output) if args.view_output else output_path.parent / "rs_input_view.json"
    compact = build_compact(rs_input)
    view_path.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"产出 rs_input_view.json: {view_path}（compact 视图，给 designer）")


if __name__ == "__main__":
    main()
