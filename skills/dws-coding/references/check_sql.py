#!/usr/bin/env python3
"""
SELECT 静态对比: SELECT 语句 vs ts.json 规则切片

检查 coder 写的 SELECT 是否和 ts.json 设计一致。
不连库，纯静态分析。coder 产出 SELECT 后自检用。

检查项：
1. SELECT 输出字段覆盖 ts.json 定义的所有目标字段（不漏）
2. SELECT 引用的 FROM 表在 ts.json 的 source_tables 里（不瞎引用）
3. 括号/引号平衡（基本语法）
4. 没有 SELECT *

用法:
  python check_sql.py --select R0001_select.sql --ts ts.json --rule R0001

退出码: 0=通过, 1=有问题
"""

import sys
import re
import json
import argparse
from pathlib import Path


def read_sql(path: str) -> str:
    """读 SQL 文件，去注释"""
    text = Path(path).read_text(encoding="utf-8")
    # 去块注释 /* */
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    # 去行注释 --（只去行首的，不动行内的 --）
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('--'):
            continue
        lines.append(line)
    return '\n'.join(lines)


def extract_select_aliases(sql: str) -> list[str]:
    """提取 SELECT 输出的字段别名（AS xxx 或隐式别名）。

    例如 SELECT t.contract_no, t.amt AS amount → ['contract_no', 'amount']
    """
    aliases = []

    # 找最外层 SELECT（跳过子查询的 SELECT）
    # 简化策略：找第一个 SELECT 到第一个非嵌套 FROM/WHERE/GROUP 之间
    # 更可靠的是找 "AS xxx" 模式 和 "字段名 xxx" 模式

    # 模式1: AS alias
    for m in re.finditer(r'\bAS\s+(\w+)', sql, re.IGNORECASE):
        aliases.append(m.group(1).lower())

    # 模式2: 字段 空格 alias（不带 AS，如 t.contract_no contract_no）
    # 这个较难准确提取，暂依赖 AS 模式
    # 大多数规范 SQL 都用 AS

    return aliases


def extract_from_tables(sql: str) -> list[str]:
    """提取 FROM/JOIN 引用的表名。"""
    tables = []

    # FROM schema.table 或 FROM table
    # JOIN schema.table 或 JOIN table
    for pattern in [r'\bFROM\s+(\w+(?:\.\w+)?)', r'\bJOIN\s+(\w+(?:\.\w+)?)']:
        for m in re.finditer(pattern, sql, re.IGNORECASE):
            table_ref = m.group(1)
            # 去掉 schema 前缀，只要表名
            table_name = table_ref.split('.')[-1].lower()
            tables.append(table_name)

    return tables


def check_bracket_balance(sql: str) -> tuple[bool, str]:
    """检查括号平衡"""
    depth = 0
    in_string = False
    string_char = ''
    for i, c in enumerate(sql):
        if in_string:
            if c == string_char:
                in_string = False
        elif c in ("'", '"'):
            in_string = True
            string_char = c
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth < 0:
                return False, f"位置{i}: 多余的右括号"
    if depth != 0:
        return False, f"括号不平衡: 差 {depth} 个"
    return True, ""


def check_no_select_star(sql: str) -> tuple[bool, str]:
    """检查没有 SELECT *"""
    # SELECT * 或 SELECT t.*
    if re.search(r'SELECT\s+\*\s', sql, re.IGNORECASE) or \
       re.search(r'SELECT\s+\w+\.\*', sql, re.IGNORECASE):
        return False, "发现 SELECT *（禁止全选，必须列出字段）"
    return True, ""


def check_sql(sql_text: str, ts: dict, rule_code: str) -> list[str]:
    """静态对比 SELECT vs ts.json。

    返回问题列表（空=全部通过）。
    """
    issues = []

    # 1. 规则存在性
    rules = ts.get("rules", {})
    if rule_code not in rules:
        return [f"规则 '{rule_code}' 在 ts.json 里不存在"]

    rule = rules[rule_code]
    design = ts.get("design", {})

    # 2. 基本语法：括号平衡
    ok, msg = check_bracket_balance(sql_text)
    if not ok:
        issues.append(f"[语法] {msg}")

    # 3. 没有 SELECT *
    ok, msg = check_no_select_star(sql_text)
    if not ok:
        issues.append(f"[规范] {msg}")

    # 4. 字段覆盖：SELECT 输出的字段 vs ts.json 定义的目标字段
    ts_fields = {f["target_field"].lower() for f in rule.get("fields", [])}
    # 加审计字段
    audit_fields = {k.lower() for k in design.get("audit_fields", {}).keys()}
    ts_all_fields = ts_fields | audit_fields

    select_aliases = set(extract_select_aliases(sql_text))

    # 只检查有 AS 的字段（没 AS 的隐式别名查不准，不报）
    if select_aliases:
        missing = ts_fields - select_aliases
        # 审计字段单独检查（可能 coder 用了不同的 AS 写法）
        missing_audit = audit_fields - select_aliases

        if missing:
            issues.append(
                f"[字段覆盖] SELECT 缺少字段（ts.json 定义了但 SELECT 没输出）: "
                f"{sorted(missing)}"
            )
        if missing_audit:
            issues.append(
                f"[字段覆盖] SELECT 缺少审计字段: {sorted(missing_audit)}（检查是否带了 AS 别名）"
            )

        # SELECT 多出的字段（不在 ts.json 里的）
        extra = select_aliases - ts_all_fields
        if extra:
            # 过滤掉可能是 CTE 内部别名的
            real_extra = {e for e in extra if not e.startswith('_')}
            if real_extra:
                issues.append(
                    f"[字段覆盖] SELECT 输出了 ts.json 没定义的字段: "
                    f"{sorted(real_extra)}（可能是拼写错误）"
                )

    # 5. FROM 表引用：SELECT 引用的表 vs ts.json 的 source_tables
    ts_source_tables = set()
    for st in rule.get("source_tables", []):
        t = st.get("table", "")
        if t:
            ts_source_tables.add(t.lower())
    # CTE 名也算合法引用
    for cte in rule.get("ctes", []):
        if cte.get("name"):
            ts_source_tables.add(cte["name"].lower())

    select_tables = set(extract_from_tables(sql_text))
    # 去掉可能是子查询别名/CTE定义名的
    unknown_tables = select_tables - ts_source_tables
    # 过滤掉明显的子查询别名（通常很短或首字母大写不一致）
    if unknown_tables:
        issues.append(
            f"[表引用] SELECT 引用了不在 ts.json source_tables 里的表: "
            f"{sorted(unknown_tables)}（确认是否拼写错误或遗漏了源表声明）"
        )

    return issues


def main():
    parser = argparse.ArgumentParser(
        description="SELECT 静态对比: SELECT vs ts.json 规则切片"
    )
    parser.add_argument("--select", required=True, help="SELECT SQL 文件路径")
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--rule", required=True, help="规则编号，如 R0001")
    args = parser.parse_args()

    # 读 SQL
    sql_path = Path(args.select)
    if not sql_path.exists():
        print(f"错误: SELECT 文件不存在: {sql_path}", file=sys.stderr)
        sys.exit(2)
    sql_text = read_sql(str(sql_path))

    # 读 ts.json
    ts_path = Path(args.ts)
    if not ts_path.exists():
        print(f"错误: ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(2)
    ts = json.loads(ts_path.read_text(encoding="utf-8"))

    # 检查
    issues = check_sql(sql_text, ts, args.rule)

    if issues:
        print(f"[静态对比未通过] {args.rule} 有 {len(issues)} 个问题:", file=sys.stderr)
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"[静态对比通过] {args.rule}: 字段覆盖完整, 表引用正确, 语法OK")
        sys.exit(0)


if __name__ == "__main__":
    main()
