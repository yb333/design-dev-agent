#!/usr/bin/env python3
"""评估清单草稿生成器（2026-09-17 作业台整体化：草稿随 view 进来——预填表单/slot-filling 模式）。

纯 rs_input 确定性派生（零 designer 判断参与生成），两个消费者调同一函数吃同一输入：
- preprocess.build_compact → view 的「评估清单」段（designer 读输入即见草稿）
- explore --eval → 内部重拉草稿合并 designer 的 ? 答案（必然与 view 一致）

产出三类行：
- run：需实测行（结构化条件预填 key/where；自然语言留空待 designer 填，未填=疑点）
- treat：已声明处理行（取一/最新——免实测，原始表必不唯一=伪信号；SQL 开窗
  partition by vs 关联键机械核对）
- warn：precheck 检出的输入存疑（直接进疑点清单）
"""

import re

from sql_parse import parse_join_pairs

# 取一/最新类处理语义信号（⓪同族、收紧防误触——"最新"单字不触发）
_TREAT_KEYWORDS = ("取最新", "取一条", "取第一条", "最新一条", "取有效", "去重", "开窗", "row_number")
_RN_EQ_RE = re.compile(r"\b(?:[a-z_]\w*\.)?rn\s*=\s*1\b", re.IGNORECASE)
_PARTITION_RE = re.compile(
    r"partition\s+by\s+((?:[a-z_]\w*\s*\.\s*)?[a-z_]\w*(?:\s*,\s*(?:[a-z_]\w*\s*\.\s*)?[a-z_]\w*)*)",
    re.IGNORECASE)


def _split_terms(text: str) -> list:
    """顶层 and/or 切分（括号深度感知）。"""
    s = str(text or "")
    out, depth, start, i = [], 0, 0, 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0:
            edge_l = i == 0 or s[i - 1].isspace()
            if edge_l and s[i:i + 3].lower() == "and" and (i + 3 >= n or s[i + 3].isspace()):
                out.append(s[start:i]); i += 3; start = i; continue
            if edge_l and s[i:i + 2].lower() == "or" and (i + 2 >= n or s[i + 2].isspace()):
                out.append(s[start:i]); i += 2; start = i; continue
        i += 1
    out.append(s[start:])
    return [t.strip() for t in out if t.strip()]


def extract_join_facts(condition: str, alias: str) -> dict:
    """从 join_condition 提取该别名的关联事实——零猜测：机械提不动的留空。

    返回 {structured, key, where, treat_hit, treat_signal, partition_cols}：
    - structured: 跨别名等值对解析成功（结构化 SQL）；False=自然语言
    - key: 该别名侧等值对列（复合键逗号序；rn=1 处理项不进键）
    - where: 该别名侧非等值限定（剥别名前缀的裸条件，and 连接）
    - treat_hit/treat_signal: 取一/最新类处理声明（免实测——原始表必不唯一=伪信号）
    - partition_cols: SQL 开窗 partition by 列（有则与关联键机械核对）
    """
    cond = str(condition or "").strip()
    facts = {"structured": False, "key": "", "where": "", "treat_hit": False,
             "treat_signal": "", "partition_cols": [], "partner": "", "partner_cols": []}
    if not cond:
        return facts
    m = _RN_EQ_RE.search(cond)
    if m:
        facts["treat_hit"] = True
        facts["treat_signal"] = m.group(0).strip()
    kw = next((k for k in _TREAT_KEYWORDS if k in cond), "")
    if kw:
        facts["treat_hit"] = True
        facts["treat_signal"] = (facts["treat_signal"] + "+" if facts["treat_signal"] else "") + f"关键词:{kw}"
    pm = _PARTITION_RE.search(cond)
    if pm:
        facts["partition_cols"] = [re.sub(r"^[a-z_]\w*\.", "", c.strip(), flags=re.IGNORECASE)
                                   for c in pm.group(1).split(",")]
    al = (alias or "").strip().lower()
    my_cols, other_cols, cross_pair, partner = [], [], False, ""
    for left, right in parse_join_pairs(cond):
        la = (left[0] or "").strip().lower()
        ra = (right[0] or "").strip().lower()
        if la == al and ra and ra != al:
            my_cols.append(left[1]); other_cols.append(right[1]); cross_pair = True
            partner = partner or (right[0] or "").strip()
        elif ra == al and la and la != al:
            my_cols.append(right[1]); other_cols.append(left[1]); cross_pair = True
            partner = partner or (left[0] or "").strip()
    if my_cols and cross_pair:
        facts["structured"] = True
        facts["partner"] = partner
        facts["partner_cols"] = other_cols  # 与 key 按同一等值对配对——复合度一致
        seen, kk = set(), []
        for c in my_cols:
            if c.lower() not in seen:
                seen.add(c.lower()); kk.append(c)
        facts["key"] = ",".join(kk)
    quals = []
    for term in _split_terms(cond):
        if _RN_EQ_RE.search(term):
            continue
        tp = parse_join_pairs(term)
        is_key_term = any(
            (((l[0] or "").strip().lower() == al and (r[0] or "").strip().lower() not in ("", al))
             or ((r[0] or "").strip().lower() == al and (l[0] or "").strip().lower() not in ("", al)))
            for l, r in tp)
        if is_key_term:
            continue
        if re.search(rf"\b{re.escape(alias)}\s*\.", term, re.IGNORECASE):
            quals.append(re.sub(rf"\b{re.escape(alias)}\s*\.", "", term, flags=re.IGNORECASE).strip())
    facts["where"] = " and ".join(q for q in quals if q)
    return facts


def build_eval_plan_data(rs_input: dict) -> dict:
    """从 rs_input 派生评估清单（结构化数据——view 渲染与 --eval 合并共用）。

    返回 {run: [...], treat: [...], warn: [...]}：
    - run 行: {alias, schema, table, key, where, prefilled, note, verified}
      （prefilled=False 即 ? 行——key 为空，designer 填或留空=疑点）
    - treat 行: {alias, schema, table, signal, check, check_ok}
      （check_ok: True=机械核对一致 / False=不一致疑点 / None=口径不全待核）
    - warn 行: {alias, field, issue}
    """
    sts = rs_input.get("source_tables") or []
    dbv = {str(t).lower() for t in ((rs_input.get("_db_verified") or {}).get("tables") or [])}
    issues = rs_input.get("_condition_issues") or []
    # 声明主键（mapping remark 标"主键"提取，2026-09-20——主表线预填消 ? 求证摩擦）
    declared_pk = [str(k).strip() for k in
                   ((rs_input.get("meta") or {}).get("declared_business_key") or []) if str(k).strip()]
    pk_str = ",".join(declared_pk)
    run, treat, warn = [], [], []
    for st in sts:
        alias = str(st.get("source_alias") or "?")
        sch = str(st.get("source_schema") or "?")
        tbl = str(st.get("source_table") or "?")
        cond = str(st.get("join_condition") or "")
        full_l = f"{sch}.{tbl}".lower()
        verified = full_l in dbv
        f = extract_join_facts(cond, alias)
        for i in issues:
            if (i.get("table") or "").lower() == full_l:
                warn.append({"alias": alias, "field": i.get("field"), "issue": i.get("issue")})
        src_note = f"原文:「{cond}」" if cond else "（无条件——主表/粒度证据线：键=业务主键）"
        if f["treat_hit"]:
            part = f["partition_cols"]
            if part and f["key"]:
                ok = {c.lower() for c in part} == {c.lower() for c in f["key"].split(",")}
                check = (f"开窗 partition by {','.join(part)} ↔ 关联键 {f['key']} → "
                         + ("机械核对一致 ✓" if ok else "⚠ 不一致——处理后仍不唯一，进疑点清单"))
            elif part:
                ok = None
                check = f"关联键 {f['key'] or '?'}；开窗 partition by {','.join(part)}——核对两者一致"
                if not f["key"]:
                    check = f"开窗 partition by {','.join(part)}；关联键待你定——核对两者一致"
            else:
                ok = None
                check = (f"关联键 {f['key']}；" if f["key"] else "")
                check += "原文未含开窗分组/排序口径——口径不全=疑点上报（开窗口径业务语义源端给，不是你编）"
            treat.append({"alias": alias, "schema": sch, "table": tbl, "signal": f["treat_signal"],
                          "key": f["key"], "partition": ",".join(part), "check": check,
                          "check_ok": ok, "src": cond})
        elif f["structured"]:
            run.append({"alias": alias, "schema": sch, "table": tbl, "key": f["key"],
                        "where": f["where"], "prefilled": True,
                        "is_main": False, "partner": f.get("partner") or "",
                        "partner_key": ",".join(f.get("partner_cols") or []),
                        "note": f"预填自结构化条件（核一眼）{'〔存在性+类型已核，唯一性未测〕' if verified else ''}  {src_note}"})
        elif not cond:
            if pk_str:
                run.append({"alias": alias, "schema": sch, "table": tbl, "key": pk_str, "where": "",
                            "prefilled": True, "is_main": True, "pk_declared": True,
                            "note": f"主表/粒度证据线：键=业务主键（mapping 声明：{pk_str}——"
                                    f"核一眼，粒度变化才调）{'〔存在性+类型已核，唯一性未测〕' if verified else ''}"})
            else:
                run.append({"alias": alias, "schema": sch, "table": tbl, "key": "", "where": "",
                            "prefilled": False, "is_main": True,
                            "note": f"主表/粒度证据线：键=业务主键（mapping 未标记主键——从字段中文名/RS 粒度声明判断）"
                                    f"{'〔存在性+类型已核，唯一性未测〕' if verified else ''}"})
        else:
            run.append({"alias": alias, "schema": sch, "table": tbl, "key": "", "where": "",
                        "prefilled": False, "is_main": False,
                        "note": f"自然语言——填你从原文读出的键/限定（从 view 的 mapping 中文名对物理名；"
                                f"对不出就留空=自动进疑点；填错流水线会拦）{'〔存在性+类型已核，唯一性未测〕' if verified else ''}  {src_note}"})
    return {"run": run, "treat": treat, "warn": warn}


def render_eval_draft(rs_input: dict) -> str:
    """草稿人读文本（--eval 无 stdin 兜底输出；view 用分块结构不走这里）。"""
    d = build_eval_plan_data(rs_input)
    out = ["── 评估清单（填空后回灌：explore --eval，stdin 只给答案行 别名|键|限定）──"]
    if d["run"]:
        out.append("\n需实测（行格式=别名|键[,复合]|限定；预填行自动跑不用抄，只补空行）：")
        for r in d["run"]:
            line = f"{r['alias']}|{r['key'] or '?'}|{r['where']}"
            out.append(f"{line}   ← {r['note']}")
    if d["treat"]:
        out.append("\n已声明处理（免实测——原始表必不唯一=伪信号）：")
        for t in d["treat"]:
            out.append(f"{t['alias']}|{t['schema']}.{t['table']}  命中:{t['signal']}  {t['check']}\n    原文:「{t['src']}」")
    if d["warn"]:
        out.append("\n⚠ 输入存疑（处置写一次，逐条只列事实：核 mapping 出处——逻辑成立 → "
                   "落地其产生逻辑（如 derived_fields）；对不上 → 记疑点上报（字段名写错归人裁决））：")
        for w in d["warn"]:
            out.append(f"⚠ {w['alias']}/{w['field']}: {w['issue']}")
    return "\n".join(out)
