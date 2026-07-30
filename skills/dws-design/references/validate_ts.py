#!/usr/bin/env python3
"""
design.md 完整性校验工具

用途:
  - Designer 输出自检：design.md 生成后检查内容完整性
  - Coder 输入校验：编码前检查 design.md 是否可作为合法输入

校验项:
  1. 字段映射表存在
  2. 目标类型列存在
  3. 目标类型非空
  4. 源类型列存在
  5. 字段数量一致（需 mapping.json）

使用方法:
    python validate_design.py --design docs/output/table/02_design/design.md
    python validate_design.py --design docs/output/table/02_design/design.md --mapping docs/output/table/01_input/mapping.json
    python validate_design.py --design docs/output/table/02_design/design.md --output report.json
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

VERSION = "1.0.0"
CHANGELOG = """
v1.0.0 (2026-04-03):
  - 初始版本：design.md 字段完整性校验
  - 支持：字段映射表存在性、目标类型列、目标类型非空、源类型列
  - 支持：字段数量一致性比对（需 mapping.json）
"""


@dataclass
class CheckResult:
    name: str
    level: str  # PASS, WARNING
    detail: str = ""


@dataclass
class ValidationResult:
    status: str  # PASS, WARNING
    file: str
    checks: List[CheckResult] = field(default_factory=list)
    field_count: int = 0
    fields_missing_target_type: List[str] = field(default_factory=list)


class DesignValidator:
    """design.md 完整性校验器"""

    # 字段映射表的标题模式
    FIELD_MAPPING_PATTERN = re.compile(
        r'^###\s+(步骤\s*\d+[^\n]*字段映射|字段映射对照表)',
        re.IGNORECASE
    )

    def __init__(self, design_path: str):
        self.design_path = design_path
        self.content = ""
        self.lines: List[str] = []

    def load(self) -> bool:
        """加载 design.md"""
        path = Path(self.design_path)
        if not path.exists():
            print(f"错误: 文件不存在 {self.design_path}", file=sys.stderr)
            return False
        try:
            self.content = path.read_text(encoding='utf-8')
            self.lines = self.content.split('\n')
            return True
        except Exception as e:
            print(f"错误: 读取文件失败: {e}", file=sys.stderr)
            return False

    def validate(self, mapping_data: Optional[Dict] = None) -> ValidationResult:
        """执行校验"""
        result = ValidationResult(
            status="PASS",
            file=self.design_path,
            field_count=0,
            fields_missing_target_type=[]
        )

        # 1. 字段映射表存在
        result.checks.append(self._check_mapping_table_exists())

        # 如果没有映射表，后续检查无意义
        has_table = any(c.level == "PASS" for c in result.checks if c.name == "field_mapping_table_exists")
        if has_table:
            # 2. 目标类型列存在
            result.checks.append(self._check_target_type_column())

            # 3. 目标类型非空
            check, missing = self._check_target_type_not_empty()
            result.checks.append(check)
            result.fields_missing_target_type = missing

            # 4. 源类型列存在
            result.checks.append(self._check_source_type_column())

            # 统计字段数量
            result.field_count = self._count_fields()

            # 5. 字段数量一致（需 mapping.json）
            if mapping_data:
                result.checks.append(self._check_field_count_consistency(mapping_data))

        # 判定整体状态
        has_warning = any(c.level == "WARNING" for c in result.checks)
        result.status = "WARNING" if has_warning else "PASS"

        return result

    def _check_mapping_table_exists(self) -> CheckResult:
        """检查字段映射表是否存在"""
        for line in self.lines:
            if self.FIELD_MAPPING_PATTERN.match(line.strip()):
                return CheckResult(name="field_mapping_table_exists", level="PASS")

        return CheckResult(
            name="field_mapping_table_exists",
            level="WARNING",
            detail="未找到字段映射对照表"
        )

    def _find_mapping_tables(self) -> List[Tuple[int, List[str]]]:
        """找到所有字段映射表，返回 [(起始行号, 表头列名列表), ...]"""
        tables = []
        for i, line in enumerate(self.lines):
            if self.FIELD_MAPPING_PATTERN.match(line.strip()):
                # 找到表头行（紧跟标题后的第一个以 | 开头的行）
                for j in range(i + 1, min(i + 5, len(self.lines))):
                    if self.lines[j].strip().startswith('|') and '---' not in self.lines[j]:
                        # 这是表头行
                        headers = [h.strip() for h in self.lines[j].strip().split('|') if h.strip()]
                        tables.append((j, headers))
                        break
        return tables

    def _check_target_type_column(self) -> CheckResult:
        """检查目标类型列是否存在"""
        tables = self._find_mapping_tables()
        if not tables:
            return CheckResult(name="target_type_column_exists", level="PASS")

        for line_no, headers in tables:
            has_target_type = any(
                '目标类型' in h or '目标字段类型' in h or 'target_type' in h.lower()
                for h in headers
            )
            if not has_target_type:
                return CheckResult(
                    name="target_type_column_exists",
                    level="WARNING",
                    detail=f"第 {line_no + 1} 行的字段映射表缺少「目标类型」列"
                )

        return CheckResult(name="target_type_column_exists", level="PASS")

    def _check_source_type_column(self) -> CheckResult:
        """检查源类型列是否存在"""
        tables = self._find_mapping_tables()
        if not tables:
            return CheckResult(name="source_type_column_exists", level="PASS")

        for line_no, headers in tables:
            has_source_type = any(
                '源类型' in h or '源字段类型' in h or 'source_type' in h.lower()
                for h in headers
            )
            if not has_source_type:
                return CheckResult(
                    name="source_type_column_exists",
                    level="WARNING",
                    detail=f"字段映射表缺少「源类型」列（建议补充）"
                )

        return CheckResult(name="source_type_column_exists", level="PASS")

    def _check_target_type_not_empty(self) -> Tuple[CheckResult, List[str]]:
        """检查目标类型是否非空，返回 (结果, 缺失类型字段列表)"""
        missing_fields = []
        tables = self._find_mapping_tables()

        for start_line, headers in tables:
            # 找到目标类型列索引
            target_type_idx = None
            target_field_idx = None
            for idx, h in enumerate(headers):
                if '目标类型' in h or '目标字段类型' in h:
                    target_type_idx = idx
                if '目标字段' in h or 'target字段' in h:
                    if '类型' not in h:  # 排除「目标字段类型」
                        target_field_idx = idx

            if target_type_idx is None or target_field_idx is None:
                continue

            # 读取数据行（跳过表头和分隔行）
            data_start = start_line + 2  # 跳过表头行和 |---| 分隔行
            for i in range(data_start, len(self.lines)):
                line = self.lines[i].strip()
                if not line.startswith('|'):
                    break  # 表格结束

                cells = [c.strip() for c in line.split('|') if c.strip()]
                if len(cells) > target_field_idx and len(cells) > target_type_idx:
                    field_name = cells[target_field_idx]
                    field_type = cells[target_type_idx]
                    if not field_type or field_type == '-' or field_type == '—':
                        if field_name and field_name not in missing_fields:
                            missing_fields.append(field_name)

        if missing_fields:
            return (
                CheckResult(
                    name="target_type_not_empty",
                    level="WARNING",
                    detail=f"{len(missing_fields)} 个字段目标类型为空: {', '.join(missing_fields[:10])}"
                    + (f" ...等{len(missing_fields)}个" if len(missing_fields) > 10 else "")
                ),
                missing_fields
            )

        return CheckResult(name="target_type_not_empty", level="PASS"), missing_fields

    def _count_fields(self) -> int:
        """统计字段数量（去重）"""
        tables = self._find_mapping_tables()
        all_fields = set()

        for start_line, headers in tables:
            target_field_idx = None
            for idx, h in enumerate(headers):
                if '目标字段' in h or '目标字段名' in h:
                    if '类型' not in h:  # 排除「目标字段类型」
                        target_field_idx = idx
                        break

            if target_field_idx is None:
                continue

            data_start = start_line + 2
            for i in range(data_start, len(self.lines)):
                line = self.lines[i].strip()
                if not line.startswith('|'):
                    break
                cells = [c.strip() for c in line.split('|') if c.strip()]
                if len(cells) > target_field_idx:
                    fname = cells[target_field_idx]
                    if fname:
                        all_fields.add(fname)

        return len(all_fields)

    def _check_field_count_consistency(self, mapping_data: Dict) -> CheckResult:
        """检查字段数量是否与 mapping.json 一致"""
        # mapping.json 的去重字段数
        field_stats = mapping_data.get('field_statistics', {})
        mapping_unique = field_stats.get('unique_fields', 0)

        # 如果 mapping.json 没有统计，手动计算
        if not mapping_unique:
            field_mappings = mapping_data.get('field_mappings', [])
            mapping_unique = len(set(f.get('target_column', '') for f in field_mappings if f.get('target_column')))

        design_count = self._count_fields()

        if design_count != mapping_unique and mapping_unique > 0:
            return CheckResult(
                name="field_count_consistency",
                level="WARNING",
                detail=f"字段数量不一致: design.md 有 {design_count} 个, mapping.json 有 {mapping_unique} 个"
            )

        return CheckResult(name="field_count_consistency", level="PASS")


def format_json(result: ValidationResult) -> str:
    """格式化 JSON 输出"""
    output = {
        "status": result.status,
        "file": result.file,
        "checks": [
            {
                "name": c.name,
                "level": c.level,
                **({"detail": c.detail} if c.detail else {})
            }
            for c in result.checks
        ],
        "field_count": result.field_count,
        "fields_missing_target_type": result.fields_missing_target_type
    }
    return json.dumps(output, ensure_ascii=False, indent=2)


def format_text(result: ValidationResult) -> str:
    """格式化文本输出"""
    lines = []
    lines.append("=" * 60)
    lines.append("design.md 校验报告")
    lines.append("=" * 60)
    lines.append(f"文件: {result.file}")

    for c in result.checks:
        if c.level == "PASS":
            lines.append(f"【PASS】{c.name}")
        elif c.level == "WARNING":
            lines.append(f"【WARNING】{c.detail}")

    lines.append("")

    warning_count = sum(1 for c in result.checks if c.level == "WARNING")
    if warning_count > 0:
        lines.append(f"结果: WARNING ({warning_count} 个问题需关注)")
    else:
        lines.append("结果: PASS")

    lines.append("=" * 60)
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='design.md 完整性校验工具')
    parser.add_argument('--design', '-d', required=True, help='design.md 文件路径')
    parser.add_argument('--mapping', '-m', help='mapping.json 文件路径（可选，用于字段数量比对）')
    parser.add_argument('--output', '-o', help='报告输出路径（可选）')
    parser.add_argument('--format', '-f', choices=['text', 'json'], default='text', help='输出格式')

    args = parser.parse_args()

    # 加载 design.md
    validator = DesignValidator(args.design)
    if not validator.load():
        sys.exit(2)

    # 加载 mapping.json（可选）
    mapping_data = None
    if args.mapping:
        mapping_path = Path(args.mapping)
        if mapping_path.exists():
            try:
                with open(mapping_path, 'r', encoding='utf-8') as f:
                    mapping_data = json.load(f)
            except Exception as e:
                print(f"警告: 无法读取 mapping.json: {e}", file=sys.stderr)
        else:
            print(f"警告: mapping.json 不存在: {args.mapping}", file=sys.stderr)

    # 执行校验
    result = validator.validate(mapping_data)

    # 输出
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

    # 返回码: 0=PASS, 1=WARNING
    sys.exit(1 if result.status == "WARNING" else 0)


if __name__ == "__main__":
    main()
