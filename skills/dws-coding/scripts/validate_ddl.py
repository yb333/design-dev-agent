#!/usr/bin/env python3
"""
DDL 产出物校验工具

用途: Coder 生成 DDL 后的自检，确保 DDL 与 design.md 类型一致

校验项:
  1. DDL 字段类型 vs design.md 目标类型一致性 (CRITICAL)
  2. DDL 业务字段完整性 (CRITICAL)

使用方法:
    python validate_ddl.py --ddl-dir docs/output/table/04_ddl --design docs/output/table/02_design/design.md
    python validate_ddl.py --ddl-dir docs/output/table/04_ddl --design docs/output/table/02_design/design.md --output report.json
"""

import os
import sys
import re
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

VERSION = "1.1.0"
CHANGELOG = """
v1.1.0 (2026-04-11):
  - 新增: CREATE IF NOT EXISTS 检查
  - 新增: TO GROUP 逻辑集群检查（schema 含 drt → gtoup_version1，否则 → LC_DW1）
  - 新增: 禁止 DROP TABLE 检查
  - 新增: 回退脚本完整性检查
v1.0.0 (2026-04-03):
  - 初始版本：DDL 字段类型一致性校验
  - 支持：DDL vs design.md 目标类型比对 (CRITICAL)
  - 支持：DDL 业务字段完整性检查 (CRITICAL)
"""

AUDIT_FIELDS = frozenset({
    'del_flag', 'crt_cycle_id', 'last_upd_cycle_id', 'dw_last_update_date'
})

# 逻辑集群配置
LOGICAL_GROUP_REALTIME = "gtoup_version1"  # 实时区
LOGICAL_GROUP_OFFLINE = "LC_DW1"           # 离线区（默认）
REALTIME_SCHEMA_PATTERN = re.compile(r'drt', re.IGNORECASE)


def infer_logical_group(schema: str) -> str:
    """根据 schema 推断逻辑集群：schema 含 drt → gtoup_version1，否则 → LC_DW1"""
    if REALTIME_SCHEMA_PATTERN.search(schema):
        return LOGICAL_GROUP_REALTIME
    return LOGICAL_GROUP_OFFLINE

DDL_TYPE_PATTERN = re.compile(
    r'(VARCHAR2?\s*\([^)]*\)|NVARCHAR2\s*\([^)]*\)|CHAR\s*\([^)]*\)|NCHAR\s*\([^)]*\)|'
    r'INT|INTEGER|BIGINT|SMALLINT|TINYINT|'
    r'DECIMAL\s*\([^)]*\)|NUMERIC\s*\([^)]*\)|NUMBER\s*\([^)]*\)|FLOAT|DOUBLE|REAL|'
    r'DATE|TIME|TIMESTAMP|TIMESTAMPTZ|'
    r'BOOLEAN|BOOL|TEXT|CLOB|BLOB|BYTEA|UUID|'
    r'JSON|JSONB|SERIAL|BIGSERIAL|SMALLSERIAL)',
    re.IGNORECASE
)


@dataclass
class FieldMismatch:
    file: str
    table: str
    design_step: str
    field: str
    ddl_type: str
    design_type: str


@dataclass
class DDLFileResult:
    file: str
    table: str
    design_step: str
    total_fields: int = 0
    matched: int = 0
    mismatches: List[FieldMismatch] = field(default_factory=list)
    missing_in_ddl: List[str] = field(default_factory=list)
    missing_in_design: List[str] = field(default_factory=list)
    ddl_convention_issues: List[str] = field(default_factory=list)


@dataclass
class DDLValidationResult:
    status: str  # PASS, CRITICAL
    ddl_dir: str
    design_file: str
    files: List[DDLFileResult] = field(default_factory=list)
    all_mismatches: List[FieldMismatch] = field(default_factory=list)
    total_fields: int = 0
    matched: int = 0
    mismatched: int = 0
    rollback_issues: List[str] = field(default_factory=list)


def normalize_type(type_str: str) -> str:
    """规范化类型字符串用于比对：去空格、统一大小写"""
    return re.sub(r'\s+', '', type_str).upper()


def parse_ddl(content: str) -> Optional[Tuple[str, List[Tuple[str, str]]]]:
    """解析 DDL，返回 (表名, [(字段名, 类型), ...]) 或 None"""
    create_match = re.search(r'CREATE\s+TABLE\s+(\S+)\s*\(', content, re.IGNORECASE)
    if not create_match:
        return None

    table_name = create_match.group(1)

    start_pos = create_match.end()
    depth = 1
    end_pos = start_pos
    for i in range(start_pos, len(content)):
        char = content[i]
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                end_pos = i
                break

    fields_section = content[start_pos:end_pos]
    constraint_keywords = ('PRIMARY', 'FOREIGN', 'UNIQUE', 'CHECK', 'CONSTRAINT',
                           'INDEX', 'KEY', 'REFERENCES')
    fields = []

    for line in fields_section.split('\n'):
        line = line.strip().rstrip(',')
        if not line or line.startswith('--'):
            continue

        upper_line = line.upper()
        if upper_line.startswith(constraint_keywords):
            continue

        field_match = re.match(r'^(\w+)\s+' + DDL_TYPE_PATTERN.pattern, line, re.IGNORECASE)
        if field_match:
            field_name = field_match.group(1)
            field_type = field_match.group(2)
            fields.append((field_name, field_type))

    return table_name, fields


def parse_design_mappings(content: str) -> List[Dict]:
    """从 design.md 提取所有步骤的字段映射，返回 [{step, output_table, fields: {name: type}}]

    两阶段解析：先扫描全文建立 step_number → output_table 映射，再按步骤号查表。
    解决输出表与字段映射标题跨章节距离过远（原 20 行回溯不够）的问题。
    """
    mapping_pattern = re.compile(
        r'^###\s+(步骤\s*\d+[^\n]*字段映射|字段映射对照表)',
        re.IGNORECASE
    )

    lines = content.split('\n')

    # Phase 1: 扫描全文，建立 step_number → output_table 映射
    step_output_map = {}
    current_step_num = None
    step_header_re = re.compile(r'###\s*步骤\s*(\d+)')
    output_table_re = re.compile(r'\*\*(?:目标表|输出表)\*\*:\s*`?(\S+)`?')

    for line in lines:
        sm = step_header_re.match(line.strip())
        if sm:
            current_step_num = int(sm.group(1))
            continue
        if current_step_num is not None:
            tm = output_table_re.search(line)
            if tm:
                step_output_map[current_step_num] = tm.group(1)

    # Phase 2: 处理字段映射，按步骤号查表获取 output_table
    results = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if mapping_pattern.match(line.strip()):
            step_title = line.strip().lstrip('#').strip()

            step_num_match = re.search(r'步骤\s*(\d+)', step_title)
            output_table = step_output_map.get(int(step_num_match.group(1)), "") if step_num_match else ""

            headers = []
            data_rows = []

            for j in range(i + 1, min(i + 8, len(lines))):
                if lines[j].strip().startswith('|') and '---' not in lines[j]:
                    if not headers:
                        headers = [h.strip() for h in lines[j].strip().split('|') if h.strip()]
                    else:
                        cells = [c.strip() for c in lines[j].strip().split('|') if c.strip()]
                        if cells:
                            data_rows.append(cells)

                elif '---' in lines[j]:
                    continue
                elif lines[j].strip().startswith('#'):
                    break

            target_type_idx = None
            target_field_idx = None
            for idx, h in enumerate(headers):
                if '目标类型' in h or '目标字段类型' in h:
                    target_type_idx = idx
                if ('目标字段' in h or '目标字段名' in h) and '类型' not in h:
                    target_field_idx = idx

            fields = {}
            if target_type_idx is not None and target_field_idx is not None:
                for row in data_rows:
                    if len(row) > max(target_field_idx, target_type_idx):
                        fname = row[target_field_idx]
                        ftype = row[target_type_idx]
                        if fname and ftype and ftype != '-' and ftype != '—':
                            fields[fname] = ftype

            results.append({
                "step": step_title,
                "output_table": output_table,
                "fields": fields
            })

        i += 1

    return results


def match_ddl_to_design(ddl_table: str, design_mappings: List[Dict]) -> Optional[Dict]:
    ddl_lower = ddl_table.lower().replace('`', '')

    for dm in design_mappings:
        design_table = dm["output_table"].lower().replace('`', '')

        if ddl_lower == design_table:
            return dm

        ddl_name = ddl_lower.split('.')[-1] if '.' in ddl_lower else ddl_lower
        design_name = design_table.split('.')[-1] if '.' in design_table else design_table

        if ddl_name == design_name:
            return dm

    step_match = re.search(r'step[_\s]*(\d+)', ddl_lower)
    if step_match:
        ddl_step_num = int(step_match.group(1))
        for dm in design_mappings:
            design_step_num_match = re.search(r'步骤\s*(\d+)', dm["step"])
            if design_step_num_match:
                design_step_num = int(design_step_num_match.group(1))
                if ddl_step_num == design_step_num:
                    return dm

    return None


def validate(ddl_dir: str, design_path: str) -> DDLValidationResult:
    """执行 DDL 校验"""
    design_content = Path(design_path).read_text(encoding='utf-8')
    design_mappings = parse_design_mappings(design_content)

    result = DDLValidationResult(
        status="PASS",
        ddl_dir=ddl_dir,
        design_file=design_path
    )

    ddl_path = Path(ddl_dir)
    if not ddl_path.exists():
        result.status = "CRITICAL"
        return result

    for ddl_file in sorted(ddl_path.glob('*.sql')):
        content = ddl_file.read_text(encoding='utf-8')
        parsed = parse_ddl(content)

        if not parsed:
            continue

        table_name, ddl_fields = parsed
        ddl_field_dict = {name: ftype for name, ftype in ddl_fields if name not in AUDIT_FIELDS}

        dm = match_ddl_to_design(table_name, design_mappings)
        design_step = dm["step"] if dm else "未匹配"

        file_result = DDLFileResult(
            file=ddl_file.name,
            table=table_name,
            design_step=design_step
        )

        if dm:
            design_fields = dm["fields"]

            for fname, ddl_type in ddl_field_dict.items():
                file_result.total_fields += 1
                result.total_fields += 1

                if fname in design_fields:
                    design_type = design_fields[fname]
                    if normalize_type(ddl_type) == normalize_type(design_type):
                        file_result.matched += 1
                        result.matched += 1
                    else:
                        mismatch = FieldMismatch(
                            file=ddl_file.name,
                            table=table_name,
                            design_step=design_step,
                            field=fname,
                            ddl_type=ddl_type,
                            design_type=design_type
                        )
                        file_result.mismatches.append(mismatch)
                        result.all_mismatches.append(mismatch)
                        result.mismatched += 1
                else:
                    file_result.missing_in_design.append(fname)

            for fname in design_fields:
                if fname not in ddl_field_dict:
                    file_result.missing_in_ddl.append(fname)

        # DDL 规范检查
        _check_ddl_conventions(content, table_name, file_result)

        result.files.append(file_result)

    if result.mismatched > 0 or any(f.missing_in_ddl for f in result.files) \
            or any(f.ddl_convention_issues for f in result.files) \
            or result.rollback_issues:
        result.status = "CRITICAL"

    return result


def _check_ddl_conventions(content: str, table_name: str, file_result: DDLFileResult):
    """检查 DDL 是否符合建表规范"""
    content_upper = content.upper()

    # 检查 1: 禁止 DROP TABLE
    if re.search(r'\bDROP\s+TABLE\b', content_upper):
        file_result.ddl_convention_issues.append(
            "DDL 中包含 DROP TABLE 语句，禁止使用，应使用 CREATE TABLE IF NOT EXISTS")

    # 检查 2: 必须使用 CREATE TABLE IF NOT EXISTS
    create_match = re.search(r'\bCREATE\s+TABLE\b', content_upper)
    if create_match:
        if not re.search(r'\bCREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\b', content_upper):
            file_result.ddl_convention_issues.append(
                "必须使用 CREATE TABLE IF NOT EXISTS，当前缺少 IF NOT EXISTS")

    # 检查 3: 必须有 TO GROUP
    if create_match:
        if not re.search(r'\bTO\s+GROUP\b', content_upper):
            file_result.ddl_convention_issues.append("缺少 TO GROUP 逻辑集群指定")
        else:
            # 检查 4: 逻辑集群值与 schema 是否匹配
            group_match = re.search(r'TO\s+GROUP\s+"([^"]+)"', content, re.IGNORECASE)
            if group_match:
                group_value = group_match.group(1)
                schema = table_name.split('.')[0] if '.' in table_name else ''
                expected_group = infer_logical_group(schema)
                if group_value != expected_group:
                    file_result.ddl_convention_issues.append(
                        f"逻辑集群不匹配: schema='{schema}' 期望 '{expected_group}'，实际 '{group_value}'")

    # 检查 5: CREATE VIEW 也需要 TO GROUP
    view_match = re.search(r'\bCREATE\s+(OR\s+REPLACE\s+)?VIEW\b', content_upper)
    if view_match:
        if not re.search(r'\bTO\s+GROUP\b', content_upper):
            file_result.ddl_convention_issues.append("视图定义缺少 TO GROUP 逻辑集群指定")


def _check_rollback_scripts(ddl_dir: str, result: DDLValidationResult):
    """检查回退脚本完整性"""
    ddl_path = Path(ddl_dir)
    rollback_dir = ddl_path.parent / "04_ddl_rollback"

    if not rollback_dir.exists():
        result.rollback_issues.append(
            f"回退脚本目录不存在: {rollback_dir}，每个 DDL 必须有对应的回退脚本")
        return

    rollback_files = set(f.name for f in rollback_dir.glob('*.sql'))

    for file_result in result.files:
        ddl_name = file_result.file
        if ddl_name.startswith('create_table_') or ddl_name.startswith('create_view_'):
            expected_rollback = f"rollback_{ddl_name}"
            if expected_rollback not in rollback_files:
                result.rollback_issues.append(
                    f"DDL '{ddl_name}' 缺少回退脚本 '{expected_rollback}'")


def format_text(result: DDLValidationResult) -> str:
    """格式化文本输出"""
    lines = []
    lines.append("=" * 60)
    lines.append("DDL 类型一致性检查报告")
    lines.append("=" * 60)
    lines.append(f"DDL 目录: {result.ddl_dir}")
    lines.append(f"设计文档: {result.design_file}")
    lines.append("")

    for fr in result.files:
        status_icon = "✅" if not fr.mismatches and not fr.missing_in_ddl and not fr.ddl_convention_issues else "⚠"
        lines.append(f"文件: {fr.file} ({fr.table}) → {fr.design_step}")
        lines.append(f"  匹配: {fr.matched}/{fr.total_fields}")

        for m in fr.mismatches:
            lines.append(f"  ⚠ {m.field:30s} DDL: {m.ddl_type:20s} 设计: {m.design_type}")

        for fname in fr.missing_in_ddl:
            lines.append(f"  ✗ {fname} 在 DDL 中缺失")

        for issue in fr.ddl_convention_issues:
            lines.append(f"  ✗ DDL规范: {issue}")

        lines.append("")

    for issue in result.rollback_issues:
        lines.append(f"  ✗ 回退脚本: {issue}")

    lines.append(f"汇总: {len(result.files)} 个文件, {result.total_fields} 个字段, "
                 f"{result.matched} 匹配, {result.mismatched} 不一致")

    if result.status == "CRITICAL":
        lines.append("结果: CRITICAL (存在类型不一致，必须修复)")
    else:
        lines.append("结果: PASS")

    lines.append("=" * 60)
    return '\n'.join(lines)


def format_json(result: DDLValidationResult) -> str:
    """格式化 JSON 输出"""
    files_data = []
    for fr in result.files:
        files_data.append({
            "file": fr.file,
            "table": fr.table,
            "design_step": fr.design_step,
            "total_fields": fr.total_fields,
            "matched": fr.matched,
            "mismatches": [
                {"field": m.field, "ddl_type": m.ddl_type, "design_type": m.design_type}
                for m in fr.mismatches
            ],
            "missing_in_ddl": fr.missing_in_ddl,
            "missing_in_design": fr.missing_in_design,
            "ddl_convention_issues": fr.ddl_convention_issues
        })

    output = {
        "status": result.status,
        "ddl_dir": result.ddl_dir,
        "design_file": result.design_file,
        "files": files_data,
        "summary": {
            "total_ddl_files": len(result.files),
            "total_fields": result.total_fields,
            "matched": result.matched,
            "mismatched": result.mismatched
        },
        "all_mismatches": [
            {"file": m.file, "field": m.field, "ddl_type": m.ddl_type, "design_type": m.design_type}
            for m in result.all_mismatches
        ]
    }
    return json.dumps(output, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description='DDL 产出物校验工具')
    parser.add_argument('--ddl-dir', required=True, help='DDL 目录路径')
    parser.add_argument('--design', '-d', required=True, help='design.md 文件路径')
    parser.add_argument('--output', '-o', help='报告输出路径（可选）')
    parser.add_argument('--format', '-f', choices=['text', 'json'], default='text', help='输出格式')

    args = parser.parse_args()

    if not Path(args.design).exists():
        print(f"错误: design.md 不存在: {args.design}", file=sys.stderr)
        sys.exit(2)

    result = validate(args.ddl_dir, args.design)

    _check_rollback_scripts(args.ddl_dir, result)
    if result.rollback_issues:
        result.status = "CRITICAL"

    if args.format == 'json':
        output = format_json(result)
    else:
        output = format_text(result)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"报告已生成: {out_path}")
    else:
        print(output)

    sys.exit(2 if result.status == "CRITICAL" else 0)


if __name__ == "__main__":
    main()
