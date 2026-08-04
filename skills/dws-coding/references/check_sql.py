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


def split_cte_main(sql: str) -> tuple[list[str], str]:
    """把 SQL 拆成 (CTE 名列表, 主查询体)。

    支持 `WITH name AS (...), name2 AS (...) <主SELECT>` 结构。
    返回的 main 是最后一个顶层 CTE 右括号之后的 SQL（即最终对外输出的 SELECT）；
    若没有 WITH，main 就是整个 sql。CTE 名供表引用校验把它们视作合法引用。

    关键：通过括号深度跟踪 + 顶层 CTE 头模式 `name AS (` 识别。
    WITH 子句里顶层只会出现「, name AS (」(下一个 CTE) 或主查询开头；
    一旦在 depth==0 处遇到非 CTE 头的内容，说明已进入主查询，即可停止。
    这样主查询里 COALESCE(...)/CASE...END 的括号不会被误判成 CTE 边界。
    """
    m = re.search(r'\bWITH\b', sql, re.IGNORECASE)
    if not m:
        return [], sql

    body = sql[m.end():]
    cte_names: list[str] = []
    depth = 0
    last_cte_close = -1  # 最后一个 CTE 的右括号在 body 中的位置
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == '(':
            depth += 1
            i += 1
            continue
        if ch == ')':
            depth -= 1
            # 只在「正在解析某个 CTE」时记录闭合位置
            if depth == 0 and cte_names and last_cte_close < i:
                # 确认这是当前最后一个 CTE 的闭合：要求此后到下一个 CTE 头/主查询之间是顶层
                last_cte_close = i
            i += 1
            continue
        if depth == 0:
            # 跳过 CTE 之间的逗号/空白
            if ch in (',', ' ', '\t', '\n', '\r'):
                i += 1
                continue
            # 顶层尝试匹配 CTE 头: <名字> AS (
            hm = re.match(r'([A-Za-z_]\w*)\s+AS\s*\(', body[i:], re.IGNORECASE)
            if hm:
                cte_names.append(hm.group(1).lower())
                last_cte_close = -1  # 重置，等这个新 CTE 的右括号
                i += hm.end() - 1  # 跳到 '(' 让 depth 计数接管其内部
                continue
            # 顶层遇到非逗号/空白/CTE 头 → 已进入主查询，停止扫描
            break
        i += 1

    if last_cte_close >= 0:
        main = body[last_cte_close + 1:].strip()
    else:
        main = body.strip()
    return cte_names, main


def _strip_sql_noise(sql: str) -> str:
    """去掉会干扰字段/表抽取的 SQL 结构，避免误判。

    处理：
    1. EXTRACT(x FROM y) → EXTRACT(x FROM y) 里的 FROM 不是表引用，整体替换掉 FROM 子句
    2. CAST(... AS type) / ::type → 类型转换的 AS type 不是字段别名
    """
    s = sql
    # 1. EXTRACT(<part> FROM <expr>) —— 这里的 FROM 是函数语法，不是表引用
    #    把 " FROM " 在 EXTRACT 上下文里替换掉（简单做法：替换 EXTRACT(...FROM...) 中的 FROM）
    s = re.sub(r'(EXTRACT\s*\([^)]*?)\bFROM\b', r'\1__FROM__', s, flags=re.IGNORECASE)
    # 2. CAST(<expr> AS <type>) —— 去掉 "AS <type>"，避免类型被当成别名
    s = re.sub(r'\bAS\s+(BIGINT|INT|INTEGER|SMALLINT|DECIMAL|NUMERIC|FLOAT|DOUBLE|REAL|'
               r'VARCHAR|NVARCHAR|CHAR|TEXT|DATE|DATETIME|TIMESTAMP|BOOLEAN|BOOL|'
               r'INTERVAL|JSON|BLOB|BYTEA|SERIAL)\b',
               '', s, flags=re.IGNORECASE)
    # 3. postgres 风格的类型转换 ::type
    s = re.sub(r'::\w+', '', s)
    return s


def extract_select_aliases(sql: str) -> list[str]:
    """提取【主查询】SELECT 输出的字段别名（AS xxx）。

    只看 WITH ... 之后的最终 SELECT，避免把 CTE 内部的 AS 别名误当成输出字段。
    例如 SELECT t.contract_no, t.amt AS amount → ['contract_no', 'amount']
    也排除了 CAST(... AS type) / ::type 里的类型名（不是字段别名）。
    """
    _cte_names, main = split_cte_main(sql)
    target = main if main else sql
    target = _strip_sql_noise(target)

    aliases = []
    # 模式: AS alias（只取 ASCII 标识符；SQL 别名不会含中文等非 ASCII 字符，
    # 限制为 ASCII 可避免注释里残留的 "JOIN 的" 这类被误当成别名）
    for m in re.finditer(r'\bAS\s+([A-Za-z_]\w*)', target, re.IGNORECASE):
        aliases.append(m.group(1).lower())
    # 模式: 字段 空格 alias（不带 AS）较难准确提取，暂依赖 AS 模式（规范 SQL 都用 AS）
    return aliases


def extract_from_tables(sql: str) -> list[str]:
    """提取 FROM/JOIN 引用的表名（含 CTE 名，CTE 名合法性由调用方结合 cte_names 判断）。

    先去掉 EXTRACT(... FROM ...) 这类函数语法里的 FROM，避免误判。
    """
    tables = []
    sql = _strip_sql_noise(sql)

    # FROM schema.table 或 FROM table
    # JOIN schema.table 或 JOIN table
    # 只取 ASCII 标识符：表名不会含中文等非 ASCII 字符，避免注释残留（如 "JOIN 的"）误判
    for pattern in [r'\bFROM\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)', r'\bJOIN\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)']:
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
        sys.exit(1)
    else:
        print(f"[静态对比通过] {args.rule}: 字段覆盖完整, 表引用正确, 语法OK")
        sys.exit(0)


if __name__ == "__main__":
    main()
