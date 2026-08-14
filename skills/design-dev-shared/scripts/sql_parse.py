#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQL 文本解析原语（design-dev-shared 公共库）。

从 check_sql 抽出的纯解析函数：run_ut（字段覆盖对账）和 check_sql（coder 静态自检）
共用，所以沉在 shared，避免 shared→coding 上翻依赖。

只做文本级解析（CTE 拆分/别名抽取/表引用抽取），不做"检查"逻辑（检查在 check_sql）。
不连库，纯函数。
"""

import re
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
