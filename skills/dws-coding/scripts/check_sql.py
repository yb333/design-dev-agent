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


# SQL 文本解析原语沉在 shared（run_ut 也要用）；此处 import 保持旧引用名不变
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from sql_parse import read_sql, split_cte_main, extract_select_aliases, extract_from_tables


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


def check_no_line_comment(sql: str) -> tuple[bool, str]:
    """检查没有 -- 行注释（规范要求一律用 /* */ 块注释）。

    避免误判：跳过字符串字面量（'...' / "..."）里的 --。
    日期字面量如 '2025-01-01' 是单破折号不会被匹配（需要两个连续 -）。
    """
    # 去掉字符串字面量后再检测，避免字符串里的 -- 被误判
    stripped = re.sub(r"'(?:[^'\\]|\\.)*'", "''", sql)
    stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', stripped)
    # 匹配 -- 注释：两个连续 - 后跟非 - 字符（排除 -- 这种，避免 --- 等边界，但 SQL 行注释就是 --）
    # 标准：-- 后面跟空格或直接是行尾，且不是 - 的一部分（如 ->, --）
    # 简化：找 "-- " 或行末 "--"，排除 "--" 在块注释里的情况（块注释已被 read_sql 处理，但这里收原始文本）
    # 先去掉块注释内容，再检测 --
    no_block = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)
    if re.search(r'--[^\-]', no_block) or re.search(r'--$', no_block, re.MULTILINE):
        return False, "发现 -- 行注释（禁止：注释一律用 /* */ 块注释，详见编码规范 §7）"
    return True, ""


def _format_field_list(fields, per_line: int = 5) -> str:
    """把字段列表格式化成多行显示（每行 per_line 个），避免超长单行被截断。

    例: {'b', 'a', 'c'} → "  a, b, c"
        7个字段 → 两行（每行最多5个）
    """
    sorted_fields = sorted(fields)
    lines = []
    for i in range(0, len(sorted_fields), per_line):
        chunk = sorted_fields[i:i + per_line]
        lines.append("  " + ", ".join(chunk))
    return "\n".join(lines)


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

    # 3.1 没有 -- 行注释（规范：一律用 /* */ 块注释）
    ok, msg = check_no_line_comment(sql_text)
    if not ok:
        issues.append(f"[规范] {msg}")

    # 4. 字段覆盖：SELECT 输出的字段 vs ts.json 定义的目标字段
    # 字段名来源：优先 rule.field_targets，fallback rule.fields（旧格式兼容）
    if "field_targets" in rule:
        ts_fields = {t.lower() for t in rule.get("field_targets", [])}
    else:
        ts_fields = {f["target_field"].lower() for f in rule.get("fields", [])}
    # 加审计字段
    audit_fields = {k.lower() for k in design.get("audit_fields", {}).keys()}
    # 加业务主键字段（中间表需要带关联键，即使不在 fields 列表里）
    business_key_fields = {k.lower() for k in design.get("business_key", [])}
    # 加本规则的分组/收敛键（中间表聚合规则的 GROUP BY 键必须 SELECT 出来供下游关联，
    # 但它未必等于全局 business_key，例如订单中心按 user_id 聚合的 tmp 表）。
    # 从 grain.output 与 join_safety 文本里抽标识符作为合法键。
    grain_key_fields = set()
    grain = rule.get("grain", {}) or {}
    if isinstance(grain, dict):
        for m in re.finditer(r'([A-Za-z_]\w*)', str(grain.get("output", ""))):
            grain_key_fields.add(m.group(1).lower())
    # designer 把收敛策略写在 strategy 或 reason 任一字段里（中文 reason 里也会带
    # 英文标识符，如 "按 user_id GROUP BY 聚合"），两个字段都扫，避免漏判。
    # 兼容两种语序：英文 "GROUP BY user_id" 和中文 "按 user_id GROUP BY"。
    for js in rule.get("join_safety", []) or []:
        for field in ("strategy", "reason"):
            text = str(js.get(field, ""))
            for m in re.finditer(r'(?:GROUP BY|PARTITION BY)\s+([A-Za-z_]\w*)', text, re.IGNORECASE):
                grain_key_fields.add(m.group(1).lower())
            for m in re.finditer(r'([A-Za-z_]\w*)\s+(?:GROUP BY|PARTITION BY)', text, re.IGNORECASE):
                grain_key_fields.add(m.group(1).lower())
    ts_all_fields = ts_fields | audit_fields | business_key_fields | grain_key_fields

    select_aliases = set(extract_select_aliases(sql_text))

    # 有 AS 才能校验字段覆盖；无 AS 报提示（统一 AS 写法便于静态对比）
    if select_aliases:
        missing = ts_fields - select_aliases
        # 审计字段单独检查（可能 coder 用了不同的 AS 写法）
        missing_audit = audit_fields - select_aliases

        if missing:
            issues.append(
                f"[字段覆盖] SELECT 缺少字段（ts.json 定义了但 SELECT 没输出），"
                f"共 {len(missing)} 个:\n{_format_field_list(missing)}"
            )
        if missing_audit:
            issues.append(
                f"[字段覆盖] SELECT 缺少审计字段，共 {len(missing_audit)} 个:\n"
                f"{_format_field_list(missing_audit)}\n（检查是否带了 AS 别名）"
            )

        # SELECT 多出的字段（不在 ts.json 里的）
        extra = select_aliases - ts_all_fields
        if extra:
            # 过滤掉可能是 CTE 内部别名的
            real_extra = {e for e in extra if not e.startswith('_')}
            if real_extra:
                issues.append(
                    f"[字段覆盖] SELECT 输出了 ts.json 没定义的字段，"
                    f"共 {len(real_extra)} 个:\n{_format_field_list(real_extra)}\n"
                    f"（可能是拼写错误）"
                )
    else:
        issues.append(
            "[字段覆盖] SELECT 输出列没有 AS 别名，字段覆盖无法校验"
            "（输出列请统一用 `expr AS 别名` 写法，便于静态对比）"
        )

    # 5. FROM 表引用：SELECT 引用的表 vs ts.json 的 source_tables
    ts_source_tables = set()
    for st in rule.get("source_tables", []):
        t = st.get("table", "")
        if t:
            ts_source_tables.add(t.lower())
    # 所有规则的 target_table（中间表）也算合法引用——多规则场景下下游会引用上游产出的中间表
    for rc, rr in rules.items():
        tt = rr.get("target_table", "")
        if tt:
            ts_source_tables.add(tt.split(".")[-1].lower())
    # SQL 里实际定义的 CTE 名也算合法引用（designer 通常不把 ctes 写进 ts.json，
    # 但 coder 产出的 SELECT 里 WITH ... AS (...) 定义的 CTE 是合法的本地表引用）
    cte_names, _main = split_cte_main(sql_text)
    ts_source_tables.update(cte_names)

    select_tables = set(extract_from_tables(sql_text))
    # 去掉可能是子查询别名/CTE定义名的
    unknown_tables = select_tables - ts_source_tables
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
            print(file=sys.stderr)  # issue 之间空行，避免多行字段列表粘连
        sys.exit(1)
    else:
        print(f"[静态对比通过] {args.rule}: 字段覆盖完整, 表引用正确, 语法OK")
        sys.exit(0)


if __name__ == "__main__":
    main()
