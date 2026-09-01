#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diagnose_fanout——UT 回路的关联发散定位器（engineer 步骤 6b 用）。

★ 解决什么：UT 主键重复（发散）后人问"哪张表关联发散了"——engineer 没有
  ad-hoc SQL 通道，全靠 designer 退回全流程太重。本工具给确定性事实：

  链式关联不需要增量测试（a→b→c 逐个加 JOIN 数行数）——每张表在自己关联键上
  全局唯一 ⇒ 该 join 不可能放大行数，与顺序无关；不唯一 ⇒ 嫌疑源。
  严格遵守声明条件（as-designed）：
  - 复合键：按表聚合关联条件里该表的全部列，查组合键唯一性（单列查会误报）；
  - 过滤条件：joins[].filter / join_safety.join_filter / 规则 filter 中引用该表
    的项 / condition 里的字面量等值项（b.is_current=1）全部并入 WHERE；
  - filter 承重墙：裸查重复但按声明条件唯一 ⇒ SQL 漏写 filter 即发散（高频根因）；
  - 嫌疑→实锤：重复键样例回伙伴表查命中（重复键不命中实际不膨胀）；
  - 驱动表自检：count(*) vs count(distinct business_key)——排除"根本不是 join 的锅"。

用法:
  python diagnose_fanout.py --ts {ts路径} --rule R0001 [--top 5]

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


class _Db:
    """按 schema 缓存 executor（一次诊断多源表各连一次）。"""

    def __init__(self):
        self._cache: dict = {}

    def get(self, schema: str):
        schema = (schema or "").strip()
        if schema not in self._cache:
            from dws_db import create_executor_for_schema
            ex = create_executor_for_schema(schema, role="etl")
            if not ex.test_connection():
                raise ConnectionError(f"连不上 schema={schema}")
            self._cache[schema] = ex
        return self._cache[schema]

    def one(self, schema: str, sql: str) -> dict:
        r = self.get(schema).execute(sql)
        if not r.success:
            raise RuntimeError(f"查询失败: {(r.error or '')[:200]} | SQL: {sql[:150]}")
        return (r.rows or [{}])[0]

    def rows(self, schema: str, sql: str) -> list[dict]:
        r = self.get(schema).execute(sql)
        if not r.success:
            raise RuntimeError(f"查询失败: {(r.error or '')[:200]} | SQL: {sql[:150]}")
        return r.rows or []

    def close(self):
        for ex in self._cache.values():
            try:
                ex.close()
            except Exception:
                pass


def _key_stat(db: _Db, schema: str, table: str, cols: list[str], where: str) -> dict:
    """count(*) vs count(distinct 组合键)（NULL 键行单独数——NULL 不参与 join 不会发散）。"""
    key = ", ".join(cols)
    # NULL 键行数用 CASE（GaussDB=PG9.2 内核，无 FILTER 子句）——NULL 不参与 join 不会发散
    null_cond = " OR ".join(f"{c} IS NULL" for c in cols)
    sql = (f"SELECT COUNT(*) AS total, COUNT(DISTINCT ({key})) AS uniq, "
           f"SUM(CASE WHEN {null_cond} THEN 1 ELSE 0 END) AS nulls "
           f"FROM {schema}.{table}")
    if where:
        sql += f" WHERE {where}"
    row = db.one(schema, sql)
    return {"total": int(row.get("total") or 0), "uniq": int(row.get("uniq") or 0),
            "nulls": int(row.get("nulls") or 0)}


def _dup_samples(db: _Db, schema: str, table: str, cols: list[str], where: str, top: int) -> list[dict]:
    key = ", ".join(cols)
    sql = (f"SELECT {key}, COUNT(*) AS c FROM {schema}.{table}")
    if where:
        sql += f" WHERE {where}"
    sql += (f" GROUP BY {key} HAVING COUNT(*) > 1 ORDER BY c DESC, {key} LIMIT {top}")
    return db.rows(schema, sql)


def _partner_hits(db: _Db, p_schema: str, p_table: str, p_cols: list[str],
                  samples: list[dict], cols: list[str]) -> int:
    """实锤确认：重复键样例回伙伴表查命中行数（不命中=实际不膨胀）。"""
    tuples = []
    for s in samples[:5]:
        vals = ", ".join(_fmt_val(s.get(c)) for c in cols)
        tuples.append(f"({vals})")
    pkey = ", ".join(p_cols)
    sql = (f"SELECT COUNT(*) AS hits FROM {p_schema}.{p_table} "
           f"WHERE ({pkey}) IN ({', '.join(tuples)})")
    return int(db.one(p_schema, sql).get("hits") or 0)


def diagnose(ts_path: Path, rule_code: str, top: int = 5) -> tuple[list[str], str]:
    """跑诊断，返回 (报告行列表, 结论一句话)。异常上抛由 main 分流。"""
    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    rule = (ts.get("rules") or {}).get(rule_code) \
        or ((ts.get("init") or {}).get("rules") or {}).get(rule_code)
    if not rule:
        raise ValueError(f"ts 里没有规则 {rule_code}（查 ts.rules / ts.init.rules）")

    # alias → (schema, table)
    binding: dict[str, tuple[str, str]] = {}
    for st in rule.get("source_tables") or []:
        al = (st.get("alias") or "").strip().lower()
        if al:
            binding[al] = ((st.get("schema") or "").strip(), (st.get("table") or "").strip())
    joins = rule.get("join_safety") or []
    safety_by_table = {(j.get("table") or "").rsplit(".", 1)[-1].lower(): j
                       for j in joins if isinstance(j, dict)}
    rule_filter_terms = _split_terms(rule.get("filter") or "")
    business_key = (ts.get("design") or {}).get("business_key") or []

    db = _Db()
    lines: list[str] = []
    verdicts: list[str] = []
    try:
        # ── 驱动表自检（count vs business_key——排除"根本不是 join 的锅"）──
        join_aliases = {(j.get("alias") or "").strip().lower() for j in rule.get("joins") or []}
        driving = next((a for a in binding if a not in join_aliases), None) \
            or (next(iter(binding)) if binding else "")
        if driving and business_key:
            sch, tbl = binding[driving]
            where = " AND ".join(_terms_for_alias(rule_filter_terms, driving))
            st = _key_stat(db, sch, tbl, [c.lower() for c in business_key], where)
            dup = st["total"] - st["nulls"] - st["uniq"]
            if dup > 0:
                verdicts.append(f"驱动表 {sch}.{tbl} 自身 business_key 重复 {dup} 行（非关联问题——粒度/主键）")
                lines.append(f"[驱动表自检] {sch}.{tbl}（{driving}）：{st['total']} 行 / "
                             f"business_key 唯一 {st['uniq']}（NULL 键 {st['nulls']}）→ "
                             f"✗ 自身重复 {dup} 行——发散不来自 JOIN，查粒度/business_key")
            else:
                lines.append(f"[驱动表自检] {sch}.{tbl}（{driving}）：{st['total']} 行 / "
                             f"business_key 唯一 {st['uniq']}（NULL 键 {st['nulls']}）→ ✓ 自身粒度与主键一致")

        # ── 逐 join 表按声明条件查 ──
        joins_decl = rule.get("joins") or []
        if not joins_decl:
            lines.append("[关联] 本规则无 joins——无关联可查，发散不来自 JOIN（查驱动表粒度/主键）")
        for i, j in enumerate(joins_decl, 1):
            alias = (j.get("alias") or "").strip().lower()
            sch_tbl = binding.get(alias)
            if not sch_tbl:
                lines.append(f"[JOIN {i}] 别名 {alias} 无法绑定到表（source_tables 缺）——跳过，宁放过")
                continue
            sch, tbl = sch_tbl
            cond = j.get("condition") or ""
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
            terms += _literal_terms(cond, alias)
            where = " AND ".join(dict.fromkeys(terms))
            st = _key_stat(db, sch, tbl, own, where)
            dup = st["total"] - st["nulls"] - st["uniq"]
            head = (f"[JOIN {i}] {sch}.{tbl}（{alias}）键({', '.join(own)})"
                    + (f" [声明过滤: {where}]" if where else ""))
            if dup > 0:
                samples = _dup_samples(db, sch, tbl, own, where, top)
                hits, p_desc = 0, ""
                if partner:
                    pa = next(iter(partner))
                    if pa in binding:
                        p_sch, p_tbl = binding[pa]
                        hits = _partner_hits(db, p_sch, p_tbl, partner[pa], samples, own)
                        p_desc = f"伙伴表 {p_sch}.{p_tbl}.{','.join(partner[pa])} 命中 {hits} 行"
                verdict = (f"{tbl} 键重复 {dup} 行" + ("且命中伙伴表——发散嫌疑成立" if hits else
                          "但未命中伙伴表（实际可能不膨胀）"))
                verdicts.append(f"JOIN {i} {sch}.{tbl}：{verdict}")
                lines.append(f"{head}：{st['total']} 行 / 唯一 {st['uniq']}（NULL {st['nulls']}）"
                             f"→ ✗ 发散 {dup} 行")
                lines.append(f"  重复键 top{len(samples)}：" + "、".join(
                    f"{'|'.join(str(s.get(c)) for c in own)}×{s.get('c')}" for s in samples))
                lines.append(f"  实锤：{p_desc or '无伙伴表可核'} → {verdict}")
            else:
                extra = ""
                if where:  # filter 承重墙：裸查重复但声明条件下唯一 ⇒ SQL 漏 filter 即发散
                    bare = _key_stat(db, sch, tbl, own, "")
                    if bare["total"] - bare["nulls"] - bare["uniq"] > 0:
                        extra = (f"（⚠ filter 承重墙：裸查 {bare['total']}/唯一 {bare['uniq']} 重复——"
                                 f"coder 的 SQL 漏写该过滤即发散，先核 SQL）")
                        verdicts.append(f"JOIN {i} {tbl}：声明条件下唯一但裸查重复（filter 承重——核 SQL 是否漏写）")
                lines.append(f"{head}：{st['total']} 行 / 唯一 {st['uniq']}（NULL {st['nulls']}）"
                             f"→ ✓ 唯一{extra}")
    finally:
        db.close()

    conclusion = "；".join(verdicts) if verdicts else "所有 join 表按声明条件键唯一、驱动表粒度一致——发散不来自关联（核 coder SQL 与设计差异，如漏 GROUP BY/漏 filter）"
    lines.append(f"[结论] {conclusion}")
    lines.append("[提示] 事实供人判断根因（6b 四选一：关联设计/源表数据/业务粒度/coder 实现不符）——工具不代答")
    return lines, conclusion


def main():
    ap = argparse.ArgumentParser(description="UT 回路关联发散定位器（逐表按声明条件查键唯一性+实锤+驱动表自检）")
    ap.add_argument("--ts", required=True, help="ts.json 路径")
    ap.add_argument("--rule", required=True, help="规则编码（R0001 / INIT_R0001）")
    ap.add_argument("--top", type=int, default=5, help="重复键样例数（默认 5）")
    args = ap.parse_args()

    ts_path = Path(args.ts)
    if not ts_path.exists():
        print(f"[错误] ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(1)
    try:
        lines, _ = diagnose(ts_path, args.rule, args.top)
    except ConnectionError as e:
        print(f"[环境] 无库/连不上: {e}——环境问题归人（剧本 6c）", file=sys.stderr)
        sys.exit(2)
    except (ValueError, RuntimeError, json.JSONDecodeError) as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    print("\n".join(lines))
    out = ts_path.parent / "_internal" / "diagnose" / f"fanout_{args.rule}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# 关联发散定位 " + args.rule + "\n\n```\n" + "\n".join(lines) + "\n```\n",
                   encoding="utf-8")
    print(f"\n[报告已落盘] {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
