#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diagnose_fanout——关联质量定位器（闸口①批量预检 + UT 回路 6b 深查）。

★ 解决什么：关联的三类边界场景给确定性事实（engineer 质检用，判断归人）：
  1. 类型不一致 → 1b precheck 关联键类型对账（人决策），不在本工具；
  2. 唯一性（发散）→ 声明语义精确计数（before/after 直接量结果，无取样噪声）
     + 确认发散后逐表键唯一性归因（哪张表贡献）；
  3. 值域/内容不一致（静默空关联）→ per-join 关联不上率 + 未命中键样例。

  遵守声明条件（as-designed）：复合键聚合、joins[].filter / join_safety.join_filter /
  规则 filter / condition 字面量项全部并入；**字面量值形态按列类型开局修正**
  （char 列裸数值 = 声明错误，按 '值' 执行并披露——真实 ETL 照写会炸）。
  单表故障隔离（降级裸查/跳过续跑）；依赖中间表的规则闸口①不可查（表未建，UT 兜底）。

  两种深度：--all（闸口①批量，deep=否——精确计数为主，发散才逐表归因，无承重墙）；
  --rule（6b 深查，deep=是——计数 + 逐表唯一性/承重墙/实锤全量）。

用法:
  python diagnose_fanout.py --ts {ts路径} --rule R0001 [--top 5]   # 6b 深查
  python diagnose_fanout.py --ts {ts路径} --all                    # 闸口①批量（分规则全量落盘）

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


def _split_terms(text: str) -> list[str]:
    """把 condition/filter 按顶层 AND 拆成项（简单合取假设——我们的声明都是简单合取）。"""
    if not text:
        return []
    parts = re.split(r"\s+and\s+", str(text), flags=re.IGNORECASE)
    return [p.strip().strip("()").strip() for p in parts if p.strip()]


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


def _cast_err_hint(err_text) -> str:
    """识别隐式转换类报错（回放声明条件时字面量与列类型不匹配——如 varchar 列
    = 数值字面量，内核把列值隐式 cast 成 numeric，脏值即炸。这本身是诊断发现：
    条件独立执行都跑不通，真实 ETL 照写同样炸，闸口①提前抓到）。"""
    low = str(err_text).lower()
    if "invalid input" in low or "无效" in low:
        return "（疑似声明条件的字面量与列类型不匹配触发隐式转换——该条件独立执行已跑不通，真实 ETL 照写同样炸，闸口①提前抓到）"
    return ""


def _key_stat(db: _Db, schema: str, table: str, cols: list[str], where: str) -> dict:
    """count(*) vs count(distinct 组合键)（NULL 键行单独数——NULL 不参与 join 不会发散）。"""
    key = ", ".join(cols)
    # NULL 键行数用 CASE（GaussDB=PG9.2 内核，无 FILTER 子句）——NULL 不参与 join 不会发散
    # COUNT(1) 而非 COUNT(*)（平台口径，性能更合理）
    null_cond = " OR ".join(f"{c} IS NULL" for c in cols)
    sql = (f"SELECT COUNT(1) AS total, COUNT(DISTINCT ({key})) AS uniq, "
           f"SUM(CASE WHEN {null_cond} THEN 1 ELSE 0 END) AS nulls "
           f"FROM {schema}.{table}")
    if where:
        sql += f" WHERE {where}"
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
    # 中间表闸口①未建（DDL 在步骤4）——天然边界，UT 兜底
    involved = [driving] + [(j.get("alias") or "").strip().lower() for j in joins_decl]
    if any(a in tmp_aliases or a not in binding for a in involved):
        lines.append("[声明计数] 依赖中间表（reads tmp，闸口①表未建）或别名未绑定——跳过，UT 兜底")
        return "skip"
    d_sch, d_tbl = binding[driving]
    where_txt = f" WHERE {rule_filter_text}" if (rule_filter_text or "").strip() else ""
    join_parts, jt_by_alias = [], {}
    for j in joins_decl:
        alias = (j.get("alias") or "").strip().lower()
        sch, tbl = binding[alias]
        cond, fix_notes = _fix_literal_form(j.get("condition") or "", alias, binding, coltypes)
        for n in fix_notes:
            lines.append(f"[字面量形态] {n}")
        jt = (j.get("type") or "").strip().upper() or "INNER JOIN"
        jt_by_alias[alias] = jt
        join_parts.append(f"{jt} {sch}.{tbl} {alias} ON ({cond})")
    try:
        before = int(db.one(f"SELECT COUNT(1) AS jc FROM {d_sch}.{d_tbl} {driving}{where_txt}").get("jc") or 0)
        after = int(db.one(f"SELECT COUNT(1) AS jc FROM {d_sch}.{d_tbl} {driving} "
                           + " ".join(join_parts) + where_txt).get("jc") or 0)
    except RuntimeError as e:
        lines.append(f"[声明计数] 查询失败跳过（逐表统计照常）：{_err_brief(e)}{_cast_err_hint(e)}")
        return "skip"
    fanout, loss = after - before, before - after
    if fanout > 0:
        verdicts.append(f"声明语义精确膨胀 {fanout} 行（before {before} → after {after}，as-declared 实锤）")
        lines.append(f"[声明计数] 驱动 {before} 行 → 声明关联后 {after} 行 → ✗ **膨胀 {fanout} 行**"
                     f"（as-declared 实锤，无取样歧义）")
        return "fanout"
    if loss > 0:
        verdicts.append(f"声明关联丢行 {loss} 行（before {before} → after {after}——INNER 未命中，或规则 filter 引用 join 表列使 LEFT 退化；核对关联条件/键内容）")
        lines.append(f"[声明计数] 驱动 {before} 行 → 声明关联后 {after} 行 → ⚠ **丢行 {loss} 行**"
                     f"（INNER 未命中，或规则 filter 引用 join 表列使 LEFT 退化）")
    else:
        lines.append(f"[声明计数] 驱动 {before} 行 → 声明关联后 {after} 行 → ✓ 无膨胀无丢行")
    # 空关联率（LEFT join 逐个——值域/内容不一致维度的系统性检查）
    for i, j in enumerate(joins_decl, 1):
        alias = (j.get("alias") or "").strip().lower()
        if not jt_by_alias.get(alias, "").startswith("LEFT"):
            continue
        sch, tbl = binding[alias]
        cond, _ = _fix_literal_form(j.get("condition") or "", alias, binding, coltypes)
        try:
            matched = int(db.one(f"SELECT COUNT(1) AS jc FROM {d_sch}.{d_tbl} {driving} "
                                 f"{jt_by_alias[alias]} {sch}.{tbl} {alias} ON ({cond}){where_txt}"
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


def diagnose(ts_path: Path, rule_code: str, top: int = 5, db: "_Db | None" = None,
             deep: bool = True) -> tuple[list[str], str]:
    """跑诊断，返回 (报告行列表, 结论一句话)。异常上抛由 main 分流。
    db 传入则复用连接（批量模式单连接跑全部规则），不传入则自建自关。
    deep=True（6b 深查）：计数 + 逐表唯一性/承重墙/实锤全量；
    deep=False（闸口①批量）：精确计数为主，确认膨胀才逐表归因，无承重墙。"""
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
    safety_by_table = {(j.get("table") or "").rsplit(".", 1)[-1].lower(): j
                       for j in joins if isinstance(j, dict)}
    rule_filter_terms = _split_terms(rule.get("filter") or "")
    business_key = (ts.get("design") or {}).get("business_key") or []
    coltypes = _load_coltypes(ts_path)

    connect_schema = str(((ts.get("meta", {}).get("target", {}) or {})
                           .get("f_table", {}) or {}).get("schema") or "").strip()
    if not connect_schema and binding:
        connect_schema = next(iter(binding.values()))[0]
    owns_db = db is None
    if owns_db:
        db = _Db(connect_schema)
    lines: list[str] = []
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

        # ── 声明语义精确计数（膨胀/丢行/空关联——闸口①满配核心，6b 也带实锤）──
        jc_state = _join_counts(db, rule, binding, driving, tmp_aliases, coltypes,
                                rule.get("filter") or "", top, lines, verdicts)

        # ── 逐 join 表按声明条件查（deep=6b 深查全量；闸口①仅在确认膨胀时归因）──
        joins_decl = rule.get("joins") or []
        if not joins_decl:
            lines.append("[关联] 本规则无 joins——无关联可查，发散不来自 JOIN（查驱动表粒度/主键）")
        if not deep and jc_state != "fanout":
            if joins_decl:
                lines.append("[逐表归因] 未触发（闸口①批量模式：精确计数无膨胀，逐表统计与承重墙省略——6b 深查或膨胀时才跑）")
        else:
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
                safety = safety_by_table.get(tbl.rsplit(".", 1)[-1].lower()) or {}
                terms += _split_terms(safety.get("join_filter") or "")
                terms += _terms_for_alias(rule_filter_terms, alias)
                terms += _literal_terms(cond_f, alias)
                # 单表查询 FROM 无别名——逐项剥别名前缀；剥完仍含其他别名引用的跳过（宁放过）
                where = " AND ".join(dict.fromkeys(
                    x for x in (_strip_alias(tm, alias) for tm in terms) if x))
                head = (f"[JOIN {i}] {sch}.{tbl}（{alias}）键({', '.join(own)})"
                        + (f" [声明过滤: {where}]" if where else ""))
                # ★ 单表故障隔离（内网实证：一张表报错曾炸停整批致报告缺失）——
                # 声明条件独立执行失败本身是诊断发现；降级裸查继续，裸查也挂才跳过该表
                try:
                    st = _key_stat(db, sch, tbl, own, where)
                except RuntimeError as e:
                    hint = _cast_err_hint(e)
                    try:
                        bare = _key_stat(db, sch, tbl, own, "")
                    except RuntimeError as e2:
                        verdicts.append(f"JOIN {i} {tbl}：查询失败跳过（其余表继续）")
                        lines.append(f"{head}：查询失败跳过（其余表继续）。报错原文: {_err_brief(e2, 160)}")
                        continue
                    dup_b = bare["total"] - bare["nulls"] - bare["uniq"]
                    tag = f"✗ 重复 {dup_b} 行（filter 承重且条件本身有问题）" if dup_b > 0 else "✓ 唯一"
                    verdicts.append(f"JOIN {i} {tbl}：声明条件查询失败{hint}；降级裸查{tag}")
                    lines.append(f"{head}：按声明条件查询失败{hint}，已降级裸查——"
                                 f"{bare['total']} 行/唯一 {bare['uniq']}（NULL {bare['nulls']}）→ {tag}；"
                                 f"报错原文: {_err_brief(e)}")
                    continue
                dup = st["total"] - st["nulls"] - st["uniq"]
                if dup > 0:
                    try:
                        samples = _dup_samples(db, sch, tbl, own, where, top)
                    except RuntimeError as e:
                        lines.append(f"{head}：✗ 发散 {dup} 行（样例查询失败：{_err_brief(e, 100)}）")
                        verdicts.append(f"JOIN {i} {tbl}：键重复 {dup} 行（样例未取到）")
                        continue
                    hits, p_desc = 0, ""
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
                                p_desc = f"伙伴表 {p_sch}.{p_tbl}.{','.join(partner[pa])} 命中 {hits} 行"
                            except RuntimeError as e:
                                p_desc = f"实锤查询失败（{_err_brief(e, 80)}）"
                    verdict = (f"{tbl} 键重复 {dup} 行" + ("且命中伙伴表——发散嫌疑成立" if hits else
                              "但未命中伙伴表（不膨胀，或键内容形态不一致——空关联维度）"))
                    verdicts.append(f"JOIN {i} {sch}.{tbl}：{verdict}")
                    lines.append(f"{head}：{st['total']} 行 / 唯一 {st['uniq']}（NULL {st['nulls']}）"
                                 f"→ ✗ 发散 {dup} 行")
                    lines.append(f"  重复键 top{len(samples)}：" + "、".join(
                        f"{'|'.join(str(s.get(c)) for c in own)}×{s.get('c')}" for s in samples))
                    lines.append(f"  实锤：{p_desc or '无伙伴表可核'} → {verdict}")
                else:
                    extra = ""
                    if where:  # filter 承重墙：裸查重复但声明条件下唯一 ⇒ SQL 漏 filter 即发散
                        try:
                            bare = _key_stat(db, sch, tbl, own, "")
                        except RuntimeError as e:
                            bare = None
                            lines.append(f"{head}：✓ 唯一（承重墙裸查失败：{_err_brief(e, 80)}）")
                        if bare and bare["total"] - bare["nulls"] - bare["uniq"] > 0:
                            extra = (f"（⚠ filter 承重墙：裸查 {bare['total']}/唯一 {bare['uniq']} 重复——"
                                     f"coder 的 SQL 漏写该过滤即发散，先核 SQL）")
                            verdicts.append(f"JOIN {i} {tbl}：声明条件下唯一但裸查重复（filter 承重——核 SQL 是否漏写）")
                    lines.append(f"{head}：{st['total']} 行 / 唯一 {st['uniq']}（NULL {st['nulls']}）"
                                 f"→ ✓ 唯一{extra}")
    finally:
        if owns_db:
            db.close()

    conclusion = "；".join(verdicts) if verdicts else "所有 join 表按声明条件键唯一、驱动表粒度一致——发散不来自关联（核 coder SQL 与设计差异，如漏 GROUP BY/漏 filter）"
    lines.append(f"[结论] {conclusion}")
    lines.append("[提示] 事实供人判断根因（6b 四选一：关联设计/源表数据/业务粒度/coder 实现不符）——工具不代答")
    return lines, conclusion


def diagnose_all(ts_path: Path, top: int = 5) -> list[tuple[str, str, list[str]]]:
    """全规则批量（闸口①前用）：rules + init.rules 逐规则，共享单连接，闸口①深度
    （deep=False：精确计数为主，膨胀才逐表归因）；单规则异常跳过不炸整批。
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
                rlines, concl = diagnose(ts_path, code, top, db=db, deep=False)
            except Exception as e:  # 单规则问题（别名绑不上/条件解析不了）不炸整批
                concl, rlines = f"跳过（{_err_brief(e)}）", []
            out.append((code, concl, rlines))
    finally:
        db.close()
    return out


def main():
    ap = argparse.ArgumentParser(description="UT 回路关联发散定位器（逐表按声明条件查键唯一性+实锤+驱动表自检）")
    ap.add_argument("--ts", required=True, help="ts.json 路径")
    ap.add_argument("--rule", default="", help="规则编码（R0001 / INIT_R0001；与 --all 二选一）")
    ap.add_argument("--all", action="store_true",
                    help="全规则批量（闸口①前用：rules+init.rules 逐规则共享单连接，单规则异常跳过）")
    ap.add_argument("--top", type=int, default=5, help="重复键样例数（默认 5）")
    args = ap.parse_args()

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

    print("\n".join(lines))
    tag = "all" if args.all else args.rule
    out = ts_path.parent / "_internal" / "diagnose" / f"fanout_{tag}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# 关联质量定位 " + (tag if args.all else args.rule) + "\n\n" + blocks,
                   encoding="utf-8")
    print(f"\n[报告已落盘] {out}（分规则全量——中间结论不吞）", file=sys.stderr)


if __name__ == "__main__":
    main()
