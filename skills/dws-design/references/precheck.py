#!/usr/bin/env python3
"""
ETL 任务预检工具

功能:
1. 读取 mapping.json，统计字段数、源表数
2. 检查输入完整性（字段依赖、重复字段等）
3. 输出预检报告

使用方法:
    python3 precheck.py --input mapping.json
    python3 precheck.py --input mapping.json --output precheck_report.md
"""

import os
import sys
import re
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

VERSION = "1.13.0"
CHANGELOG = """
v1.13.0 (2026-04-16):
  - 重构: 目标字段重复检测改为按 scene_group 分组检测（同组内重复报错，跨组合法）
  - 新增: 读取 field_mappings 中的 scene_group 字段
v1.12.0 (2026-03-26):
  - 新增: 识别多表取值表达式（COALESCE/NVL/IFNULL），降级为 INFO 不误报 MAJOR
  - 新增: 识别自然语言描述表达式，降级为 INFO 不误报 MAJOR
v1.11.0 (2026-03-26):
  - 新增: 源表别名校验（SQL标识符合法性、SQL关键字检测、同一目标表内唯一性）
  - 新增: 部分填写别名时发出 WARNING（建议统一填写或统一不填）
v1.10.0 (2026-03-12):
  - 新增: 字段命名规范检查（是否为有效SQL标识符）
  - 检测来源字段和目标字段是否包含中文或特殊字符
  - 直取字段的来源字段必须是有效SQL标识符
v1.9.0 (2026-03-11):
  - 新增: 多场景设计模式识别（multi_scene_union）
  - 优化: 多场景模式下跳过重复字段检查
  - 新增: 读取 field_statistics 输出去重后字段数
v1.8.0 (2026-03-10):
  - 重构: 移除拆分建议功能，预检仅做正确性检查
  - 简化: 返回码从 4 个减少到 3 个（移除 SPLIT_REQUIRED）
  - 删除: 移除 complexity、need_split、split_recommendations 字段
  - 删除: 移除 _evaluate_complexity、_need_split、_generate_split_recommendations、_generate_stg_name 方法
v1.7.0 (2026-03-10):
  - 修复: _is_multi_step_processing() 区分真假多步骤（检查表名引用）
  - 修复: 时间窗口检查只在明确涉及"近N天"等场景触发
  - 优化: 纯计算字段识别逻辑改进
  - 修复: 拆分建议去重
  - 统一: task() 建议格式使用双引号
v1.6.0 (2026-03-08):
  - 重构: 移除非严格模式，所有 CRITICAL/MAJOR 问题始终阻塞
  - 简化: 移除 --strict 和 --ignore-issues 参数
  - 优化: 简化逻辑，避免混淆
v1.5.0 (2026-03-08):
  - 修复: 重复字段检查始终为 CRITICAL，不受 strict 模式影响
  - 修复: 非严格模式下重复字段也会阻塞流程
v1.4.1 (2026-02-28):
  - 优化: 添加 Windows 控制台 UTF-8 编码支持
v1.3.0 (2026-02-20):
  - 新增: 智能识别"纯计算字段"
v1.2.0 (2026-02-19):
  - 新增: 输入完整性预检功能
v1.0.0:
  - 初始版本
"""


@dataclass
class CompletenessIssue:
    """完整性问题"""
    field_name: str
    issue_type: str  # 'missing_source_table', 'multi_step_dependency', 'time_field_ambiguous'
    description: str
    suggestion: str
    severity: str  # 'CRITICAL', 'MAJOR', 'WARNING'


@dataclass
class FieldStatistics:
    """字段统计"""
    total: int
    direct: int  # 直取
    processed: int  # 加工
    implicit: int  # 隐式计算（来源表为空的加工字段）
    with_source_table: int


@dataclass
class PrecheckResult:
    precheck_result: str
    field_count: int
    source_table_count: int
    estimated_lines: int
    # v1.2.0 新增
    completeness_pass: bool = True
    completeness_issues: List[CompletenessIssue] = field(default_factory=list)
    field_statistics: Optional[FieldStatistics] = None


class ETLPrechecker:
    """ETL 任务预检器"""
    
    LINES_PER_FIELD = 4
    
    # 真多步骤标记（明确有多个步骤）
    MULTI_STEP_MARKERS = ['第一步', '第二步', '第三步', '第1步', '第2步', '第3步', 'STEP1', 'STEP2', 'step1', 'step2']
    # 表名引用模式（真多步骤需要关联其他表）
    TABLE_REF_PATTERNS = [
        r'从\s*[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?\s*(?:按|统计|汇总|计算|关联|获取)',
        r'FROM\s+[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?',
        r'JOIN\s+[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?',
        r'子查询.*FROM',
    ]
    
    def __init__(self, mapping_data: Dict[str, Any]):
        self.mapping_data = mapping_data
        self.source_tables = mapping_data.get('source_tables', [])
        self.field_mappings = mapping_data.get('field_mappings', [])
        
    def analyze(self) -> PrecheckResult:
        field_count = len(self.field_mappings)
        source_table_count = len(self.source_tables)
        estimated_lines = field_count * self.LINES_PER_FIELD
        
        field_statistics = self._calculate_field_statistics()
        completeness_issues = self._check_completeness()
        
        has_critical = len([i for i in completeness_issues if i.severity == 'CRITICAL']) > 0
        has_major = len([i for i in completeness_issues if i.severity == 'MAJOR']) > 0
        has_warning = len([i for i in completeness_issues if i.severity == 'WARNING']) > 0
        
        if has_critical or has_major:
            precheck_result = 'INCOMPLETE'
            completeness_pass = False
        elif has_warning:
            precheck_result = 'WARNING'
            completeness_pass = True
        else:
            precheck_result = 'PASS'
            completeness_pass = True
        
        return PrecheckResult(
            precheck_result=precheck_result,
            field_count=field_count,
            source_table_count=source_table_count,
            estimated_lines=estimated_lines,
            completeness_pass=completeness_pass,
            completeness_issues=completeness_issues,
            field_statistics=field_statistics
        )
    
    def _calculate_field_statistics(self) -> FieldStatistics:
        total = len(self.field_mappings)
        direct = sum(1 for f in self.field_mappings if f.get('mapping_rule') == '直取')
        processed = sum(1 for f in self.field_mappings if f.get('mapping_rule') == '加工')
        implicit = sum(1 for f in self.field_mappings if f.get('mapping_rule') == '加工' and not f.get('source_table'))
        with_source = sum(1 for f in self.field_mappings if f.get('source_table'))
        
        return FieldStatistics(
            total=total,
            direct=direct,
            processed=processed,
            implicit=implicit,
            with_source_table=with_source
        )
    
    def _check_completeness(self) -> List[CompletenessIssue]:
        issues = []
        
        for field in self.field_mappings:
            if field.get('mapping_rule') == '加工':
                target_col = field.get('target_column', '')
                source_table = field.get('source_table', '')
                expression = field.get('mapping_expression', '')
                
                if not source_table:
                    if self._is_multi_step_processing(expression):
                        issues.append(CompletenessIssue(
                            field_name=target_col,
                            issue_type='multi_step_dependency',
                            description=f'多步骤加工字段 "{target_col}" 缺少依赖表说明',
                            suggestion=f'请在mapping中补充: {target_col} 字段依赖哪些表？表达式: {expression[:50]}...',
                            severity='CRITICAL'
                        ))
                    elif self._is_pure_calculation_field(expression):
                        issues.append(CompletenessIssue(
                            field_name=target_col,
                            issue_type='pure_calculation',
                            description=f'纯计算字段 "{target_col}"（只引用主表字段）',
                            suggestion=f'已自动识别为纯计算字段，无需关联其他表',
                            severity='INFO'
                        ))
                    elif self._is_multi_table_fallback(expression):
                        issues.append(CompletenessIssue(
                            field_name=target_col,
                            issue_type='multi_table_fallback',
                            description=f'多表取值字段 "{target_col}"（COALESCE/NVL/IFNULL）',
                            suggestion=f'已通过映射表达式描述多表取值逻辑，无需额外指定来源表',
                            severity='INFO'
                        ))
                    elif self._is_natural_language_expression(expression):
                        issues.append(CompletenessIssue(
                            field_name=target_col,
                            issue_type='natural_language_expression',
                            description=f'自然语言描述字段 "{target_col}"',
                            suggestion=f'已通过自然语言描述转换逻辑，Designer 将根据描述生成 SQL',
                            severity='INFO'
                        ))
                    else:
                        issues.append(CompletenessIssue(
                            field_name=target_col,
                            issue_type='missing_source_table',
                            description=f'加工字段 "{target_col}" 来源表为空',
                            suggestion=f'请确认: {target_col} 是纯计算字段还是需要关联其他表？',
                            severity='MAJOR'
                        ))
                
                if self._is_multi_step_processing(expression) and self._has_time_window(expression):
                    time_field = self._extract_time_field(expression)
                    if not time_field:
                        issues.append(CompletenessIssue(
                            field_name=target_col,
                            issue_type='time_field_ambiguous',
                            description=f'多步骤加工字段 "{target_col}" 时间窗口字段不明确',
                            suggestion=f'请补充: 使用哪个时间字段判断"近N天"？(如 create_time, sale_date 等)',
                            severity='MAJOR'
                        ))
        
        # v1.13.0: 按 scene_group 分组检测重复字段
        # 同组内 target_column 重复 → CRITICAL
        # 跨组 target_column 重复 → 合法（不同场景/分组取不同来源的同一字段）
        from collections import defaultdict, Counter
        
        group_fields = defaultdict(list)
        for f in self.field_mappings:
            group_key = f.get('scene_group', '') or ''
            target_col = f.get('target_column', '')
            if target_col:
                group_fields[group_key].append(target_col)
        
        # 如果没有任何分组信息，回退到全局检测
        has_any_group = any(key for key in group_fields.keys())
        
        if has_any_group:
            # 按分组检测
            for group_key, fields in group_fields.items():
                group_label = f'分组"{group_key}"' if group_key else '未分组'
                for name, count in Counter(fields).items():
                    if count > 1:
                        issues.append(CompletenessIssue(
                            field_name=name,
                            issue_type='duplicate_target_field_in_group',
                            description=f'{group_label}内目标字段 "{name}" 重复定义 {count} 次',
                            suggestion=f'同一分组内不允许重复目标字段，请检查 mapping 中 {group_label} 的字段映射',
                            severity='CRITICAL'
                        ))
        else:
            # 无分组信息，全局检测（兼容旧格式）
            for name, count in Counter([f.get('target_column') for f in self.field_mappings if f.get('target_column')]).items():
                if count > 1:
                    issues.append(CompletenessIssue(
                        field_name=name,
                        issue_type='duplicate_target_field',
                        description=f'目标字段 "{name}" 重复定义 {count} 次',
                        suggestion='检查mapping，添加前缀区分或删除重复',
                        severity='CRITICAL'
                    ))
        
        # v1.10.0: 检查字段命名规范（是否为有效SQL标识符）
        issues.extend(self._check_field_naming())
        
        # v1.11.0: 检查源表别名合法性
        issues.extend(self._check_source_aliases())
        
        return issues
    
    def _check_field_naming(self) -> List[CompletenessIssue]:
        """检查字段命名是否符合SQL标识符规范"""
        issues = []
        valid_identifier = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
        
        for field in self.field_mappings:
            source_col = field.get('source_column', '')
            target_col = field.get('target_column', '')
            
            if field.get('mapping_rule') == '直取' and source_col:
                if not valid_identifier.match(source_col):
                    issues.append(CompletenessIssue(
                        field_name=target_col,
                        issue_type='invalid_source_column_name',
                        description=f'来源字段 "{source_col}" 不是有效的SQL标识符',
                        suggestion=f'来源字段应为英文字段名，当前疑似中文名或含特殊字符',
                        severity='CRITICAL'
                    ))
            
            if target_col and not valid_identifier.match(target_col):
                issues.append(CompletenessIssue(
                    field_name=target_col,
                    issue_type='invalid_target_column_name',
                    description=f'目标字段 "{target_col}" 不是有效的SQL标识符',
                    suggestion=f'请使用英文+下划线+数字的命名规范',
                    severity='CRITICAL'
                ))
        
        return issues
    
    def _check_source_aliases(self) -> List[CompletenessIssue]:
        """检查源表别名是否合法（仅当用户填写了别名时校验）"""
        issues = []
        
        valid_identifier = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
        
        SQL_KEYWORDS = frozenset({
            'SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER',
            'ON', 'AND', 'OR', 'NOT', 'IN', 'IS', 'NULL', 'AS', 'GROUP', 'ORDER',
            'BY', 'HAVING', 'LIMIT', 'OFFSET', 'UNION', 'ALL', 'EXISTS', 'BETWEEN',
            'LIKE', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'INSERT', 'UPDATE',
            'DELETE', 'CREATE', 'ALTER', 'DROP', 'TABLE', 'VIEW', 'INDEX',
            'DISTINCT', 'OVER', 'PARTITION', 'WINDOW', 'WITH', 'RECURSIVE',
            'SET', 'INTO', 'VALUES', 'GRANT', 'REVOKE', 'TRUNCATE',
        })
        
        filled_aliases = [(i, st) for i, st in enumerate(self.source_tables) if st.get('source_alias')]
        
        if not filled_aliases:
            return issues
        
        # Check: partial fill warning
        if len(filled_aliases) < len(self.source_tables):
            filled_count = len(filled_aliases)
            total_count = len(self.source_tables)
            issues.append(CompletenessIssue(
                field_name='-',
                issue_type='partial_alias_fill',
                description=f'源表别名仅填写了 {filled_count}/{total_count} 个，建议统一填写或统一不填',
                suggestion='未填写的别名将由 AI 在设计阶段自动推导，或使用 t1/t2/t3 默认别名',
                severity='WARNING'
            ))
        
        # Collect aliases per target table (for uniqueness check)
        from collections import defaultdict
        target_aliases = defaultdict(list)
        
        for i, st in filled_aliases:
            alias = st['source_alias']
            table_name = st.get('source_table', '')
            target_table = st.get('target_table', '')
            
            # Check: valid SQL identifier
            if not valid_identifier.match(alias):
                issues.append(CompletenessIssue(
                    field_name=table_name,
                    issue_type='invalid_source_alias',
                    description=f'源表别名 "{alias}" 不是有效的 SQL 标识符（表: {table_name}）',
                    suggestion='别名应由英文字母、数字和下划线组成，且不能以数字开头',
                    severity='CRITICAL'
                ))
                continue
            
            # Check: SQL keyword
            if alias.upper() in SQL_KEYWORDS:
                issues.append(CompletenessIssue(
                    field_name=table_name,
                    issue_type='reserved_keyword_alias',
                    description=f'源表别名 "{alias}" 是 SQL 保留关键字（表: {table_name}）',
                    suggestion=f'请使用其他别名，如 {table_name[:3]} 或 {table_name.split("_")[0]}',
                    severity='CRITICAL'
                ))
            
            # Collect for uniqueness check
            target_aliases[target_table].append((alias, table_name, i))
        
        # Check: uniqueness within same target table
        for target_table, aliases in target_aliases.items():
            if len(aliases) != len(set(a[0] for a in aliases)):
                from collections import Counter
                alias_counts = Counter(a[0] for a in aliases)
                for alias_name, count in alias_counts.items():
                    if count > 1:
                        tables = [a[1] for a in aliases if a[0] == alias_name]
                        issues.append(CompletenessIssue(
                            field_name=alias_name,
                            issue_type='duplicate_source_alias',
                            description=f'目标表 "{target_table}" 下源表别名 "{alias_name}" 重复使用 {count} 次（表: {", ".join(tables)}）',
                            suggestion='同一目标表内每个源表的别名必须唯一',
                            severity='CRITICAL'
                        ))
        
        entity_aliases = {st['source_alias'] for st in self.source_tables if st.get('source_alias')}
        if entity_aliases:
            for i, fm in enumerate(self.field_mappings):
                attr_alias = fm.get('source_alias', '')
                if attr_alias and attr_alias not in entity_aliases:
                    issues.append(CompletenessIssue(
                        field_name=fm.get('target_column', ''),
                        issue_type='attribute_alias_mismatch',
                        description=f'属性级字段 "{fm.get("target_column", "")}" 的别名 "{attr_alias}" 在实体级 mapping 中不存在',
                        suggestion=f'请确认别名是否正确，实体级已有别名: {", ".join(sorted(entity_aliases))}',
                        severity='CRITICAL'
                    ))
        
        return issues
    
    def _is_multi_step_processing(self, expression: str) -> bool:
        """
        判断是否为真多步骤加工（需要关联其他表或子查询）
        
        判断逻辑：
        1. 有明确的步骤标记（第一步、第二步等）
        2. 或引用了其他表名（FROM、JOIN、从xxx汇总等）
        """
        if not expression:
            return False
        
        if any(marker in expression for marker in self.MULTI_STEP_MARKERS):
            return True
        
        for pattern in self.TABLE_REF_PATTERNS:
            if re.search(pattern, expression, re.IGNORECASE):
                return True
        
        return False
    
    def _is_pure_calculation_field(self, expression: str) -> bool:
        if not expression:
            return False
        
        if self._is_multi_step_processing(expression):
            return False
        
        known_fields = set()
        for fm in self.field_mappings:
            source_col = fm.get('source_column', '')
            if source_col:
                known_fields.add(source_col.lower())
        
        sql_keywords = {
            'coalesce', 'case', 'when', 'then', 'else', 'end', 'datediff', 
            'date_add', 'date_sub', 'now', 'current_date', 'current_timestamp',
            'curdate', 'curtime', 'sysdate', 'getdate',
            'sum', 'count', 'avg', 'max', 'min', 'cast', 'concat', 'substring',
            'trim', 'upper', 'lower', 'length', 'round', 'floor', 'ceil',
            'ifnull', 'nullif', 'nvl', 'abs', 'mod', 'replace', 'instr',
            'to_date', 'to_char', 'to_timestamp', 'extract', 'year', 'month', 'day',
            'and', 'or', 'not', 'null', 'true', 'false', 'as', 'from', 'where',
            'select', 'group', 'order', 'by', 'having', 'limit', 'offset',
            'is', 'in', 'like', 'between', 'exists', 'distinct'
        }
        
        identifiers = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', expression)
        
        if not identifiers:
            return False
        
        for ident in identifiers:
            ident_lower = ident.lower()
            if ident_lower in sql_keywords:
                continue
            if ident.isdigit():
                continue
            if ident_lower not in known_fields:
                return False

        return True

    def _is_multi_table_fallback(self, expression: str) -> bool:
        fallback_keywords = re.compile(
            r'\b(COALESCE|NVL|IFNULL|ISNULL|NULLIF)\s*\(',
            re.IGNORECASE,
        )
        return bool(fallback_keywords.search(expression))

    def _is_natural_language_expression(self, expression: str) -> bool:
        cn_step_patterns = re.compile(r'(?:然后|接着|最后)')
        if cn_step_patterns.search(expression):
            return False
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', expression))
        sql_keywords = re.findall(
            r'\b(SELECT|FROM|WHERE|JOIN|GROUP|ORDER|HAVING|CASE|WHEN|THEN|ELSE|END|'
            r'SUM|COUNT|AVG|MAX|MIN|COALESCE|NVL|OVER|PARTITION|ROW_NUMBER|RANK|DENSE_RANK)\b',
            expression,
            re.IGNORECASE,
        )
        has_arithmetic = bool(re.search(r'[\+\-\*\/]', expression))
        if has_arithmetic and chinese_chars <= 8:
            return False
        return chinese_chars >= 2 and len(sql_keywords) == 0

    TIME_WINDOW_KEYWORDS = ['近', '最近', '天内', '天内', '天内', '天前', '月内', '周内', 'LAST_', 'LAST ', 'LAST_']
    
    def _has_time_window(self, expression: str) -> bool:
        """检查表达式是否涉及时间窗口计算"""
        if not expression:
            return False
        return any(kw in expression.upper() if kw.isascii() else kw in expression for kw in self.TIME_WINDOW_KEYWORDS)
    
    def _extract_time_field(self, expression: str) -> Optional[str]:
        import re
        time_patterns = [
            r'使用\s*(\w+_time|\w+_date)',  # 优先匹配明确的字段声明
            r'近(\d+)天',
            r'(\d+)天内',
        ]
        for pattern in time_patterns:
            match = re.search(pattern, expression)
            if match:
                result = match.group(1)
                # 如果匹配到的是时间字段（以 _time 或 _date 结尾），返回它
                if result and ('_time' in result.lower() or '_date' in result.lower()):
                    return result
                # 否则继续检查下一个模式
        return None


def format_output(result: PrecheckResult, output_format: str = 'text') -> str:
    if output_format == 'json':
        return json.dumps({
            'precheck_result': result.precheck_result,
            'field_count': result.field_count,
            'source_table_count': result.source_table_count,
            'estimated_lines': result.estimated_lines,
            'completeness_pass': result.completeness_pass,
            'completeness_issues': [
                {
                    'field_name': i.field_name,
                    'issue_type': i.issue_type,
                    'description': i.description,
                    'suggestion': i.suggestion,
                    'severity': i.severity
                } for i in result.completeness_issues
            ],
            'field_statistics': {
                'total': result.field_statistics.total,
                'direct': result.field_statistics.direct,
                'processed': result.field_statistics.processed,
                'implicit': result.field_statistics.implicit,
                'with_source_table': result.field_statistics.with_source_table
            } if result.field_statistics else None
        }, ensure_ascii=False, indent=2)
    
    SECTION_FIELD_STATS = "【字段统计】"
    SECTION_COMPLETENESS = "【输入完整性检查】"
    
    lines = []
    lines.append("=" * 60)
    lines.append("ETL 任务预检报告")
    lines.append("=" * 60)
    lines.append("")
    
    lines.append(SECTION_FIELD_STATS)
    if result.field_statistics:
        lines.append(f"  业务字段: {result.field_statistics.total}")
        lines.append(f"    - 直取: {result.field_statistics.direct}")
        lines.append(f"    - 加工: {result.field_statistics.processed}")
        lines.append(f"      - 隐式计算(无来源表): {result.field_statistics.implicit}")
        lines.append(f"  审计字段: 4 (标准: del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date)")
        lines.append(f"  总计: {result.field_statistics.total + 4}")
    lines.append("")
    
    lines.append(f"源表数量: {result.source_table_count}")
    lines.append(f"预估代码行数: {result.estimated_lines}")
    lines.append("")
    
    lines.append(SECTION_COMPLETENESS)
    critical_issues = [i for i in result.completeness_issues if i.severity == 'CRITICAL']
    major_issues = [i for i in result.completeness_issues if i.severity == 'MAJOR']
    warning_issues = [i for i in result.completeness_issues if i.severity == 'WARNING']
    info_issues = [i for i in result.completeness_issues if i.severity == 'INFO']
    
    if result.completeness_pass:
        if warning_issues:
            lines.append(f"  ✅ 通过（非严格模式） - {len(warning_issues)} WARNING（已降级，不阻塞）")
        else:
            lines.append("  ✅ 通过 - 所有加工字段依赖明确")
    else:
        lines.append(f"  ❌ 不通过 - {len(critical_issues)} CRITICAL, {len(major_issues)} MAJOR")
        lines.append("")
        lines.append("  需要补充的信息:")
        for i, issue in enumerate(result.completeness_issues, 1):
            if issue.severity in ['CRITICAL', 'MAJOR']:
                lines.append(f"")
                lines.append(f"  [{issue.severity}] {issue.field_name}:")
                lines.append(f"    问题: {issue.description}")
                lines.append(f"    建议: {issue.suggestion}")
    
    # v1.4.0: 显示 WARNING 级别的问题（非严格模式下的降级问题）
    if warning_issues and not result.completeness_pass:
        lines.append("")
        lines.append("  警告（非严格模式下降级，不阻塞流程）:")
        for issue in warning_issues:
            lines.append(f"    ⚠ {issue.field_name}: {issue.description}")
    
    # v1.3.0: 显示已识别的纯计算字段
    if info_issues:
        lines.append("")
        lines.append("  已自动识别的纯计算字段:")
        for issue in info_issues:
            lines.append(f"    ✓ {issue.field_name}: {issue.description}")
    lines.append("")
    
    lines.append("=" * 60)
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='ETL 任务预检工具')
    parser.add_argument('--input', '-i', required=True, help='mapping.json 文件路径')
    parser.add_argument('--output', '-o', help='输出报告路径 (可选)')
    parser.add_argument('--format', '-f', choices=['text', 'json'], default='text',
                        help='输出格式 (text/json)')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"错误: 文件不存在 {args.input}")
        return 1
    
    with open(args.input, 'r', encoding='utf-8') as f:
        mapping_data = json.load(f)
    
    prechecker = ETLPrechecker(mapping_data)
    result = prechecker.analyze()
    
    output = format_output(result, args.format)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"报告已生成: {args.output}")
    else:
        print(output)
    
    # v1.8.0: 返回码简化
    # 0 = PASS（完全通过）
    # 1 = WARNING（有WARNING但不阻塞，可继续）
    # 2 = INCOMPLETE（有CRITICAL或MAJOR问题，必须停止）
    if result.precheck_result == 'INCOMPLETE':
        return 2
    elif result.precheck_result == 'WARNING':
        return 1
    else:
        return 0


if __name__ == '__main__':
    exit(main())
