#!/usr/bin/env python3
"""
dws-dq-producer 输入切片（三件套取料）: rs_input + ts.json -> producer 上下文切片 / mapping 按需检索

DQ 拆分（2026-09-14）后 producer 不读 rs_input_view（那是 designer 的全量输入），
本脚本是它的唯一取料入口，三件套：

  1. 确定性闭包（脚本）：RS DQ 需求文本提到的目标字段为种子，沿 transform_detail
     的可解析引用逐层展开（A←B←C 的隐性依赖显式化）
  2. 存疑显式标记（脚本）：闭包边界上机器圈不动的行（人话逻辑/引用提取为空）
     显式标注交付——不是静默缺失
  3. 按需查询服务（--query/--field）：producer 对存疑行深挖时检索 mapping 原文段

用法:
  # 产 producer 上下文切片（默认写到 stdout，--out 落盘）
  python pick_dq_context.py --rs {build}/_internal/rs_input.json --ts {build}/ts.json [--out ctx.json]
  # 深挖检索（mapping 原文段，按关键词）
  python pick_dq_context.py --rs ... --ts ... --query "折扣"
  # 精确字段检索（按字段名，含以它为源/为目标的行）
  python pick_dq_context.py --rs ... --ts ... --field order_amount

退出码: 0=成功, 2=文件/解析错误
"""

import sys
import json
import argparse
from pathlib import Path


def _fm_get(fm: dict, *keys, default=""):
    for k in keys:
        if fm.get(k):
            return fm[k]
    return default


def _norm_field(name: str) -> str:
    return str(name or "").strip().lower()


def _word_hit(text: str, word: str) -> bool:
    """词边界匹配（防 order_id 命中 order_id_ext）。"""
    import re
    if not text or not word:
        return False
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])", text, re.IGNORECASE) is not None


def _is_suspect(fm: dict) -> str:
    """存疑判定：机器圈不动的行返回原因，圈得动返回空串。"""
    rule = _fm_get(fm, "transform_rule", "mapping_rule")
    detail = str(_fm_get(fm, "transform_detail", "mapping_expression")).strip()
    if rule == "直取":
        return ""  # 直连依赖（target←source_column），确定性
    if not detail:
        return "加工逻辑为空（mapping 未给口径，需人/RS 补）"
    if not any(c.isascii() and c.isalnum() for c in detail):
        return "纯人话逻辑（无可解析引用——机器圈不出依赖闭包，按需 --query 深挖+歧义标注）"
    return ""


def build_dq_plan(dq_reqs: list) -> dict:
    """DQ 规划工作单（2026-09-18 定调：producer 把"翻译需求"跳步成"直接写 SQL"——
    补规划层，镜像主线评估层的预填表单模式：机械部分归工具，语义裁决归 producer）。

    确定性产出（producer 只填空不枚举）：
    - rows：每条 RS 需求 → 场景分类预判（断言空值/重复/阈值/数量一致性/聚合对比/
      逻辑复核）+ mode 建议 + declined 候选标记（结构类已被流程内建覆盖）
    - fusion_candidates：疑似同一检查的需求对（文本 bigram 相似度——只标候选，
      融不融由 producer 裁决并写 dq.json 的 fused 申报）
    """
    scene_rules = [
        ("结构类候选", None, [("类型一致", "结构"), ("字段存在", "结构"), ("表结构", "结构"),
                              ("落地", "结构"), ("都创建", "结构"), ("对齐", "结构")]),
        ("数量一致性", "compare", [("行数", "数量"), ("条数", "数量"), ("记录数", "数量"),
                                    ("数量一致", "数量")]),
        ("聚合对比", "compare", [("汇总", "聚合"), ("合计", "聚合"), ("金额一致", "聚合"),
                                  ("总量", "聚合")]),
        ("逻辑复核", "compare", [("口径", "复核"), ("重新计算", "复核"), ("重算", "复核"),
                                  ("计算逻辑", "复核")]),
        ("断言-重复", "assertion", [("重复", "重复"), ("唯一", "重复")]),
        ("断言-阈值", "assertion", [("不超过", "阈值"), ("大于", "阈值"), ("小于", "阈值"),
                                     ("范围", "阈值"), ("阈值", "阈值")]),
        ("断言-空值", "assertion", [("空", "空值"), ("null", "空值"), ("非空", "空值")]),
    ]

    def _classify(req: dict) -> dict:
        blob = " ".join(str(req.get(k) or "") for k in ("rule_name", "rule_desc", "check_type", "scope"))
        low = blob.lower()
        for scene, mode, kws in scene_rules:
            if any(str(k).lower() in low for k, _tag in kws):
                if scene == "结构类候选":
                    return {"场景": "结构类候选（declined 候选）", "mode 建议": "-",
                            "declined_candidate": True,
                            "候选理由": "结构类检查疑已被流程内建覆盖（precheck 类型对账/字段闭合/UT 列序）——你确认后写 dq.json 的 declined"}
                return {"场景": scene, "mode 建议": mode, "declined_candidate": False}
        return {"场景": "未分类（你判断）", "mode 建议": "assertion", "declined_candidate": False}

    rows = []
    for j, req in enumerate(dq_reqs, 1):
        c = _classify(req)
        rows.append({"rs_idx": j,
                     "rule_name": req.get("rule_name", ""),
                     "check_type": req.get("check_type", ""),
                     "rule_desc": str(req.get("rule_desc") or "")[:120],
                     **c})
    return {
        "rows": rows,
        "fusion_candidates": _fusion_candidates(dq_reqs),
        "用法": ("规划在先：逐行确认场景/mode（改预判直接改）；declined 候选确认后进 dq.json 的 declined；"
                 "fusion_candidates 是工具标的疑似同文异述对——融不融你裁决，融合了写 dq.json 的 fused "
                 "（[{rule_id, covered_rs, note}]，covered_rs=被并掉的 RS 需求名）；"
                 "规划定完再写 SQL（每条规划行→一条规则或 declined/fused），交卷自查=行行有落点。"),
    }


def _bigrams(s: str) -> set:
    t = "".join(ch for ch in str(s or "") if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else ({t} if t else set())


def _fusion_candidates(dq_reqs: list, threshold: float = 0.22) -> list:
    """疑似同一检查的需求对（bigram Jaccard≥阈值——0.22 校准：真实同义对
    「产品编码非空/编码不可为空值」=0.26，跨场景对≈0.03；宁可多标候选误扰，
    裁决归 producer——候选漏标=融合漏做[RS 计数契约会 warn]，候选多标=多看一眼）。"""
    texts = [" ".join(str(r.get(k) or "") for k in ("rule_name", "rule_desc", "check_type"))
             for r in dq_reqs]
    grams = [_bigrams(t) for t in texts]
    out = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if not grams[i] or not grams[j]:
                continue
            sim = len(grams[i] & grams[j]) / len(grams[i] | grams[j])
            if sim >= threshold:
                out.append({"rs_idx": [i + 1, j + 1],
                            "names": [dq_reqs[i].get("rule_name", ""), dq_reqs[j].get("rule_name", "")],
                            "相似度": round(sim, 2)})
    return out


def build_context(rs_input: dict, ts: dict) -> dict:
    fms = rs_input.get("field_mappings", []) or []
    dq_reqs = rs_input.get("dq_requirements", []) or []

    # 目标字段全集（field_mappings + ts.tables 并集；行数据以 field_mappings 为准）
    target_fields = []
    seen = set()
    for fm in fms:
        t = _norm_field(_fm_get(fm, "target_column"))
        if t and t not in seen:
            seen.add(t)
            target_fields.append(t)
    f_meta = (ts.get("meta", {}).get("target", {}) or {}).get("f_table", {}) or {}
    f_short = _norm_field(f_meta.get("table"))
    for col in ((ts.get("tables", {}).get(f_short) or {}).get("fields") or []):
        # 键形态对齐 build_tables 真实产出（target_field；name 为兼容兜底）
        name = _norm_field((col.get("target_field") or col.get("name"))
                           if isinstance(col, dict) else col)
        if name and name not in seen:
            seen.add(name)
            target_fields.append(name)

    # 源列全集（供引用匹配）
    source_cols = {_norm_field(_fm_get(fm, "source_column")) for fm in fms}
    source_cols.discard("")

    # --- 种子：RS DQ 需求文本提到的目标字段 ---
    req_texts = []
    for r in dq_reqs:
        req_texts.append(json.dumps(r, ensure_ascii=False))
    req_blob = "\n".join(req_texts)
    seeds = [t for t in target_fields if _word_hit(req_blob, t)]

    # --- 闭包展开（BFS）：target 字段的行 → transform_detail 引用 → 命中的目标列入队 ---
    by_target = {}
    for fm in fms:
        by_target.setdefault(_norm_field(_fm_get(fm, "target_column")), []).append(fm)

    visited = set()
    queue = [t for t in seeds if t not in visited]
    visited.update(queue)
    entries = []
    suspect = []
    while queue:
        cur = queue.pop(0)
        for fm in by_target.get(cur, []):
            entries.append(fm)
            reason = _is_suspect(fm)
            if reason:
                suspect.append({"target_column": _fm_get(fm, "target_column"),
                                "target_column_cn": _fm_get(fm, "target_column_cn"),
                                "reason": reason,
                                "detail": str(_fm_get(fm, "transform_detail", "mapping_expression"))[:200]})
            # 引用提取：detail 里词边界命中的列（源列+目标列都算线索）
            detail = str(_fm_get(fm, "transform_detail", "mapping_expression"))
            src = _norm_field(_fm_get(fm, "source_column"))
            refs = set()
            if src and _word_hit(detail, src):
                refs.add(src)
            for c in source_cols | seen:
                if c and _word_hit(detail, c):
                    refs.add(c)
            for c in refs:
                if c in seen and c not in visited:  # 是目标列（跨字段传递依赖）→ 入队
                    visited.add(c)
                    queue.append(c)

    def _row(fm):
        return {
            "target_column": _fm_get(fm, "target_column"),
            "target_column_cn": _fm_get(fm, "target_column_cn"),
            "target_type": _fm_get(fm, "target_type"),
            "transform_rule": _fm_get(fm, "transform_rule", "mapping_rule"),
            "transform_detail": str(_fm_get(fm, "transform_detail", "mapping_expression")),
            "source_table": _fm_get(fm, "source_table"),
            "source_column": _fm_get(fm, "source_column"),
            "source_alias": _fm_get(fm, "source_alias"),
        }

    # F 表字段全量清单（DQ 可检查任何目标字段，不只闭包内——中文名供 producer 理解语义）
    f_fields = [_row(fm) for fm in fms if _fm_get(fm, "target_column")]

    return {
        "spec_type": "dq_context",
        "dq_requirements": dq_reqs,
        "plan": build_dq_plan(dq_reqs),
        "target": {
            "f_table": f"{f_meta.get('schema', '')}.{f_meta.get('table', '')}",
            "f_table_cn": f_meta.get("cn", ""),
            "business_key": ts.get("design", {}).get("business_key", []),
            "fields": f_fields,
        },
        "source_tables": [
            {"schema": st.get("source_schema", ""), "table": st.get("source_table", ""),
             "cn": st.get("source_table_cn", ""), "alias": st.get("source_alias", "")}
            for st in (rs_input.get("source_tables") or [])
        ],
        "closure": {
            "seed_fields": seeds,
            "entries": [_row(fm) for fm in entries],
            "suspect": suspect,
        },
        "服务说明": {
            "深挖检索": "python pick_dq_context.py --rs ... --ts ... --query <关键词>（mapping 原文段全文检索）",
            "精确字段": "python pick_dq_context.py --rs ... --ts ... --field <字段名>（含以它为源/为目标的行）",
            "纪律": ("存疑行（closure.suspect）必须逐个深挖或标注歧义——不拍板不跳过；"
                    "引用闭包外的行按需 --query 补（禁止读 mapping 全量原文）。"),
        },
    }


def query_mapping(rs_input: dict, keyword: str) -> list:
    """关键词全文检索 mapping 行（任何字段子串命中）。"""
    out = []
    for fm in rs_input.get("field_mappings", []) or []:
        blob = json.dumps(fm, ensure_ascii=False)
        if keyword.lower() in blob.lower():
            out.append(fm)
    return out


def query_field(rs_input: dict, field: str) -> list:
    """精确字段检索：target_column 或 source_column 命中的行。"""
    f = field.strip().lower()
    out = []
    for fm in rs_input.get("field_mappings", []) or []:
        t = _norm_field(_fm_get(fm, "target_column"))
        s = _norm_field(_fm_get(fm, "source_column"))
        if f in (t, s):
            out.append(fm)
    return out


def main():
    parser = argparse.ArgumentParser(description="dws-dq-producer 输入切片（三件套取料）")
    parser.add_argument("--rs", required=True, help="_internal/rs_input.json")
    parser.add_argument("--ts", default="", help="build/ts.json（business_key/target 用；不给则目标信息留空）")
    parser.add_argument("--out", default="", help="切片落盘路径（不给则 stdout）")
    parser.add_argument("--query", default="", help="mapping 原文段关键词检索（深挖服务）")
    parser.add_argument("--field", default="", help="按字段名精确检索（深挖服务）")
    args = parser.parse_args()

    rs_path = Path(args.rs)
    if not rs_path.exists():
        print(f"错误: rs_input.json 不存在: {rs_path}", file=sys.stderr)
        sys.exit(2)
    try:
        rs_input = json.loads(rs_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"错误: rs_input.json 解析失败: {e}", file=sys.stderr)
        sys.exit(2)

    ts = {}
    if args.ts:
        ts_path = Path(args.ts)
        if not ts_path.exists():
            print(f"错误: ts.json 不存在: {ts_path}", file=sys.stderr)
            sys.exit(2)
        ts = json.loads(ts_path.read_text(encoding="utf-8"))

    if args.query or args.field:
        rows = query_field(rs_input, args.field) if args.field else query_mapping(rs_input, args.query)
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        print(f"（命中 {len(rows)} 行）", file=sys.stderr)
        sys.exit(0)

    ctx = build_context(rs_input, ts)
    text = json.dumps(ctx, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"切片产出: {args.out}", file=sys.stderr)
        print(f"种子字段: {len(ctx['closure']['seed_fields'])} 闭包行: {len(ctx['closure']['entries'])} "
              f"存疑: {len(ctx['closure']['suspect'])}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
