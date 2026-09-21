#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diagnose_fanout——关联质量定位器。一个工具两个时点，按 **ts 是否已产** 选模式：

  - **评估期（无 ts.json）→ --edge 疑点边交集式试算**：designer 评估层上报"从表键不唯一"
    疑点后，engineer 做实**当前影响**给人做材料（重复键 ∩ 对侧键 → 当前命中 K 组/
    零命中+未来命中即膨胀风险披露）。**无需 --ts**——ts 没产正是用本模式的原因。
  - **有 ts.json（UT 回路 6b / 闸口①）→ --rule 单规则深查 / --all 批量**：逐表键唯一性+
    声明对照+join_safety 断言对照+整体试算严重性。

★ 解决什么：关联的三类边界场景给确定性事实（engineer 质检用，判断归人）：
  1. 类型不一致 → 1b precheck 关联键类型对账（人决策），不在本工具；
  2. 唯一性（发散）→ 声明语义精确计数（before/after 直接量结果，无取样噪声）
     + 确认发散后逐表键唯一性归因（哪张表贡献）；
  3. 值域/内容不一致（静默空关联）→ per-join 关联不上率 + 未命中键样例。

  遵守声明条件（as-designed）：复合键聚合、joins[].filter / join_safety.join_filter /
  规则 filter / condition 字面量项全部并入；**字面量值形态按列类型开局修正**
  （char 列裸数值 = 声明错误，按 '值' 执行并披露——真实 ETL 照写会炸）。
  单表故障隔离（条件失败=发现不下伪结论/跳过续跑）+全函数 fail-soft 终层（内部缺陷 exit 0 不阻断）；依赖中间表的规则闸口①不可查（表未建，UT 兜底）。
  --edge：只测疑点边不构造链（链级=设计后 --all 的活）；交集式无 JOIN（查询自身不发散）；
  产物落 _internal/diagnose/（engineer 材料），永不回写 view（designer 输入面零结论级内容）。

用法:
  # 评估期（无 ts）——疑点边试算（A=对侧，B=疑点侧；参数抄 designer 评估结果的事实行）:
  python diagnose_fanout.py --rs {rs路径} --edge \\
      --schema-a ods --table-a main_f --key-a order_id \\
      --schema-b ods --table-b dim_cust --key-b cust_code --where-b "status=1"

  # UT 回路 6b（有 ts）——单规则深查:
  python diagnose_fanout.py --ts {ts路径} --rule R0001 [--top 5]

  # 闸口①批量（有 ts）:
  python diagnose_fanout.py --ts {ts路径} --all

退出码: 0=诊断完成（报告 stdout + 落 _internal/diagnose/）, 1=用法/文件错, 2=无库（环境归人）
"""

import sys
import re
import json
import argparse
from pathlib import Path

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))

from sql_parse import parse_join_pairs


def _unwrap_parens(t: str) -> str:
    """剥**配对**的包裹括号（首 ( 的闭合点恰在末位才剥一层）。

    裸 strip("()") 不认配对——`(a.x in ('1','2'))` 会把外层 ) 和 IN 收括号 ) 一起
    剥掉拼出 `('1','2'` 残缺 SQL（2026-09-15 内网实证：关联条件带 IN 直接炸）。"""
    t = t.strip()
    while t.startswith("(") and t.endswith(")"):
        depth = 0
        for i, ch in enumerate(t):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(t) - 1:
                    return t  # 首 ( 中途已闭合——不是包裹括号（如 (a=1) or (b=2)）
        t = t[1:-1].strip()
    return t


def _split_terms(text: str) -> list[str]:
    """把 condition/filter 按**顶层** AND 拆项（括号深度感知；含中文连词 且/并且）。

    括号内的 and 不拆（包裹括号 `(a=1 and b in (1,2))` 整项保留+剥包裹后内含 and
    合法；IN 列表内更不拆）——旧版裸 split 在包裹括号内部切开，两半各带残括号；
    旧版 strip("()") 还会剥掉 IN 收括号。两bug 2026-09-15 修。"""
    s = str(text or "")
    # mask 括号内内容后找顶层 and 分割点，按坐标切原串（保内容零失真）
    masked_chars, depth = [], 0
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        masked_chars.append(ch if depth == 0 else "\x00")
    masked = "".join(masked_chars)
    spans = [m.span() for m in re.finditer(r"\s+and\s+|并且|且", masked, flags=re.IGNORECASE)]
    parts, prev = [], 0
    for a, b in spans:
        parts.append(s[prev:a])
        prev = b
    parts.append(s[prev:])
    return [_unwrap_parens(p) for p in parts if p.strip()]


def _terms_for_alias(terms: list[str], alias: str) -> list[str]:
    """归属某别名的项：项里出现 alias. 引用才算（无限定词的项归属不了——宁放过）。"""
    a = alias.lower()
    return [t for t in terms if re.search(rf"\b{re.escape(a)}\.", t, re.IGNORECASE)]


def _literal_terms(condition: str, alias: str) -> list[str]:
    """condition 里 `别名.列 = 字面量` 形态的项（parse_join_pairs 只认表间等值对，这类要单独收）。"""
    a = alias.lower()
    pat = re.compile(rf"\b({re.escape(a)})\.([A-Za-z_]\w*)\s*=\s*('[^']*'|[-+]?\d+(?:\.\d+)?)",
                     re.IGNORECASE)
    return [f"{m.group(1)}.{m.group(2)} = {m.group(3)}" for m in pat.finditer(condition or "")]


def _fmt_val(v) -> str:
    """样例键值回填 SQL：数值裸写，其余单引号（内部引号转义）。"""
    s = "" if v is None else str(v)
    if re.fullmatch(r"[-+]?\d+(\.\d+)?", s):
        return s
    return "'" + s.replace("'", "''") + "'"


_CHAR_FAMILY_PAT = re.compile(r"(char|text)", re.IGNORECASE)


def _load_coltypes(ts_path: Path) -> dict:
    """schema_cache 的 {"schema.table": {col: type}}（字面量值形态判断用；
    precheck 连库时产出，全小写键）。无 cache 返回空 dict（形态修正退化为原样）。"""
    p = ts_path.parent / "_internal" / "schema_cache.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8")).get("tables") or {}
        return {str(k).lower(): {str(c).lower(): str(t) for c, t in (v or {}).items()}
                for k, v in raw.items() if isinstance(v, dict)}
    except Exception:
        return {}


def _fix_literal_form(text: str, alias: str, binding: dict, coltypes: dict) -> tuple[str, list[str]]:
    """裸数值字面量按列类型**开局**修正为字符串形态（用户定调：char 列 = 3309 是
    声明错误——隐式转换炸弹；本工具按 '3309' 执行拿到结论，声明 bug 另行披露，
    真实 ETL 照写会炸）。未知列类型保持原样（退化为原样回放）。返回 (修正后文本, 披露)。"""
    notes = []
    ent = binding.get(alias.lower())
    if not ent:
        return text or "", notes
    sch, tbl = ent
    ctypes = coltypes.get(f"{sch}.{tbl}".lower(), {})
    pat = re.compile(rf"\b({re.escape(alias.lower())})\.([A-Za-z_]\w*)(\s*=\s*)([-+]?\d+(?:\.\d+)?)",
                     re.IGNORECASE)

    def _sub(m):
        col = m.group(2).lower()
        ct = ctypes.get(col)
        if ct and _CHAR_FAMILY_PAT.search(ct):
            notes.append(f"{m.group(1)}.{col} = {m.group(4)}（列类型 {ct}）→ 已按 '{m.group(4)}' 执行；"
                         f"声明本身需修正（真实 ETL 照写触发隐式转换会炸）")
            return f"{m.group(1)}.{m.group(2)}{m.group(3)}'{m.group(4)}'"
        return m.group(0)

    return pat.sub(_sub, text or ""), notes


def _clean_declared(text: str) -> str:
    """剥 BA 声明里的 join 类型前缀与冒号（内网实证：mapping 里写 'left join ： t.xx=s.xx'，
    designer 条件 't.xx=s.xx'——不剥前缀文本比对必不等，把整条声明误报成'漏掉的条件'）。"""
    s = str(text or "").strip()
    s = re.sub(r"^\s*(?:(?:left|right|full|inner|cross|outer)\s+)*join\b\s*[:：]?\s*",
               "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*on\b\s*", "", s, flags=re.IGNORECASE)
    return s.strip()


def _decl_parseable(mapping_decl: str) -> bool:
    """声明可解析性（宁缺勿错）：清洗后仍解析不出任何 '别名.列=别名.列' 等值对
    （纯自然语言描述——BA 写'订单表关联客户表取最新'这类）→ 对照无意义，跳过
    不比（2026-09-03 用户预判的误报源之一）。"""
    if not mapping_decl:
        return False
    return bool(parse_join_pairs(_clean_declared(mapping_decl)))


def _load_mapping_joins(ts_path: Path) -> dict:
    """BA 的关联声明（rs_input 实体级 join_condition，按表短名，**清洗后**——设计 vs 输入
    归属判别的依据。约定路径 ts 同级 _internal/rs_input.json 自动探测；探测不到
    返回空 dict（对照降级为'声明不可得'，事实照报不猜）。"""
    p = ts_path.parent / "_internal" / "rs_input.json"
    try:
        sts = json.loads(p.read_text(encoding="utf-8")).get("source_tables") or []
        return {str(st.get("source_table") or "").rsplit(".", 1)[-1].lower():
                _clean_declared(st.get("join_condition"))
                for st in sts if st.get("source_table")}
    except Exception:
        return {}


def _norm_term(term: str) -> str:
    """条件项归一——声明对照用（宁缺勿错：把常见写法差异归到同形，等价才可断言）。
    ① 小写；② 引号串外的空白全去（'t.x = s.x'≡'t.x=s.x'，串内空白保留）；
    ③ 纯两操作数等值项两侧排序（'s.x=t.x'≡'t.x=s.x'——SQL 等价）。"""
    s = str(term).strip().lower()
    segs = re.split(r"('[^']*'|\"[^\"]*\")", s)
    s = "".join(seg if i % 2 else re.sub(r"\s+", "", seg) for i, seg in enumerate(segs))
    eq = re.fullmatch(r"([a-z_][\w.]*)=([a-z_][\w.]*)", s)
    if eq:
        a, b = sorted((eq.group(1), eq.group(2)))
        return f"{a}={b}"
    return s


def _dup_anatomy(db: "_Db", schema: str, table: str, cols: list[str],
                 key_vals: dict, limit: int = 3) -> str:
    """重复组解剖：top 重复键取组内整行，报**组内值有差异的列**——人一眼看出
    该补什么收敛/是不是撞键（事实披露，不猜收敛方式）。"""
    cond = " AND ".join(f"{c} = {_fmt_val(key_vals.get(c))}" for c in cols)
    try:
        rows = db.rows(f"SELECT * FROM {schema}.{table} WHERE {cond} LIMIT {limit}")
    except RuntimeError:
        return ""
    if len(rows) < 2:
        return ""
    diffs = []
    for col in rows[0]:
        vals = [str(r.get(col)) for r in rows]
        if len(set(vals)) > 1:
            diffs.append(f"{col}({'|'.join(vals)})")
    return "、".join(diffs[:8])


def _fix_literal_form_any(text: str, binding: dict, coltypes: dict) -> tuple[str, list[str]]:
    """任意 别名.列 = 裸数值 的形态修正（规则 filter 整段用——filter 可引用多别名）。
    语义同 _fix_literal_form：char 列裸数值=声明错误，开局按 '值' 执行并披露。"""
    notes = []
    pat = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)(\s*=\s*)([-+]?\d+(?:\.\d+)?)")

    def _sub(m):
        alias, col = m.group(1).lower(), m.group(2).lower()
        ent = binding.get(alias)
        if not ent:
            return m.group(0)
        ct = coltypes.get(f"{ent[0]}.{ent[1]}".lower(), {}).get(col)
        if ct and _CHAR_FAMILY_PAT.search(ct):
            notes.append(f"{m.group(1)}.{col} = {m.group(4)}（列类型 {ct}）→ 已按 '{m.group(4)}' 执行；"
                         f"声明本身需修正（真实 ETL 照写触发隐式转换会炸）")
            return f"{m.group(1)}.{m.group(2)}{m.group(3)}'{m.group(4)}'"
        return m.group(0)

    return pat.sub(_sub, text or ""), notes



def _safety_index(rule: dict, rule_alias_map: dict) -> dict:
    """join_safety 关联级索引：{别名: 条目}（2026-09-15 决策 B——关联是一等分析单位）。

    alias 键一一对应；老条目无 alias 按表名兜底（同表多条目无 alias 无法区分——
    每个别名都标"声明歧义"提示人补 alias，宁披露不猜）。"""
    items = [js for js in (rule.get("join_safety") or []) if isinstance(js, dict)]
    by_alias, by_table, multi = {}, {}, set()
    for js in items:
        sa = (js.get("alias") or "").strip().lower()
        st = str(js.get("table") or "").rsplit(".", 1)[-1].lower()
        if sa:
            by_alias[sa] = js
        else:
            if st in by_table:
                multi.add(st)
            by_table[st] = js
    out = {}
    for j in (rule.get("joins") or []):
        if not isinstance(j, dict):
            continue
        ja = (j.get("alias") or "").strip().lower()
        if not ja:
            continue
        if ja in by_alias:
            out[ja] = by_alias[ja]
            continue
        _ent = rule_alias_map.get(ja) or ("", "")
        st = (_ent[-1] if isinstance(_ent, (tuple, list)) else str(_ent)).rsplit(".", 1)[-1].lower()
        if st in by_table:
            out[ja] = by_table[st] if st not in multi else {
                **by_table[st], "_ambiguous": True}
    return out

class _Db:
    """单连接走**目标 schema 的数据源**（部署事实：目标 schema 数据源有全部来源表
    权限，逐源 schema 连库会报"schema 不在 db 配置"——explore.py 同款语义）。
    表名在各 SQL 里带自己的 schema 限定，跨 schema 同连接查。"""

    def __init__(self, connect_schema: str):
        from dws_db import create_executor_for_schema
        self._ex = create_executor_for_schema(connect_schema, role="etl")
        if not self._ex.test_connection():
            raise ConnectionError(f"连不上目标 schema={connect_schema} 的数据源")

    def one(self, sql: str) -> dict:
        r = self._ex.execute(sql)
        if not r.success:
            raise RuntimeError(f"查询失败: {(r.error or '')[:200]} | SQL: {sql[:150]}")
        return (r.rows or [{}])[0]

    def rows(self, sql: str) -> list[dict]:
        r = self._ex.execute(sql)
        if not r.success:
            raise RuntimeError(f"查询失败: {(r.error or '')[:200]} | SQL: {sql[:150]}")
        return r.rows or []

    def close(self):
        try:
            self._ex.close()
        except Exception:
            pass


def _strip_alias(term: str, alias: str) -> str | None:
    """单表查询的 WHERE 项剥掉别名前缀（s.is_current=1 → is_current=1——FROM 没写
    别名，带前缀直接 SQL 报错）。剥完仍含其他 别名. 引用的项归属不了，跳过（宁放过）。"""
    stripped = re.sub(rf"\b{re.escape(alias.lower())}\.", "", term, flags=re.IGNORECASE)
    if re.search(r"\b[A-Za-z_]\w*\.", stripped):
        return None
    return stripped


def _err_brief(e, limit: int = 120) -> str:
    """报错原文展示：剥掉自带 的 SQL 回显尾巴（截断难读），限长。"""
    return str(e).split("| SQL:")[0].strip()[:limit]


def _err_classify(err_text) -> str:
    """报错分类提示（2026-09-15 内网反馈"报错无提示，分不清脚本问题还是输入问题"）：
    按报错原文给方向提示——声明条件的问题（人核写法/字面量）vs 环境问题（权限/网络）。
    只提示不定罪（宁放过）。"""
    low = str(err_text).lower()
    if any(k in low for k in ("syntax", "语法", "or near")):
        return "【提示】语法错——大概率声明条件里的写法 DWS 不认（函数名/括号/全角字符），核条件原文"
    if any(k in low for k in ("function", "函数", "does not exist", "不存在")):
        if "column" in low or "字段" in low or "字段" in str(err_text):
            return "【提示】列不存在——声明条件引用的字段拼写/归属问题，对照 mapping 核字段名"
        return "【提示】函数不存在——声明条件用的函数 DWS 不支持，核函数名（大小写/方言）"
    if any(k in low for k in ("type", "类型", "invalid input", "无效")):
        return "【提示】类型不匹配——字面量形态与列类型不符（如 varchar 列=裸数值），核条件里的值写法"
    if any(k in low for k in ("permission", "denied", "权限")):
        return "【提示】权限问题——环境侧（账号/库权限），非输入问题"
    return ""


def _constructed_skip(j: dict, own: list, where: str, alias: str, tmp_aliases: set):
    """构造性唯一免实测判别（2026-09-21 用户实报：闸口①对开窗取最新关联弹"查询失败"误导人）：
    ①关联对象是中间表——闸口①表未建/属设计构造产物；②条件引用 joins.derived_fields 声明的
    派生字段（开窗序号 rn 等）——非物理列，对物理表实测必然列不存在。两形态唯一性都由设计
    构造保证（开窗 partition 键=关联键时 rn=1 每组一条，数学唯一非统计唯一），出免测结论行
    不发起物理查询（静默跳过像"检查没了"）；未命中声明的列不存在照旧弹（真幻觉列归 N38 域）。
    返回 None=照常实测；str=免测理由。"""
    if alias in tmp_aliases:
        return "中间表（设计构造产物，闸口①未建）"
    dv = j.get("derived_fields") if isinstance(j, dict) else None
    names = {str(k).strip().lower() for k in dv} if isinstance(dv, dict) else set()
    if not names:
        return None
    hit = {str(c).strip().lower() for c in own} & names
    if not hit and where:
        hit = {w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", where)} & names
    if hit:
        return f"条件含设计构造字段 {sorted(hit)}（joins.derived_fields 声明）"
    return None


def _cast_err_hint(err_text) -> str:
    """识别隐式转换类报错（回放声明条件时字面量与列类型不匹配——如 varchar 列
    = 数值字面量，内核把列值隐式 cast 成 numeric，脏值即炸。这本身是诊断发现：
    条件独立执行都跑不通，真实 ETL 照写同样炸，闸口①提前抓到）。"""
    low = str(err_text).lower()
    if "invalid input" in low or "无效" in low:
        return "（疑似声明条件的字面量与列类型不匹配触发隐式转换——该条件独立执行已跑不通，真实 ETL 照写同样炸，闸口①提前抓到）"
    return ""


def _key_stat(db: _Db, schema: str, table: str, cols: list[str], where: str) -> dict:
    """COUNT(1) vs 组合键唯一数（NULL 键行单独数——NULL 不参与 join 不会发散）。
    复合键用子查询先 DISTINCT 再计数——DWS 的 COUNT(DISTINCT) 只收单表达式，
    count(distinct a,b) 报错（2026-09-18 内网实证）。"""
    key = ", ".join(cols)
    # NULL 键行数用 CASE（GaussDB=PG9.2 内核，无 FILTER 子句）——NULL 不参与 join 不会发散
    # COUNT(1) 而非 COUNT(*)（平台口径，性能更合理）
    null_cond = " OR ".join(f"{c} IS NULL" for c in cols)
    where_part = f" WHERE {where}" if where else ""
    if len(cols) > 1:
        uniq_expr = (f"(SELECT COUNT(1) FROM (SELECT DISTINCT {key} "
                     f"FROM {schema}.{table}{where_part}) AS _dx)")
    else:
        uniq_expr = f"COUNT(DISTINCT {cols[0]})"
    sql = (f"SELECT COUNT(1) AS total, {uniq_expr} AS uniq, "
           f"SUM(CASE WHEN {null_cond} THEN 1 ELSE 0 END) AS nulls "
           f"FROM {schema}.{table}{where_part}")
    row = db.one(sql)
    return {"total": int(row.get("total") or 0), "uniq": int(row.get("uniq") or 0),
            "nulls": int(row.get("nulls") or 0)}


def _dup_samples(db: _Db, schema: str, table: str, cols: list[str], where: str, top: int) -> list[dict]:
    key = ", ".join(cols)
    sql = (f"SELECT {key}, COUNT(1) AS c FROM {schema}.{table}")
    if where:
        sql += f" WHERE {where}"
    sql += (f" GROUP BY {key} HAVING COUNT(1) > 1 ORDER BY c DESC, {key} LIMIT {top}")
    return db.rows(sql)


def _partner_hits(db: _Db, p_schema: str, p_table: str, p_cols: list[str],
                  samples: list[dict], cols: list[str], p_where: str = "") -> int:
    """实锤确认：重复键样例回伙伴表查命中行数（带伙伴侧过滤——不带会把已被
    规则 filter 排除的行误计为命中）。未命中=不膨胀，或键内容形态不一致（空关联维度）。"""
    tuples = []
    for s in samples[:5]:
        vals = ", ".join(_fmt_val(s.get(c)) for c in cols)
        tuples.append(f"({vals})")
    pkey = ", ".join(p_cols)
    sql = (f"SELECT COUNT(1) AS hits FROM {p_schema}.{p_table} "
           f"WHERE ({pkey}) IN ({', '.join(tuples)})")
    if p_where:
        sql += f" AND {p_where}"
    return int(db.one(sql).get("hits") or 0)


def _join_counts(db: _Db, rule: dict, binding: dict, driving: str, tmp_aliases: set,
                 coltypes: dict, rule_filter_text: str, top: int,
                 lines: list, verdicts: list) -> str:
    """声明语义精确计数（闸口①满配核心）：before/after 直接量结果——膨胀（after>before）
    与 INNER 丢行（after<before）无取样噪声；LEFT join 逐个披露关联不上率+未命中键样例
    （值域/内容不一致维度）。返回 fanout / clean / skip（依赖中间表或查询失败）。"""
    joins_decl = rule.get("joins") or []
    if not joins_decl or not driving or driving not in binding:
        return "none"
    # 中间表闸口①未建（DDL 在步骤4）——天然边界，UT 兜底；含设计构造字段（开窗序号等，
    # joins.derived_fields 声明）的边物理表重放语义已变（无开窗=全表行），同样不可重放——
    # 2026-09-21 补：此前这类边整体试算弹"查询失败跳过"，把合法设计误导成故障
    involved = [driving] + [(j.get("alias") or "").strip().lower() for j in joins_decl]
    if any(a in tmp_aliases or a not in binding for a in involved) \
            or any(isinstance(j.get("derived_fields"), dict) and j["derived_fields"]
                   for j in joins_decl):
        lines.append("[声明计数] 依赖中间表（reads tmp，闸口①表未建）/条件含设计构造字段"
                     "（开窗等不可物理重放）或别名未绑定——跳过，UT 兜底")
        return "skip"
    d_sch, d_tbl = binding[driving]
    where_txt = f" WHERE {rule_filter_text}" if (rule_filter_text or "").strip() else ""
    # join 侧限定并入（2026-09-15 修复：此前整体试算只并规则级 filter——拉链类限定
    # [is_current=1] 没进 WHERE，试算行数虚高误报膨胀；与逐表段同口径：
    # joins[].filter + join_safety.join_filter 全集）。before（驱动单表）不含 join 侧限定。
    _safety_by_alias = _safety_index(rule, binding)  # 关联级（决策 B）
    _join_terms_by_alias: dict[str, list[str]] = {}
    for j in joins_decl:
        alias = (j.get("alias") or "").strip().lower()
        sch, tbl = binding[alias]
        raw_terms = []
        _saf = _safety_by_alias.get(alias) or {}
        for _src in (j.get("filter") or "", _saf.get("join_filter") or ""):
            if (_src or "").strip():
                _fixed, _fn = _fix_literal_form_any(_src, binding, coltypes)
                for n in _fn:
                    if f"[字面量形态] {n}" not in "\n".join(lines):
                        lines.append(f"[字面量形态] {n}")
                raw_terms.append(_fixed)
        if raw_terms:
            _join_terms_by_alias[alias] = [t for t in raw_terms if t.strip()]
    _all_join_terms = [t for ts_ in _join_terms_by_alias.values() for t in ts_]
    after_where_txt = where_txt
    if _all_join_terms:
        _extra = " AND ".join(_all_join_terms)
        after_where_txt = f" WHERE {' AND '.join(filter(None, [rule_filter_text.strip(), _extra]))}"
    join_parts, jt_by_alias = [], {}
    for j in joins_decl:
        alias = (j.get("alias") or "").strip().lower()
        sch, tbl = binding[alias]
        cond, fix_notes = _fix_literal_form(j.get("condition") or "", alias, binding, coltypes)
        for n in fix_notes:  # 逐表段已披露过的不再重复
            if f"[字面量形态] {n}" not in "\n".join(lines):
                lines.append(f"[字面量形态] {n}")
        jt = (j.get("type") or "").strip().upper() or "INNER JOIN"
        jt_by_alias[alias] = jt
        join_parts.append(f"{jt} {sch}.{tbl} {alias} ON ({cond})")
    try:
        before = int(db.one(f"SELECT COUNT(1) AS jc FROM {d_sch}.{d_tbl} {driving}{where_txt}").get("jc") or 0)
        after = int(db.one(f"SELECT COUNT(1) AS jc FROM {d_sch}.{d_tbl} {driving} "
                           + " ".join(join_parts) + after_where_txt).get("jc") or 0)
    except RuntimeError as e:
        lines.append(f"[声明计数] 查询失败跳过（逐表统计照常）：{_err_brief(e)}{_cast_err_hint(e)}")
        return "skip"
    fanout, loss = after - before, before - after
    if fanout > 0:
        verdicts.append(f"整体试算膨胀 {fanout} 行（驱动 {before} → 关联后 {after}）")
        lines.append(f"[整体试算] 按声明条件把全部关联拼起来数行数：驱动 {before} 行 → 关联后 {after} 行"
                     f"（膨胀 {fanout} 行——当前数据下会实际膨胀）")
        return "fanout"
    if loss > 0:
        verdicts.append(f"整体试算丢行 {loss} 行（驱动 {before} → 关联后 {after}——INNER 未命中或 filter 引用 join 表列使 LEFT 退化）")
        lines.append(f"[整体试算] 按声明条件把全部关联拼起来数行数：驱动 {before} 行 → 关联后 {after} 行"
                     f"（⚠ 丢行 {loss} 行——INNER 未命中，或规则 filter 引用了 join 表列使 LEFT 退化）")
    else:
        _note = ""
        if loss == 0:
            # 未膨胀但逐表曾检出键不唯一=数据未命中发散键（未来命中即发散）——风险披露
            # （2026-09-15 内网案例：主表编码当前固定未命中，designer 曾以此推断压掉疑点漏报）
            _nu_tables = []
            for _i, _j in enumerate(joins_decl, 1):
                _al = (_j.get("alias") or "").strip().lower()
                _st = binding.get(_al)
                if not _st:
                    continue
                _tbl_short = (_st[-1] if isinstance(_st, (tuple, list)) else str(_st)).rsplit(".", 1)[-1].lower()
                _saf = _safety_by_alias.get(_al) or {}
                _lim = " AND ".join(filter(None, [rule_filter_text.strip()]
                                            + [t_ for t_ in [j.get("filter") or "" for j in joins_decl
                                                             if isinstance(j, dict) and (j.get("alias") or "").strip().lower() == _al]
                                            + [_saf.get("join_filter") or ""]]))
                # 逐表唯一性速查（重用键统计）——只对曾报不唯一的表做（本函数上下文拿不到逐表结论，
                # 简化：查 join_safety 标 join_key_unique=false 的表）
                if _saf.get("join_key_unique") is False:
                    _nu_tables.append(f"JOIN {_i}（{_tbl_short}，声明不唯一）")
            if _nu_tables:
                _note = (f"；⚠ 驱动数据当前未命中发散键（{'、'.join(_nu_tables)}）——"
                         f"现在不发散≠未来不发散，命中即膨胀——闸口①人判：修源端（含定收敛口径）"
                         f"/采纳已声明条件/知情接受（join_safety 留痕）")
        lines.append(f"[整体试算] 按声明条件把全部关联拼起来数行数：驱动 {before} 行 → 关联后 {after} 行（无膨胀无丢行{_note}）")
    # 空关联率（LEFT join 逐个——值域/内容不一致维度的系统性检查）
    for i, j in enumerate(joins_decl, 1):
        alias = (j.get("alias") or "").strip().lower()
        if not jt_by_alias.get(alias, "").startswith("LEFT"):
            continue
        sch, tbl = binding[alias]
        cond, _ = _fix_literal_form(j.get("condition") or "", alias, binding, coltypes)
        # 该 join 的限定并入（同口径：joins[].filter + join_safety.join_filter）
        _pw = " AND ".join(filter(None, [rule_filter_text.strip()]
                                  + _join_terms_by_alias.get(alias, [])))
        _pw_txt = f" WHERE {_pw}" if _pw else ""
        try:
            matched = int(db.one(f"SELECT COUNT(1) AS jc FROM {d_sch}.{d_tbl} {driving} "
                                 f"{jt_by_alias[alias]} {sch}.{tbl} {alias} ON ({cond}){_pw_txt}"
                                 ).get("jc") or 0)
        except RuntimeError:
            continue
        if before <= 0 or matched >= before:
            continue
        rate = (before - matched) * 100 // before
        lines.append(f"[空关联] JOIN {i} {sch}.{tbl}（{alias}）：关联不上率 {rate}%"
                     f"（{before - matched}/{before} 行无伙伴——值域/内容不一致或真无数据，闸口①人判）")
        pairs = parse_join_pairs(j.get("condition") or "")
        # 驱动侧列 = 条件里非本别名侧的列（未命中键样例用）
        dcols = list(dict.fromkeys(
            (lc if ra == alias else rc) for (la, lc), (ra, rc) in pairs
            if la == alias or ra == alias))
        if dcols:
            try:
                rows = db.rows(f"SELECT {', '.join(dcols)} FROM {d_sch}.{d_tbl} {driving} "
                               f"WHERE {(rule_filter_text + ' AND ') if (rule_filter_text or '').strip() else ''}"
                               f"NOT EXISTS (SELECT 1 FROM {sch}.{tbl} {alias} WHERE ({cond})) LIMIT 5")
                if rows:
                    lines.append("  未命中键样例：" + "、".join(
                        "|".join(str(r.get(c)) for c in dcols) for r in rows))
            except RuntimeError:
                pass
    return "clean"


def diagnose(ts_path: Path, rule_code: str, top: int = 5, db: "_Db | None" = None) -> tuple[list[str], str]:
    """跑诊断，返回 (报告行列表, 结论一句话)。异常上抛由 main 分流。
    db 传入则复用连接（批量模式单连接跑全部规则），不传入则自建自关。
    结构（闸口①与 6b 同构）：驱动自检 → 逐表【声明对照（设计 vs 输入归属的事实，
    全量做）+ 键唯一性(主判据) + join_safety 断言对照 + 重复组解剖 + 命中】→
    整体试算（当前数据严重性：膨胀/丢行/空关联）。只反馈事实，不猜收敛方式。"""
    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    rule = (ts.get("rules") or {}).get(rule_code) \
        or ((ts.get("init") or {}).get("rules") or {}).get(rule_code)
    if not rule:
        raise ValueError(f"ts 里没有规则 {rule_code}（查 ts.rules / ts.init.rules）")

    # alias → (schema, table)；tmp 别名（reads 中间表——闸口①未建）
    binding: dict[str, tuple[str, str]] = {}
    tmp_aliases: set = set()
    for st in rule.get("source_tables") or []:
        al = (st.get("alias") or "").strip().lower()
        if al:
            binding[al] = ((st.get("schema") or "").strip(), (st.get("table") or "").strip())
            if st.get("_from_reads"):
                tmp_aliases.add(al)
    joins = rule.get("join_safety") or []
    safety_by_alias = _safety_index(rule, binding)  # 关联级索引（决策 B）
    business_key = (ts.get("design") or {}).get("business_key") or []
    coltypes = _load_coltypes(ts_path)
    mapping_joins = _load_mapping_joins(ts_path)
    # 规则 filter 的字面量形态修正（R30 实证残留口：filter 原文裸回放两处——
    # 逐表 WHERE 归属项 + 整体试算的 WHERE；join 条件已有修正，filter 此前漏了）
    rule_filter_fixed, rf_notes = _fix_literal_form_any(rule.get("filter") or "", binding, coltypes)
    rule_filter_terms = _split_terms(rule_filter_fixed)

    connect_schema = str(((ts.get("meta", {}).get("target", {}) or {})
                           .get("f_table", {}) or {}).get("schema") or "").strip()
    if not connect_schema and binding:
        connect_schema = next(iter(binding.values()))[0]
    owns_db = db is None
    if owns_db:
        db = _Db(connect_schema)
    lines: list[str] = [f"[字面量形态] {n}" for n in rf_notes]
    verdicts: list[str] = []
    try:
        # ── 驱动表自检（count vs business_key——排除"根本不是 join 的锅"）──
        join_aliases = {(j.get("alias") or "").strip().lower() for j in rule.get("joins") or []}
        driving = next((a for a in binding if a not in join_aliases), None) \
            or (next(iter(binding)) if binding else "")
        if driving and business_key:
            sch, tbl = binding[driving]
            where = " AND ".join(filter(None, (_strip_alias(x, driving)
                                                for x in _terms_for_alias(rule_filter_terms, driving))))
            try:
                st = _key_stat(db, sch, tbl, [c.lower() for c in business_key], where)
            except RuntimeError as e:
                lines.append(f"[驱动表自检] {sch}.{tbl} 查询失败跳过（其余继续）："
                             f"{_err_brief(e)}{_cast_err_hint(e)}")
                st = None
            if st:
                dup = st["total"] - st["nulls"] - st["uniq"]
                if dup > 0:
                    verdicts.append(f"驱动表 {sch}.{tbl} 自身 business_key 重复 {dup} 行（非关联问题——粒度/主键）")
                    lines.append(f"[驱动表自检] {sch}.{tbl}（{driving}）：{st['total']} 行 / "
                                 f"business_key 唯一 {st['uniq']}（NULL 键 {st['nulls']}）→ "
                                 f"✗ 自身重复 {dup} 行——发散不来自 JOIN，查粒度/business_key")
                else:
                    lines.append(f"[驱动表自检] {sch}.{tbl}（{driving}）：{st['total']} 行 / "
                                 f"business_key 唯一 {st['uniq']}（NULL 键 {st['nulls']}）→ ✓ 自身粒度与主键一致")

        # ── 逐 join 表（主判据：声明条件下键唯一性 + 声明对照归属 + 证据解剖）──
        joins_decl = rule.get("joins") or []
        if not joins_decl:
            lines.append("[关联] 本规则无 joins——无关联可查，发散不来自 JOIN（查驱动表粒度/主键）")
        if True:
            for i, j in enumerate(joins_decl, 1):
                alias = (j.get("alias") or "").strip().lower()
                sch_tbl = binding.get(alias)
                if not sch_tbl:
                    lines.append(f"[JOIN {i}] 别名 {alias} 无法绑定到表（source_tables 缺）——跳过，宁放过")
                    continue
                sch, tbl = sch_tbl
                cond = j.get("condition") or ""
                # 字面量值形态开局修正（char 列裸数值=声明错误——按 '值' 执行并披露）
                cond_f, fix_notes = _fix_literal_form(cond, alias, binding, coltypes)
                for n in fix_notes:
                    lines.append(f"[字面量形态] {n}")
                pairs = parse_join_pairs(cond)
                own, partner = [], {}
                for (la, lc), (ra, rc) in pairs:
                    if la == alias:
                        own.append(lc)
                        partner.setdefault(ra, []).append(rc)
                    elif ra == alias:
                        own.append(rc)
                        partner.setdefault(la, []).append(lc)
                own = list(dict.fromkeys(own))
                if not own:
                    lines.append(f"[JOIN {i}] {sch}.{tbl}（{alias}）关联条件无可解析等值对"
                                 f"（{cond[:60]}）——跳过，宁放过")
                    continue
                # 过滤条件（严格遵守声明）：join 自带 filter + join_safety.join_filter + 规则 filter 归属项 + 字面量项
                terms = _split_terms(j.get("filter") or "")
                safety = safety_by_alias.get(alias) or {}
                if safety.get("_ambiguous"):
                    lines.append(f"[JOIN {i}] join_safety 同表多条目无 alias 无法区分该关联用哪条"
                                 f"——人补 alias（关联级声明）")
                terms += _split_terms(safety.get("join_filter") or "")
                terms += _terms_for_alias(rule_filter_terms, alias)
                terms += _literal_terms(cond_f, alias)
                # 单表查询 FROM 无别名——逐项剥别名前缀；剥完仍含其他别名引用的跳过（宁放过）
                where = " AND ".join(dict.fromkeys(
                    x for x in (_strip_alias(tm, alias) for tm in terms) if x))
                mapping_decl = mapping_joins.get(tbl.rsplit(".", 1)[-1].lower(), "")
                # ★ 构造性唯一免实测（2026-09-21）：tmp 边/条件含派生字段（开窗序号 rn 等）
                # 不发起物理查询——闸口①对这类边弹"查询失败"会把合法设计误导成故障
                _skip = _constructed_skip(j, own, where, alias, tmp_aliases)
                if _skip:
                    verdicts.append(f"JOIN {i} {tbl}：免实测（{_skip}——唯一性由设计构造保证）")
                    lines.append(f"[JOIN {i}] {sch}.{tbl}（{alias}）✓ 免实测——{_skip}，"
                                 f"唯一性由设计构造保证，不发起物理查询。")
                    lines.append(f"  ｜关联条件（designer 写的）：{cond}")
                    continue
                # ★ 单表故障隔离 + 降级废除（2026-09-15：join filter 存在的意义就是
                # "源表主键≠关联键，加条件保唯一"——降级不带条件查出的"不唯一"是伪信号
                # （无条件不唯一是预期）。条件查询失败本身=诊断发现：报错原文+分类提示
                # 给人核（写法/字面量/环境），不下任何唯一性结论；其余表继续跑）
                try:
                    st = _key_stat(db, sch, tbl, own, where)
                except RuntimeError as e:
                    _cls = _err_classify(e)
                    verdicts.append(f"JOIN {i} {tbl}：按声明条件查询失败——该关联唯一性无结论"
                                    f"（条件可能有问题，人核）")
                    lines.append(f"[JOIN {i}] {sch}.{tbl}（{alias}）？ 按声明条件查询失败——"
                                 f"唯一性无结论（其余表继续）。")
                    lines.append(f"  ｜声明条件（含 filter/join_filter 并入）：{where or '（无）'}")
                    lines.append(f"  ｜关联条件（designer 写的）：{cond}")
                    lines.append(f"  ｜报错原文: {_err_brief(e, 200)}")
                    if _cls:
                        lines.append(f"  ｜{_cls}")
                    continue
                dup = st["total"] - st["nulls"] - st["uniq"]
                if dup > 0:
                    lines.append(f"[JOIN {i}] {sch}.{tbl}（{alias}）✗ 关联键({', '.join(own)}) "
                                 f"在关联条件下不唯一（{st['total']} 行 / 唯一 {st['uniq']}，重复 {dup} 行）")
                    lines.append(f"  ｜关联条件（designer 写的）：{cond}")
                    # 声明对照（只在出问题时给——问题在设计侧还是输入侧的依据）
                    if alias in tmp_aliases:
                        lines.append(f"  ｜中间表（闸口①表已建时查）——无输入声明属正常，对照跳过")
                    elif mapping_decl and not _decl_parseable(mapping_decl):
                        lines.append(f"  ｜输入声明为自然语言（{mapping_decl[:40]}…）——不可解析，对照跳过（宁缺勿错）")
                    elif mapping_decl:
                        d_set = {_norm_term(x) for x in _split_terms(cond)}
                        m_set = {_norm_term(x) for x in _split_terms(mapping_decl)}
                        miss = [x for x in _split_terms(mapping_decl) if _norm_term(x) not in d_set]
                        extra = [x for x in _split_terms(cond) if _norm_term(x) not in m_set]
                        lines.append(f"  ｜输入声明（mapping）：{mapping_decl}")
                        if miss or extra:
                            # 宁缺勿错：归一后仍不等可能是真漏条件，也可能只是写法差异
                            # （自由文本无穷变体）——不定罪设计侧，人核差异
                            if miss:
                                lines.append(f"  ｜△ 声明差异（人核：可能设计漏了条件，也可能只是写法差异）"
                                             f"——输入声明独有：{'；'.join(miss)}")
                            if extra:
                                lines.append(f"  ｜△ 声明差异（人核：写法差异或设计自创收敛条件）"
                                             f"——设计条件独有：{'；'.join(extra)}")
                        else:
                            lines.append(f"  ｜→ 设计与输入声明一致——问题在**输入侧**（BA 声明的关联在数据上不成立，退 BA）")
                    elif alias not in tmp_aliases:
                        lines.append(f"  ｜输入未声明此关联（designer 自设）——问题属设计判断")
                    # join_safety 断言对照（maker 断言 vs 实测——闸口①与 designer 检查的闭环）：
                    # 声明 unique=true 实测不唯一=断言证伪（最高优先）；声明 false+reason=已知接受不重复弹
                    safety = safety_by_alias.get(alias) or {}
                    if safety:
                        if safety.get("join_key_unique") is True:
                            lines.append(f"  ｜★ designer 断言 join_key_unique=true——**实测证伪**"
                                         f"（designer 判断错或数据变了，闸口①重点核对）")
                            verdicts.append(f"JOIN {i} {tbl}：join_key_unique 断言被实测证伪")
                        elif safety.get("join_key_unique") is False:
                            lines.append(f"  ｜designer 已声明不唯一（strategy={safety.get('strategy') or '—'}"
                                         f"/reason={safety.get('reason') or '—'}）——已知接受，闸口①确认口径即可")
                        else:
                            lines.append(f"  ｜join_safety 未填 join_key_unique——评估层要求补声明")
                    else:
                        lines.append(f"  ｜join_safety 未声明此关联——评估层要求补")
                    try:
                        samples = _dup_samples(db, sch, tbl, own, where, top)
                    except RuntimeError as e:
                        lines.append(f"  ｜样例查询失败：{_err_brief(e, 100)}")
                        verdicts.append(f"JOIN {i} {tbl}：键在关联条件下不唯一（重复 {dup} 行）")
                        continue
                    hits = 0
                    if partner:
                        pa = next(iter(partner))
                        if pa in binding:
                            p_sch, p_tbl = binding[pa]
                            # 伙伴侧过滤（规则 filter 归属项 + 条件字面量项，剥别名）——
                            # 不带会把已被 filter 排除的行误计为命中
                            p_terms = _terms_for_alias(rule_filter_terms, pa) \
                                + _literal_terms(_fix_literal_form(cond, pa, binding, coltypes)[0], pa)
                            p_where = " AND ".join(filter(None, (
                                _strip_alias(x, pa) for x in p_terms)))
                            try:
                                hits = _partner_hits(db, p_sch, p_tbl, partner[pa], samples, own, p_where)
                            except RuntimeError:
                                hits = -1
                    lines.append(f"  ｜重复键 top{len(samples)}：" + "、".join(
                        f"{'|'.join(str(s.get(c)) for c in own)}×{s.get('c')}" for s in samples))
                    anatomy = _dup_anatomy(db, sch, tbl, own, samples[0])
                    if anatomy:
                        lines.append(f"  ｜重复组差异列（判该收敛还是撞键）：{anatomy}")
                    if hits > 0:
                        lines.append(f"  ｜当前数据命中驱动表 {hits} 行——会实际膨胀")
                    elif hits == 0:
                        lines.append(f"  ｜当前数据未命中驱动表——暂不膨胀（生产数据可能命中，别默默放过）")

                    verdicts.append(f"JOIN {i} {sch}.{tbl}：关联键在条件下不唯一（重复 {dup} 行"
                                    + ("，当前命中会膨胀" if hits > 0 else "，当前未命中") + "）")
                else:
                    # 通过=一句话完事（键裸查重复是常态——条件下唯一就是设计本身，不裸查）
                    # 声明对照标签（2026-09-03 全量化：所有关联都对比，不只发散的）
                    if alias in tmp_aliases:
                        decl_tag = "｜声明:中间表(正常)"
                    elif mapping_decl and not _decl_parseable(mapping_decl):
                        decl_tag = "｜声明:自然语言(跳过)"
                    elif mapping_decl:
                        d_set = {_norm_term(x) for x in _split_terms(cond)}
                        m_set = {_norm_term(x) for x in _split_terms(mapping_decl)}
                        miss = [x for x in _split_terms(mapping_decl) if _norm_term(x) not in d_set]
                        extra = [x for x in _split_terms(cond) if _norm_term(x) not in m_set]
                        if not miss and not extra:
                            decl_tag = "｜声明:一致"
                        elif miss:
                            decl_tag = f"｜声明:△漏条件({len(miss)}项,人核)"
                        elif extra:
                            decl_tag = f"｜声明:△自创({len(extra)}项,人核)"
                        else:
                            decl_tag = f"｜声明:△差异(漏{len(miss)}自创{len(extra)},人核)"
                    else:
                        decl_tag = "｜声明:输入未声明(自设)"
                    lines.append(f"[JOIN {i}] {sch}.{tbl}（{alias}）✓ 关联键({', '.join(own)}) "
                                 f"在关联条件下唯一（{st['total']} 行）{decl_tag}｜条件：{cond}")

        # ── 整体试算（严重性：当前数据下膨胀/丢行/空关联——与逐表唯一性定性互补）──
        jc_state = _join_counts(db, rule, binding, driving, tmp_aliases, coltypes,
                                rule_filter_fixed, top, lines, verdicts)
        if jc_state == "fanout" and not any("不唯一" in v for v in verdicts):
            # 矛盾信号：各键条件下都唯一但拼起来膨胀——贴条件原文给人判（数据脏？条件含函数/非等值？）
            lines.append("[⚠ 需人确认] 各关联键在条件下都唯一，但拼起来却膨胀——矛盾信号："
                         "源端数据问题（退 BA：脏数据/统计漂移——现实中大概率此项），"
                         "或关联条件含函数/非等值部分（键唯一性查不到，人核原文）。关联条件原文：")
            for i, j in enumerate(joins_decl, 1):
                al = (j.get("alias") or "").strip().lower()
                ent = binding.get(al) or ("", "")
                lines.append(f"  JOIN {i} {ent[0]}.{ent[1]}（{al}）：{j.get('condition') or ''}")
    finally:
        if owns_db:
            db.close()

    conclusion = "；".join(verdicts) if verdicts else "所有 join 表按声明条件键唯一、驱动表粒度一致——发散不来自关联（核 coder SQL 与设计差异，如漏 GROUP BY/漏 filter）"
    lines.append(f"[结论] {conclusion}")
    lines.append("[提示] 事实供人判断根因（6b 四选一：关联设计/源表数据/业务粒度/coder 实现不符）——工具不代答")
    return lines, conclusion


def diagnose_all(ts_path: Path, top: int = 5) -> list[tuple[str, str, list[str]]]:
    """全规则批量（闸口①前用）：rules + init.rules 逐规则，共享单连接（与单规则
    同构：逐表唯一性主判据 + 声明对照 + 声明计数严重性）；单规则异常跳过不炸整批。
    返回 [(code, 结论, 完整报告行)]——**中间结论不吞**（内网实证 --all 曾只留一行总结论）。"""
    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    codes = list((ts.get("rules") or {}).keys()) \
        + list(((ts.get("init") or {}).get("rules") or {}).keys())
    connect_schema = str(((ts.get("meta", {}).get("target", {}) or {})
                          .get("f_table", {}) or {}).get("schema") or "").strip()
    db = _Db(connect_schema)
    out: list[tuple[str, str, list[str]]] = []
    try:
        for code in codes:
            try:
                rlines, concl = diagnose(ts_path, code, top, db=db)
            except Exception as e:  # 单规则问题（别名绑不上/条件解析不了）不炸整批
                concl, rlines = f"跳过（{_err_brief(e)}）", []
            out.append((code, concl, rlines))
    finally:
        db.close()
    return out


# ============================================================
# 疑点边交集式试算（pre-ts，评估层上报增值——engineer 面）
# ============================================================

_EDGE_DUP_CAP = 200  # 重复键组拉取上限（交集判面够用；超限披露截断）


def _target_schema_from_rs(rs_path: Path) -> str:
    """评估层锚点：rs_input 的 meta.target.f_table.schema（选源用——ts 还没产）。"""
    data = json.loads(Path(rs_path).read_text(encoding="utf-8"))
    return str((((data.get("meta") or {}).get("target") or {}).get("f_table") or {}).get("schema") or "").strip()


def _edge_ident(*names: str) -> None:
    for n in names:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(n or "")):
            raise ValueError(f"非法标识符（只允许字母数字下划线）: {n!r}")


def _edge_keys(key: str) -> list[str]:
    ks = [k.strip() for k in (key or "").split(",") if k.strip()]
    if not ks:
        raise ValueError("键不能为空")
    return ks


def _pair_cond(keys: list[str], row: dict) -> str:
    """复合键等值对：(k1=v1 AND k2=v2)——值来自查询结果，用 _fmt_val 安全格式化。"""
    return "(" + " AND ".join(f"{k} = {_fmt_val(row.get(k))}" for k in keys) + ")"


def _load_eval_result(rs_path: Path) -> dict:
    """读 --eval 落盘的评估结果（_internal/eval_result.json——engineer 诊断的参数源）。"""
    f = rs_path.parent / "eval_result.json"
    if not f.exists():
        raise ValueError(f"评估结果未落盘: {f}——先让 designer 跑一次 explore --eval"
                         f"（或用 --override 手传参数兜底）")
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"eval_result.json 解析失败: {e}——重跑 --eval 刷新")


def _edge_gate(rs_path: Path, side: dict, keys: list, side_label: str) -> None:
    """存在性闸（参数错零 SQL 发起）：表在 cache、键字段在表——不过直接报参数错并
    指向落盘事实行（2026-09-20：参数传递错误无提示/无校验——A 表配 B 键静默出垃圾）。"""
    from schema_query import lookup_table
    st, cols = lookup_table(rs_path, side["schema"], side["table"])
    if st != "ok":
        raise ValueError(f"参数错（{side_label} 侧）: {side['schema']}.{side['table']} 不在 "
                         f"schema_cache（st={st}）——对照 eval_result.json 的 alias→表，"
                         f"别把 A 的参数传给 B")
    colsl = {str(c).lower() for c in (cols or {})}
    missing = [k for k in keys if k.lower() not in colsl]
    if missing:
        raise ValueError(f"参数错（{side_label} 侧）: 键 {missing} 不在 {side['schema']}."
                         f"{side['table']}——对照 eval_result.json（别名的键列在那里），"
                         f"不是换近名字段")


def run_edge_impact(rs_path: Path, doubt: str = "", partner: str = "",
                    override: dict = None, top: int = 5) -> tuple[list[str], Path, list[str]]:
    """疑点边影响试算（pre-ts，2026-09-20 单侧接口；同日复调：**零参数批量化**——
    doubt 留空=自动跑落盘里全部"从表键不唯一"疑点[verdict=non_unique 且非主表]，
    engineer 常规场景直接跑脚本零输入；--doubt 仅作单疑点过滤[复测用]）。

    参数派生链：疑点行（eval_result.json）→ 表/键/限定；对侧键=**等值对配对列**
    （partner_key——`f.x=c1.code AND f.y=c1.renter_id` 的 A 侧键=x,y，与疑点键
    复合度天然一致；旧版用对侧自身键，复合度不匹配直接 IndexError 崩溃）>
    对侧行自身键兜底（自然语言边，披露）。探测=对唯一重复键集 EXISTS 计数。
    批量模式逐边 fail-soft（单边参数错/异常出错误行，不杀整批）。
    返回 (stdout 结论行, 报告路径, 全量报告行)。"""
    ev = _load_eval_result(rs_path)
    rows = {r["alias"].strip().lower(): r for r in (ev.get("rows") or [])}
    override = override or {}

    if doubt:
        targets = [doubt.strip().lower()]
    else:
        targets = [al for al, r in rows.items()
                   if r.get("verdict") == "non_unique" and not r.get("is_main")]
        if not targets:
            raise ValueError("落盘里没有'从表键不唯一'疑点（verdict=non_unique 的从表行为空）——"
                             "无可试算边；③b 主表粒度/④口径类疑点不走本工具，材料直接组")

    connect = _target_schema_from_rs(rs_path)
    if not connect:
        raise ValueError("rs_input 里取不到 meta.target.f_table.schema（选源锚点）")
    stdout_all: list[str] = []
    full_all: list[str] = []
    out_name = "edge_batch.md"  # 单边成功后按疑点表名覆盖（先验校验可能抛错，不预取）
    db = None  # 懒连接：目标校验（别名/主表/键/闸）不过不发起任何连库
    try:
        for dl in targets:
            if len(targets) > 1:
                stdout_all.append(f"◆ {dl}")
                full_all.append(f"◆ {dl}")
            try:
                prep = _edge_prepare(rs_path, rows, ev, dl,
                                     partner=partner, override=override)
                if db is None:
                    db = _Db(connect)
                s_lines, f_lines, tbl = _edge_exec(db, prep, top=top)
                stdout_all.extend(s_lines)
                full_all.extend(f_lines)
                if len(targets) == 1:
                    out_name = f"edge_{tbl}.md"
            except (ValueError, RuntimeError) as e:
                if len(targets) == 1:
                    raise  # 单疑点过滤模式=严格（调用方点名要这条边，错误直抛给人看）
                # 批量模式逐边 fail-soft：单边参数错/派生失败出错误行，不杀整批
                msg = f"[{dl}] ✗ {e}"
                stdout_all.append(msg)
                full_all.append(msg)
    finally:
        if db is not None:
            db.close()
    base = rs_path.parent / "diagnose" if rs_path.parent.name == "_internal" \
        else rs_path.parent / "_internal" / "diagnose"
    base.mkdir(parents=True, exist_ok=True)
    out = base / out_name
    out.write_text("# 疑点边试算（" + ("、".join(targets)) + "）\n\n```\n"
                   + "\n".join(full_all) + "\n```\n", encoding="utf-8")
    return stdout_all, out, full_all


def _edge_prepare(rs_path: Path, rows: dict, ev: dict, doubt_alias: str,
                  partner: str = "", override: dict = None) -> dict:
    """单边的参数派生+全部校验（**零连库**——别名/主表/键/对侧/复合度/存在性闸，
    任一不过 ValueError，不发起任何 SQL）。返回执行所需的全部上下文。"""
    override = override or {}
    dl = doubt_alias.strip().lower()
    if dl not in rows:
        raise ValueError(f"疑点别名 '{doubt_alias}' 不在 eval_result.json（可用: "
                         f"{sorted(rows)}）——对照评估结果的疑点行抄别名")
    drow = rows[dl]
    if drow.get("is_main"):
        raise ValueError(f"'{doubt_alias}' 是主表粒度线（业务主键问题）——无边可试算；"
                         f"③b 路由：材料直接带选项（补键[复合]/退BA修数据——收敛口径归源端，设计侧不自主发明）")
    side_b = {"schema": drow["schema"], "table": drow["table"],
              "key": override.get("join_key_b") or drow.get("key") or "",
              "where": override.get("where_b", drow.get("where") or "")}
    if not side_b["key"]:
        raise ValueError(f"疑点行 '{doubt_alias}' 落盘无键（未答行）——先补答重跑 --eval，"
                         f"或 --override --join-key-b 手传")

    pl = (partner or "").strip().lower()
    partner_note = ""
    if not pl:
        pl = (drow.get("partner") or "").strip().lower()
    main_alias = (ev.get("main_alias") or "").strip().lower()
    if not pl and main_alias:
        pl = main_alias
        partner_note = "（对侧按主表推断——自然语言条件无结构化对侧，链式边用 --partner 指定）"
    if pl not in rows:
        raise ValueError(f"对侧别名 '{partner or pl}' 不在 eval_result.json（可用: "
                         f"{sorted(rows)}）——链式边用 --partner 指定真实对侧")
    prow = rows[pl]
    # 对侧键派生链：override > 等值对配对列（partner_key——复合度与疑点键天然一致）>
    # 对侧行自身键（自然语言兜底，披露）
    a_key = override.get("join_key_a") or (drow.get("partner_key") or "").strip() \
        or (prow.get("key") or "")
    if not a_key:
        raise ValueError(f"对侧键派生不出：疑点行无 partner_key（自然语言边）且对侧行 "
                         f"'{pl}' 无自身键——--override --join-key-a 手传")
    if (drow.get("partner_key") or "").strip() and not override.get("join_key_a"):
        partner_note = "（对侧键=关联条件配对列）" + partner_note
    side_a = {"schema": prow["schema"], "table": prow["table"],
              "key": a_key, "where": override.get("where_a", prow.get("where") or "")}

    ak, bk = _edge_keys(side_a["key"]), _edge_keys(side_b["key"])
    if len(ak) != len(bk):
        raise ValueError(f"键复合度不匹配：疑点 {len(bk)} 列[{'/'.join(bk)}] vs 对侧 "
                         f"{len(ak)} 列[{'/'.join(ak)}]——对照关联声明原文的对侧列；"
                         f"异构边用 --override --join-key-a 指定真实对侧键")
    for s, ks in ((side_a, ak), (side_b, bk)):
        _edge_ident(s["schema"], s["table"], *ks)
    _edge_gate(rs_path, side_b, bk, "疑点")
    _edge_gate(rs_path, side_a, ak, "对侧")
    return {"side_a": side_a, "side_b": side_b, "ak": ak, "bk": bk,
            "partner_note": partner_note, "doubt_alias": doubt_alias}


def _edge_exec(db: "_Db", prep: dict, top: int = 5) -> tuple[list[str], list[str], str]:
    """单边查询执行（prepare 通过后；db 由外层传入复用连接）。
    返回 (stdout 结论行, 全量行, 疑点表名)。"""
    side_a, side_b = prep["side_a"], prep["side_b"]
    ak, bk = prep["ak"], prep["bk"]
    partner_note = prep["partner_note"]

    def _nullguard(keys):
        return " AND ".join(f"{k} IS NOT NULL" for k in keys)

    _bw = (f"({side_b['where']}) AND {_nullguard(bk)}" if side_b.get("where")
           else _nullguard(bk))
    dup_sql = (f"SELECT {', '.join(bk)}, COUNT(1) AS dup FROM {side_b['schema']}.{side_b['table']}"
               f" WHERE {_bw} GROUP BY {', '.join(bk)} HAVING COUNT(1) > 1")
    on_pair = " AND ".join(f"m.{ak[i]} = d.{bk[i]}" for i in range(len(bk)))
    _a_where = f" AND ({side_a['where']})" if side_a.get("where") else ""

    stdout_lines: list[str] = []
    full_lines: list[str] = []
    # B 侧统计 + 重复组数
    bs = db.one(f"SELECT COUNT(1) AS total FROM {side_b['schema']}.{side_b['table']}"
                + (f" WHERE ({side_b['where']})" if side_b.get("where") else ""))
    dup_groups = int(db.one(f"SELECT COUNT(1) AS groups FROM ({dup_sql}) _d").get("groups") or 0)
    b_line = (f"疑点侧 {side_b['schema']}.{side_b['table']} key=({side_b['key']})"
              + (f" 限定({side_b['where']})" if side_b.get("where") else "")
              + f"：{bs.get('total', 0)} 行，重复键 {dup_groups} 组")
    stdout_lines.append(b_line); full_lines.append(b_line)
    if dup_groups:
        sample_rows = db.rows(dup_sql + f" ORDER BY dup DESC LIMIT {top}")
        if sample_rows:
            sample = "；".join((_pair_cond(bk, r).strip("()") + f" ×{int(r.get('dup', 0))}")
                               for r in sample_rows)
            full_lines.append(f"  重复组样例: {sample}")
    # 对侧唯一性（多对多检出）
    if len(ak) == 1:
        a_uniq = db.one(f"SELECT COUNT(1) AS total, COUNT(DISTINCT {ak[0]}) AS d "
                        f"FROM {side_a['schema']}.{side_a['table']}"
                        + (f" WHERE ({side_a['where']})" if side_a.get("where") else ""))
    else:
        aw = (f" WHERE ({side_a['where']})" if side_a.get("where") else "")
        a_uniq = db.one(f"SELECT COUNT(1) AS total, (SELECT COUNT(1) FROM (SELECT DISTINCT "
                        f"{', '.join(ak)} FROM {side_a['schema']}.{side_a['table']}{aw}) _dx) "
                        f"AS d FROM {side_a['schema']}.{side_a['table']}{aw}")
    a_dup = int(a_uniq.get("total") or 0) - int(a_uniq.get("d") or 0)
    a_line = (f"对侧 {side_a['schema']}.{side_a['table']} key=({side_a['key']})"
              + (f" 限定({side_a['where']})" if side_a.get("where") else "")
              + f"：{a_uniq.get('total', 0)} 行"
              + (f"，键重复 {a_dup}——多对多：此边必膨胀，收敛必选" if a_dup else "，键唯一"))
    stdout_lines.append(a_line); full_lines.append(a_line)
    # 命中面（EXISTS 对唯一集）
    if dup_groups == 0:
        hit_line = "疑点侧键唯一——无需本试算（疑点可能已失效，复核 --eval）"
        stdout_lines.append(hit_line); full_lines.append(hit_line)
    else:
        hits = int(db.one(f"SELECT COUNT(1) AS hits FROM ({dup_sql}) d "
                          f"WHERE EXISTS (SELECT 1 FROM {side_a['schema']}.{side_a['table']} m "
                          f"WHERE {on_pair}{_a_where})").get("hits") or 0)
        if hits == 0:
            hit_line = (f"命中：{dup_groups} 组重复键中 0 组存在于对侧——当前零命中=未膨胀；"
                        f"风险=未来命中即膨胀（发散键进入主表即放大）")
            stdout_lines.append(hit_line); full_lines.append(hit_line)
        else:
            aff = int(db.one(f"SELECT COUNT(1) AS c FROM {side_a['schema']}.{side_a['table']} m "
                             f"WHERE EXISTS (SELECT 1 FROM ({dup_sql}) d WHERE {on_pair})"
                             f"{_a_where}").get("c") or 0)
            hit_line = (f"命中：{dup_groups} 组重复键中 {hits} 组存在于对侧——"
                        f"当前膨胀面 {hits} 组，涉及对侧 {aff} 行")
            stdout_lines.append(hit_line); full_lines.append(hit_line)
            hs = db.rows(f"SELECT DISTINCT {', '.join(ak)} FROM {side_a['schema']}.{side_a['table']} m "
                         f"WHERE EXISTS (SELECT 1 FROM ({dup_sql}) d WHERE {on_pair})"
                         f"{_a_where} LIMIT {top}")
            if hs:
                full_lines.append("  命中样例: " + "；".join(_pair_cond(ak, h).strip("()") for h in hs))
    bnote = ("（膨胀面与 JOIN 类型无关——INNER/LEFT 下命中组同样放大，换 INNER 躲不掉膨胀；"
             "INNER 另有丢行面[对侧键无匹配即丢]，属另一疑点域：键值重叠率/整体试算）")
    stdout_lines.append(bnote); full_lines.append(bnote)
    if partner_note:
        stdout_lines.append(partner_note); full_lines.append(partner_note)
    full_lines.append("")
    full_lines.append("—— 查询原文（审计可回溯）——")
    full_lines.append(f"[B 重复键集] {dup_sql}")
    full_lines.append(f"[命中面] SELECT COUNT(1) FROM ({dup_sql}) d WHERE EXISTS(... m {on_pair})")
    return stdout_lines, full_lines, side_b["table"]


def main():
    ap = argparse.ArgumentParser(
        description="关联质量定位器——一个工具两个时点：无 ts（评估期）--edge 疑点边交集式试算；"
                    "有 ts（UT 6b/闸口①）--rule 深查 / --all 批量",
        epilog="示例:\n"
               "  评估期(无 ts) 常规零参数: %(prog)s --rs {rs} --edge"
               "（自动跑落盘全部疑点边，逐边结论+合并落盘）\n"
               "  单疑点复测:            %(prog)s --rs {rs} --edge --doubt c1（链式边加 --partner b）\n"
               "  评估期 兜底通道:     %(prog)s --rs {rs} --edge --doubt c1 --override"
               " --join-key-b code --where-b 'status=1'\n"
               "  UT 6b(有 ts):  %(prog)s --ts {ts} --rule R0001\n"
               "  闸口①(有 ts):  %(prog)s --ts {ts} --all")
    ap.add_argument("--ts", default="", help="ts.json 路径（--rule/--all 模式必填；--edge 模式不用）")
    ap.add_argument("--rs", default="", help="rs_input.json 路径（--edge 模式锚点：选源+报告落盘位）")
    ap.add_argument("--edge", action="store_true",
                    help="疑点边影响试算（pre-ts：designer 评估层上报的从表键不唯一疑点，"
                         "做实当前命中面给人做材料——对唯一重复键集 EXISTS 探测（数学上不发散）；"
                         "参数从 --eval 落盘事实派生，只需 --doubt 疑点别名")
    ap.add_argument("--doubt", default="",
                    help="edge 可选过滤：疑点别名（缺省=零参数批量，自动跑落盘全部'从表键不唯一'"
                         "疑点——常规场景直接 --edge 零参数；--doubt 仅单疑点复测用）")
    ap.add_argument("--partner", default="",
                    help="edge 可选：对侧别名（链式边才指定；缺省=落盘 partner 或主表推断）")
    ap.add_argument("--override", action="store_true",
                    help="edge 兜底通道：手传键/限定（场景=落盘缺失/显式覆盖复测；走同一存在性闸）")
    ap.add_argument("--join-key-b", default="", help="override：疑点侧关联键（复合键逗号分隔——不是主键）")
    ap.add_argument("--where-b", default="", help="override：疑点侧限定")
    ap.add_argument("--join-key-a", default="", help="override：对侧关联键（复合键逗号分隔）")
    ap.add_argument("--where-a", default="", help="override：对侧限定")
    ap.add_argument("--rule", default="", help="规则编码（R0001 / INIT_R0001；与 --all 二选一）")
    ap.add_argument("--all", action="store_true",
                    help="全规则批量（闸口①前用：rules+init.rules 逐规则共享单连接，单规则异常跳过）")
    ap.add_argument("--top", type=int, default=5, help="重复键样例数（默认 5）")
    args = ap.parse_args()

    if args.edge:
        if not args.rs:
            ap.error("--edge 需要 --rs（锚点+落盘派生源）")
        # --doubt 可选：缺省=零参数批量（自动跑落盘里全部"从表键不唯一"疑点——
        # engineer 常规场景直接跑脚本，疑点清单落盘里现成，无需挑）
        _manual = {"join_key_b": args.join_key_b, "where_b": args.where_b,
                   "join_key_a": args.join_key_a, "where_a": args.where_a}
        if any(_manual.values()) and not args.override:
            ap.error("手传键/限定需 --override（主路径参数从 --eval 落盘派生，不手抄）")
        override = {k: v for k, v in _manual.items() if v} if args.override else {}
        rs_path = Path(args.rs)
        if not rs_path.exists():
            print(f"[错误] rs_input.json 不存在: {rs_path}", file=sys.stderr)
            sys.exit(2)
        try:
            lines, out, _full = run_edge_impact(
                rs_path, doubt=args.doubt, partner=args.partner, override=override,
                top=args.top)
        except (ConnectionError, FileNotFoundError) as e:
            # FileNotFoundError=数据库配置缺失（dws_db 侧抛）——同属环境错归人，
            # 不进 fail-soft（掉进去=谎报"工具缺陷"且 exit 0 假成功，测试实抓）
            print(f"[环境] 无库/连不上/配置缺失: {e}——环境问题归人", file=sys.stderr)
            sys.exit(2)
        except (ValueError, RuntimeError, json.JSONDecodeError) as e:
            print(f"[错误] {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:  # fail-soft 终层（辅助工具永不崩盘成卡点）
            import traceback
            print(f"[试算内部错误·fail-soft] {type(e).__name__}: {e}——工具缺陷非输入问题；"
                  f"堆栈留盘", file=sys.stderr)
            _d = rs_path.parent / "diagnose" if rs_path.parent.name == "_internal" \
                else rs_path.parent / "_internal" / "diagnose"
            _d.mkdir(parents=True, exist_ok=True)
            (_d / "edge_crash.log").write_text(traceback.format_exc(), encoding="utf-8")
            sys.exit(0)
        print("\n".join(lines))
        print(f"\n[报告已落盘] {out}", file=sys.stderr)
        return

    if not args.ts:
        ap.error("--rule/--all 模式需要 --ts（pre-ts 疑点边试算用 --edge）")
    if args.all == bool(args.rule.strip()):
        ap.error("--rule 与 --all 必须二选一")

    ts_path = Path(args.ts)
    if not ts_path.exists():
        print(f"[错误] ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(1)
    try:
        if args.all:
            results = diagnose_all(ts_path, args.top)
            lines = ["[发散定位·全规则批量（闸口①材料）]"] + \
                    [f"{code}: {concl}" for code, concl, _ in results]
            blocks = "\n".join(f"## {code}\n\n```\n" + "\n".join(rlines) + "\n```\n"
                               for code, _, rlines in results if rlines)
        else:
            lines, _ = diagnose(ts_path, args.rule, args.top)
            blocks = "```\n" + "\n".join(lines) + "\n```\n"
    except ConnectionError as e:
        print(f"[环境] 无库/连不上: {e}——环境问题归人（剧本 6c）", file=sys.stderr)
        sys.exit(2)
    except (ValueError, RuntimeError, json.JSONDecodeError) as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:  # fail-soft 终层（2026-09-15：辅助工具永不崩盘成卡点）
        import traceback
        print(f"[诊断内部错误·fail-soft] {type(e).__name__}: {e}——工具缺陷非输入问题，"
              f"跳过诊断不阻断主流程；堆栈留盘供修工具", file=sys.stderr)
        tb = traceback.format_exc()
        _d = ts_path.parent / "_internal" / "diagnose"
        _d.mkdir(parents=True, exist_ok=True)
        (_d / "fanout_crash.log").write_text(tb, encoding="utf-8")
        sys.exit(0)  # 诊断是辅助提升工具——内部缺陷不阻断（exit 0，主流程继续；崩溃日志留盘修工具）

    print("\n".join(lines))
    tag = "all" if args.all else args.rule
    out = ts_path.parent / "_internal" / "diagnose" / f"fanout_{tag}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# 关联质量定位 " + (tag if args.all else args.rule) + "\n\n" + blocks,
                   encoding="utf-8")
    print(f"\n[报告已落盘] {out}（分规则全量——中间结论不吞）", file=sys.stderr)


if __name__ == "__main__":
    main()
