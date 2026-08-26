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
    in_string = False
    string_char = ''
    while i < n:
        ch = body[i]
        # 字符串字面量内的括号不参与深度计数（"WHERE note = '('" 会把边界打乱）
        if in_string:
            if ch == string_char:
                in_string = False
            i += 1
            continue
        if ch in ("'", '"'):
            in_string = True
            string_char = ch
            i += 1
            continue
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


def _skip_sql_string(s: str, j: int) -> int:
    """跳过 '...' 字符串字面量（'' 转义），返回串后位置。s[j] 必须是 '。"""
    j += 1
    n = len(s)
    while j < n:
        if s[j] == "'":
            if j + 1 < n and s[j + 1] == "'":
                j += 2
                continue
            return j + 1
        j += 1
    return n


def _skip_sql_comment(s: str, j: int) -> int:
    """跳过 /* */ 块注释或 -- 行注释，返回注释后位置。s[j:j+2] 必须是 /* 或 --。"""
    if s.startswith('/*', j):
        end = s.find('*/', j + 2)
        return len(s) if end == -1 else end + 2
    end = s.find('\n', j)
    return len(s) if end == -1 else end + 1


def _mask_literals_and_comments(s: str) -> str:
    """字符串字面量与注释的内容抹成空格，防其中残留的 AS/FROM/JOIN 干扰 token 抽取。"""
    out = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "'":
            j = _skip_sql_string(s, i)
            out.append(''.join(c if c == "'" else ' ' for c in s[i:j]))
            i = j
        elif s.startswith('/*', i) or s.startswith('--', i):
            j = _skip_sql_comment(s, i)
            out.append(' ' * (j - i))
            i = j
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


_CAST_HEAD = re.compile(r'\b(?:TRY_)?CAST\s*\(', re.IGNORECASE)


def _is_as_word(s: str, j: int) -> bool:
    """s[j] 起是否是独立的 AS 词（左侧词边界，右侧非标识符字符）。"""
    if not re.match(r'AS(?![A-Za-z0-9_])', s[j:], re.IGNORECASE):
        return False
    return j == 0 or not re.match(r'[A-Za-z0-9_]', s[j - 1])


def _strip_cast_types(s: str) -> str:
    """结构化剥除 CAST(<expr> AS <type>) 里的 "AS <type>"（含 TRY_CAST）。

    类型名是开放集（GaussDB 的 int8/timestamptz/bpchar…枚举必漏），所以不认类型名、
    认结构：括号深度扫描定位 CAST( 的配对范围，剥其中相对深度 0 的 AS 词到收口括号
    （保留收口括号与其前的表达式，类型带精度括号天然兼容）。字符串/注释不参与扫描；
    嵌套 CAST 对保留的表达式段递归处理。
    括号不平衡（烂 SQL）→ 整体放弃返回原文，调用方的 ANSI 白名单兜底（宁放过不误报）。
    """
    out = []
    pos = 0
    while True:
        m = _CAST_HEAD.search(s, pos)
        if not m:
            out.append(s[pos:])
            return ''.join(out)
        out.append(s[pos:m.end()])
        j = m.end()
        n = len(s)
        depth = 1
        as_start = -1
        while j < n and depth > 0:
            ch = s[j]
            if ch == "'":
                j = _skip_sql_string(s, j)
            elif s.startswith('/*', j) or s.startswith('--', j):
                j = _skip_sql_comment(s, j)
            elif ch == '(':
                depth += 1
                j += 1
            elif ch == ')':
                depth -= 1
                j += 1
            else:
                if as_start < 0 and depth == 1 and ch in 'Aa' and _is_as_word(s, j):
                    as_start = j
                j += 1
        if depth != 0:
            return s  # 括号不平衡：放弃结构剥除，交白名单兜底
        close = j - 1
        if as_start >= 0:
            out.append(_strip_cast_types(s[m.end():as_start]))
            out.append(')')
        else:
            out.append(s[m.end():close + 1])
        pos = close + 1


def _strip_sql_noise(sql: str) -> str:
    """去掉会干扰字段/表抽取的 SQL 结构，避免误判。

    处理：
    1. 字符串字面量/注释内容抹空——其中残留的 AS/FROM 不是 SQL 结构
    2. EXTRACT(x FROM y) —— 里面的 FROM 是函数语法，不是表引用
    3. CAST(<expr> AS <type>) / ::type(精度) —— 类型转换的 AS <type> 不是字段别名；
       结构化深度剥除（类型名开放集，枚举白名单必漏），白名单只兜烂 SQL 降级路径
    """
    s = _mask_literals_and_comments(sql)
    # 2. EXTRACT(<part> FROM <expr>) —— 把 " FROM " 在 EXTRACT 上下文里替换掉
    s = re.sub(r'(EXTRACT\s*\([^)]*?)\bFROM\b', r'\1__FROM__', s, flags=re.IGNORECASE)
    # 3a. CAST(<expr> AS <type>) —— 结构化剥除（配对括号内相对深度 0 的 AS，不认类型名）
    s = _strip_cast_types(s)
    # 3b. ANSI 类型名白名单——仅在结构剥除降级（括号不平衡）时兜底
    s = re.sub(r'\bAS\s+(BIGINT|INT|INTEGER|SMALLINT|DECIMAL|NUMERIC|FLOAT|DOUBLE|REAL|'
               r'VARCHAR|NVARCHAR|CHAR|TEXT|DATE|DATETIME|TIMESTAMP|BOOLEAN|BOOL|'
               r'INTERVAL|JSON|BLOB|BYTEA|SERIAL)\b',
               '', s, flags=re.IGNORECASE)
    # 3c. postgres 风格的类型转换 ::type（含精度括号）
    s = re.sub(r'::\w+(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?', '', s)
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


def parse_join_pairs(text: str) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    """解析关联条件文本里的等值对：a.x = b.y 形态。

    返回 [((alias, col), (alias, col)), ...]。大小写归一（alias/col 都 lower）。
    解析不出的文本（自然语言描述/复杂表达式）直接跳过——宁放过不误报，
    由调用方决定对未覆盖文本的处理（precheck 会 warn 提示无法自动对账）。

    支持一段文本含多个条件（"a.x=b.x and a.y=b.y"）；
    不等值（!=/<）和函数包装（TO_CHAR(a.x)=b.y）不匹配——只认裸等值。
    """
    if not text:
        return []
    pairs = []
    pat = re.compile(
        r'\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)')
    for m in pat.finditer(text):
        left = (m.group(1).lower(), m.group(2).lower())
        right = (m.group(3).lower(), m.group(4).lower())
        pairs.append((left, right))
    return pairs


def extract_table_refs_raw(sql: str) -> list[str]:
    """提取 FROM/JOIN 后的原始表引用（保留 schema 前缀形态，供"必须带 schema"校验用）。

    与 extract_from_tables（剥前缀取短名）互补：这里返回原文引用——
    'ods.a_f' 原样返回，'a_f'（裸名）也原样返回，由调用方判定是否缺 schema。
    """
    refs = []
    sql = _strip_sql_noise(sql)
    for pattern in [r'\bFROM\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)',
                    r'\bJOIN\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)']:
        for m in re.finditer(pattern, sql, re.IGNORECASE):
            refs.append(m.group(1))
    return refs


def parse_cte_bodies(sql: str) -> dict[str, str]:
    """解析 WITH 子句里每个 CTE 的定义体：{cte名: 体文本}。

    复用 split_cte_main 的括号深度扫描策略：识别顶层 CTE 头（name AS (），
    记录其配对右括号之间的体。没有 WITH 返回空 dict。
    """
    m = re.search(r'\bWITH\b', sql, re.IGNORECASE)
    if not m:
        return {}
    body = sql[m.end():]
    cte_bodies: dict[str, str] = {}
    depth = 0
    cur_name = ""
    body_start = -1
    i = 0
    n = len(body)
    in_string = False
    string_char = ''
    while i < n:
        ch = body[i]
        # 字符串字面量内的括号不参与深度计数
        if in_string:
            if ch == string_char:
                in_string = False
            i += 1
            continue
        if ch in ("'", '"'):
            in_string = True
            string_char = ch
            i += 1
            continue
        if ch == '(':
            if depth == 0:
                # 顶层 '(' 前应是 "<name> AS "（允许空白/逗号分隔）
                head = re.search(r'([A-Za-z_]\w*)\s+AS\s*$', body[max(0, i - 200):i])
                if head:
                    cur_name = head.group(1).lower()
                    body_start = i + 1
            depth += 1
            i += 1
            continue
        if ch == ')':
            depth -= 1
            if depth == 0 and cur_name and body_start > 0:
                cte_bodies[cur_name] = body[body_start:i]
                cur_name = ""
                body_start = -1
            i += 1
            continue
        if depth == 0:
            if ch in (',', ' ', '\t', '\n', '\r'):
                i += 1
                continue
            hm = re.match(r'([A-Za-z_]\w*)\s+AS\s*\(', body[i:])
            if hm:
                # 跳过头部，让 '(' 的深度计数接管（下一轮 ch=='(' 时 body_start 才设）
                i += hm.end() - 1
                continue
            break
        i += 1
    return cte_bodies


def cte_projection_names(cte_body: str) -> set[str]:
    """提取 CTE 定义体的投影列名集合（小写）。

    取两类：AS 别名 + 体文本里所有 `别名.列` 的列名（SELECT t.a 无 AS 时投影名即 a）。
    宁多勿漏——JOIN 条件里的列也进集，只会放行不会误报。
    """
    names = set()
    for m in re.finditer(r'\bAS\s+([A-Za-z_]\w*)', cte_body, re.IGNORECASE):
        names.add(m.group(1).lower())
    for m in re.finditer(r'\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)', cte_body):
        names.add(m.group(2).lower())
    return names


# ============================================================
# 关联条件引用 + 逻辑字段出处（precheck 入口闸 / assemble_ts N30 共用）
# ============================================================
_QUALIFIED_REF = re.compile(r'\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)')
_BARE_REF = re.compile(r'(?<![\w.])([A-Za-z_]\w*)\s*=\s*(?:\'[^\']*\'|[-+]?\d+(?:\.\d+)?)')
_FUNC_KEYWORD = (r'ROW_NUMBER|RANK|DENSE_RANK|NTILE|LAG|LEAD|SUBSTR|SUBSTRING|'
                 r'CASE|COALESCE|NVL|TO_CHAR|TO_DATE|CAST|CONCAT|OVER')


def extract_condition_field_refs(condition: str) -> tuple[list, list]:
    """关联条件里的字段引用集（引用≠证据）。

    返回 (qualified, bare)：
    - qualified: [(alias, col)] 别名限定引用（含等值对/函数参数里的一切 a.b 形态，小写）
    - bare: [name] 裸字段 = 字面量 形态（rn=1 / del_flag='N'，小写；排除别名限定的列名）
    """
    qualified = [(a.lower(), c.lower()) for a, c in _QUALIFIED_REF.findall(condition or "")]
    bare = [b.lower() for b in _BARE_REF.findall(condition or "")]
    return qualified, bare


def find_field_provenance(field: str, texts: list, mention_texts: list = None) -> str:
    """在文本里找 field 的"定义语境"出处，返回最强档（无则空串）。

    档位（强→弱）：alias（AS field 别名定义）/ assign（field = 表达式，RHS 非字面量）/
    cooccur（函数关键字与 field 同文本单元共现）/ mention（field 出现在说明性文本里）。
    纯引用（field = 字面量）不算证据——由 assign 的 RHS 排除保证。

    texts：强档语境（可含条件自身——"ROW_NUMBER() OVER(...)=1" 这类自文档写法）。
    mention_texts：说明性文本（字段行 transform_detail/remark）——条件自身不进这档，
    否则引用会命中自己（a.rn=1 里的 rn 不是出处）。
    """
    f = re.escape(field)
    for t in texts:
        if re.search(rf'\bAS\s+{f}\b', t, re.IGNORECASE):
            return "alias"
    for t in texts:
        # field = 非字面量（函数调用/标识符运算）→ 定义性赋值；= 'N'/=1 是引用
        if re.search(rf'(?<![\w.]){f}\s*=\s*(?!\s*(?:\'[^\']*\'|"[^"]*"|[-+]?\d))', t):
            return "assign"
    pat = re.compile(rf'\b{f}\b', re.IGNORECASE)
    for t in texts:
        if pat.search(t) and re.search(_FUNC_KEYWORD, t, re.IGNORECASE):
            return "cooccur"
    for t in (mention_texts or []):
        if pat.search(t):
            return "mention"
    return ""


def extract_qualified_refs(sql: str) -> list:
    """提取 SQL 文本里所有 `别名.列` 限定引用 [(alias, col)]（小写）。

    与 extract_condition_field_refs（条件专用，含裸字面量）不同：这个面向整段 SQL，
    供字段存在性核对遍历用。
    """
    return [(a.lower(), c.lower()) for a, c in _QUALIFIED_REF.findall(sql or "")]


_ASSIGN_TRIVIAL_KEYWORDS = {"CURRENT_TIMESTAMP", "SYSDATE", "CURRENT_DATE", "NULL"}


def is_trivial_assign_detail(detail: str) -> bool:
    """赋值字段的 detail 是否为平凡字面量/变量（'N' / 0 / ${PARAM} / CURRENT_TIMESTAMP / 空）。

    非平凡（CASE WHEN / 函数 / 运算 / 字段引用）= 需要翻译（不是"错标"的语义判定——
    自然语言在输入层不可判，错标识别后置到 designer 翻译之后）：assemble_ts build_field
    路由用（非平凡→加工路径，detail 作口径底稿交 coder 翻译）+ N35 校验用（赋值+非平凡
    +无 designer 翻译 → error）+ build_compact ⚠ 标记用（designer 第一眼翻译）。
    """
    d = (detail or "").strip()
    if not d or d in ("-", "无", "\\"):
        return True
    if re.fullmatch(r"'[^']*'", d):
        return True
    if re.fullmatch(r"\$\{[^}]+\}", d):
        return True
    if re.fullmatch(r"[-+]?\d+(\.\d+)?", d):
        return True
    if d.upper() in _ASSIGN_TRIVIAL_KEYWORDS:
        return True
    return False
