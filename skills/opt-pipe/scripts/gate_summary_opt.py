"""gate_summary_opt —— 闸口①' 材料摘要（确定性脚本产出，防 AI 提取失真/遗漏——对齐 new-pipe gate_summary）。

从 ts_v2 + ts_baseline + change_request 直接生成"本次变更一屏"：
变更概览 / 逐字段落位（含决策标记）/ 新 JOIN / 回刷意向 / 预检决策汇总。
engineer 把它作为闸口①' question 的材料（人扫一眼确认，不由 AI 摘要转述）。

用法：
  python gate_summary_opt.py --ts-v2 {opt}/ts_v2.json --ts-baseline {arc}/ts.json \
      --change-request {opt}/_internal/change_request.json [--output {opt}/gate_summary_opt.md]
"""
import argparse
import json
import sys
from pathlib import Path


def render(v2: dict, baseline: dict, cr: dict) -> str:
    change = v2.get("change") or {}
    fields = change.get("fields") or []
    asset = ((v2.get("meta", {}).get("target", {}) or {}).get("f_table", {}) or {})
    lines: list[str] = []
    lines.append(f"# 闸口①' 材料摘要 · {asset.get('schema','')}.{asset.get('table','')}")
    lines.append("")
    new_sources = sorted({f["source"]["table"] for f in cr.get("fields", [])
                          if f.get("new_source_table")})
    # 场景 A：显式声明的新来源（实体级 ADD）——并集呈现（隐式派生+显式声明）
    declared_sources = sorted({ns.get("table", "") for ns in cr.get("new_sources", [])
                               if ns.get("table")})
    new_sources = sorted(set(new_sources) | set(declared_sources))
    mods = change.get("modify_types") or []
    mlogics = change.get("modify_logics") or []
    inter = sorted({t for f in fields for t in f.get("intermediate_tables", [])})
    lines.append("## 变更概览")
    lines.append(f"- 版本：{cr.get('version','')}（{cr.get('change_type','')}）"
                 f"｜新增字段 {len(fields)} 个｜新来源 {len(new_sources)} 张｜中间表加列 {len(inter)} 张"
                 f"｜类型修改 {len(mods)} 列｜口径修改 {len(mlogics)} 列")
    if new_sources:
        lines.append(f"- 新来源：{', '.join(new_sources)}")
    if inter:
        lines.append(f"- 中间表：{', '.join(inter)}（存量规则加列，围栏冻结老列）")
    row = cr.get("change_log_summary") or {}
    if row:
        lines.append(f"- RS 变更记录：{row.get('date','')} {row.get('ver','')}——{row.get('desc','')}")
    lines.append("")

    if mlogics:
        lines.append("## 口径修改（第三刀：字段含义纠偏/逻辑重写——**存量数据新旧含义混置，回刷意向人定**）")
        lines.append("")
        lines.append("| 字段 | 旧口径 | 新口径（designer 翻译） | 落位规则 |")
        lines.append("|------|--------|--------------------------|----------|")
        for m in mlogics:
            old_l = str(m.get("old_logic", ""))[:60].replace("|", "\\|")
            new_l = str(m.get("new_logic", ""))[:120].replace("|", "\\|")
            lines.append(f"| {m.get('field','')} | {old_l} | {new_l} "
                         f"| {', '.join(m.get('rules', []))} |")
        lines.append("")
        lines.append(f"> 回刷意向（backfill={change.get('backfill', '?')}）：口径修改字段的历史行"
                     f"为旧含义——重算与否业务拍板（推生产不自主，UT 披露新旧逻辑差异样例）。")
        lines.append("")
    if mods:
        lines.append("## 类型修改（场景 B：ALTER 自动转换存量值，UT 抽查新列）")
        lines.append("")
        lines.append("| 字段 | 旧类型 | 新类型 | 决策标记 |")
        lines.append("|------|--------|--------|----------|")
        for m in mods:
            dec = "✔已人定" if m.get("decision") else "扩容/兼容"
            lines.append(f"| {m.get('field','')} | {m.get('old_type','')} "
                         f"| {m.get('new_type','')} | {dec} |")
        lines.append("")

    lines.append("## 逐字段落位")
    lines.append("")
    lines.append("| 字段 | 类型 | 落位规则 | 口径（design_logic） | 决策标记 |")
    lines.append("|------|------|----------|----------------------|----------|")
    for f in fields:
        dec = "✔已人定" if f.get("decision") else ""
        logic = str(f.get("design_logic", "")).replace("|", "\\|")
        lines.append(f"| {f.get('field','')} | {f.get('field_type','')} "
                     f"| {', '.join(f.get('placed_rules', []))} | {logic} | {dec} |")
    lines.append("")
    dec_fields = [f["field"] for f in fields if f.get("decision")]
    if dec_fields:
        lines.append(f"> 带『已人定』的字段（{', '.join(dec_fields)}）：类型风险人工拍板过，"
                     f"译守卫式转换——确认落位即可，不重新质疑方向。")
        lines.append("")

    joins = [(f.get("field", ""), j) for f in fields for j in f.get("new_joins", [])]
    if joins:
        lines.append("## 新 JOIN")
        lines.append("")
        for owner, j in joins:
            js = j.get("join_safety") or {}
            lines.append(f"- **{owner}** ← {j.get('join_type','')} JOIN "
                         f"{j.get('schema','')}.{j.get('table','')} `{j.get('alias','')}` "
                         f"ON `{j.get('on','')}`")
            lines.append(f"  - safety：键唯一={js.get('join_key_unique','')}｜"
                         f"策略={js.get('strategy','')}｜{js.get('reason','')}")
        lines.append("")
        lines.append("> 新 JOIN 键类型已对账（跨大类须 cast，组装器硬拦）；"
                     "键唯一性是 designer 声明——UT 双向对比实证。")
        lines.append("")

    lines.append("## 回刷意向")
    backfill = v2.get("change", {}).get("backfill") or cr.get("backfill") or "pending"
    _hint = ("（增量基线——闸口①'人选拿：回刷窗口/范围）" if backfill == "pending"
             else "（全量/分区基线：下次调度自动补齐新列，无需回刷）" if backfill == "no"
             else "")
    lines.append(f"- backfill: **{backfill}**{_hint}")
    lines.append("")

    jdec = cr.get("join_type_decisions") or []
    if jdec:
        lines.append("## 预检决策汇总（关联键）")
        for d in jdec:
            lines.append(f"- `{d.get('condition','')}` → {d.get('decision','')}"
                         f"{('（' + d.get('reason','') + '）') if d.get('reason') else ''}")
        lines.append("")
    unsup = cr.get("unsupported_changes") or []
    if unsup:
        lines.append(f"## 待扩展变更（识别未支持，不阻断）")
        for u in unsup:
            lines.append(f"- {u.get('level','')}.{u.get('change_type','')}: {u.get('name','')}"
                         f"（备注动词'{u.get('verb','')}'）")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="闸口①' 材料摘要（确定性产出）")
    ap.add_argument("--ts-v2", required=True)
    ap.add_argument("--ts-baseline", required=True)
    ap.add_argument("--change-request", required=True)
    ap.add_argument("--output", default="")
    args = ap.parse_args(argv)

    v2 = json.loads(Path(args.ts_v2).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.ts_baseline).read_text(encoding="utf-8"))
    cr = json.loads(Path(args.change_request).read_text(encoding="utf-8"))
    text = render(v2, baseline, cr)
    out = Path(args.output) if args.output else Path(args.ts_v2).with_name("gate_summary_opt.md")
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\ngate_summary_opt: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
