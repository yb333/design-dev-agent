#!/usr/bin/env python3
"""
输入预检: 校验 rs_input.json 的完整性。

独立于 preprocess.py（只做转换），本脚本只做校验。
用户修改 mapping.xlsx 或 RS.md 后，重新跑 preprocess 转换，再跑本脚本校验。

用法:
    python precheck.py --input rs_input.json
    python precheck.py --input rs_input.json --output precheck_report.md
"""

import sys
import argparse
from typing import Any
from pathlib import Path


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


# 合法的映射规则类型
VALID_RULES = {"直接复制", "数据加工", "赋值", "序列"}


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
        result.add_error("无源表 (source_tables 为空)")
    else:
        result.add_pass(f"源表数: {len(source_tables)}")
        for st in source_tables:
            if not st.get("source_alias"):
                result.add_warn(f"源表 {st.get('source_table', '?')} 缺少别名 (source_alias)")

    # 3. 字段映射 (含映射规则交叉校验)
    field_mappings = rs_input.get("field_mappings", [])
    if not field_mappings:
        result.add_error("无字段映射 (field_mappings 为空)")
    else:
        result.add_pass(f"字段映射数: {len(field_mappings)}")

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
                result.add_error(f"字段 {target_field} 的映射规则 '{rule}' 不合法 (应为: 直接复制/数据加工/赋值/序列)")
                continue

            # 3b. 交叉校验
            if rule == "直接复制":
                if expr and expr != "-":
                    result.add_warn(f"字段 {target_field} 是'直接复制'但填了映射表达式 '{expr[:30]}', 若有加工逻辑应改为'数据加工'")
                if not source_field:
                    result.add_error(f"字段 {target_field} 是'直接复制'但缺少来源字段 (source_column)")
            elif rule == "数据加工":
                if not expr or expr == "-":
                    result.add_error(f"字段 {target_field} 是'数据加工'但映射表达式为空 (必须描述加工逻辑)")
                if not source_field:
                    result.add_warn(f"字段 {target_field} 是'数据加工'但没有来源字段, 确认是否为纯派生字段")
            elif rule == "赋值":
                if not expr or expr == "-":
                    result.add_error(f"字段 {target_field} 是'赋值'但映射表达式为空 (必须说明赋什么值)")
            elif rule == "序列":
                result.add_pass(f"字段 {target_field} 是'序列'类型 (自增序列, 特殊处理)")

    # 4. 目标字段重复检查
    seen_fields: dict[str, int] = {}
    for fm in field_mappings:
        tf = fm.get("target_column", "")
        if tf:
            seen_fields[tf] = seen_fields.get(tf, 0) + 1
    for field, count in seen_fields.items():
        if count > 1:
            result.add_error(f"目标字段 '{field}' 重复出现 {count} 次")

    # 5. 调度信息 (来自 RS)
    schedule = rs_input.get("schedule", {})
    if not schedule.get("frequency"):
        result.add_warn("调度频率缺失 (RS L07 调度频率)")
    if not schedule.get("upstream"):
        result.add_warn("上游调度任务缺失 (RS L07 湖表调度信息)")

    # 6. 别名一致性
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


def main():
    parser = argparse.ArgumentParser(description="输入预检: 校验 rs_input.json 完整性")
    parser.add_argument("--input", required=True, help="rs_input.json 路径")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 文件不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    import json
    rs_input = json.loads(input_path.read_text(encoding="utf-8"))

    result = precheck(rs_input)
    print(result.summary())
    sys.exit(result.return_code)


if __name__ == "__main__":
    main()
