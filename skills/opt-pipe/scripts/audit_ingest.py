"""audit_ingest —— 逆向交付入料审核（facts 产物 → 建档前的确定性门，2026-10-14 交付门模型）。

模型（12 章 v3.1 / 02 章）：facts 产物落 reverse/ 暂存区（随时可删可覆盖）；档案只经
确认诞生——本脚本是"审核"动作，assemble_ts_baseline 是"建档"动作（审核过才被调）。

审核内容（全部确定性对账，报错自带处置路由——AI 拿到即上报，不做原因分析）：
  1. 契约校验（baseline_contract：版本/schema/内部一致性）
  2. 资产对账（产物 asset vs --asset[probe 推出]——不一致=串包拒收）
  3. 变更冲突对账（前移自 preprocess_opt 的提取时检查：mapping 变更页签最新批次的
     属性级整行 ADD 字段 vs 产物目标表字段集——已存在=制品新鲜度冲突，三选一路由）
  4. 反向对账（产物目标表字段 - mapping 属性级当前态 - 本批次新增 → 多出的字段=
     台账滞后/制品新于台账，warn 披露）
  4b. 正向类型对账（2026-10-21）：mapping 存量字段类型 vs 产物字段类型（归一比，
      同名异容——台账改类型无变更记录=账面失真；warn 披露，执行由围栏兜底）
  5. 自检结论消费（v1.4 交付门波已接入）：self_check.verdict=review（结构级矛盾）
     → 拦截待人审（放行通道 --accept-review，裁决留痕在命令行）；pass/pass_with_noise
     照常（噪音计数披露）。旧产物无 self_check 字段 → 降级折叠披露（向后兼容）

exit 0=过（可建档）；2=拦（报错带路由，处置后重来——archive 未诞生，零残留）。
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline_contract import norm_asset, validate_baseline_v1
from preprocess import parse_mapping_sheets
from preprocess_opt import (pick_batch_version, read_change_sheet,
                            field_type_drift, WHOLE_ROW_MARK)

# 每类拦截自带处置路由（"结案陈词"——AI 上报即止，不侦探）
ROUTES = {
    "contract_violation": "契约问题归逆向侧：错误清单原样退回（12 章 §五——它侧修，我们不代填）",
    "asset_mismatch": "串包：制品不是这个资产的——核对任务参数的资产标识与制品目录，换对料重来",
    "add_field_conflict": (
        "制品新鲜度冲突：变更清单疑似已执行——三选一："
        "① 换变更前导出的旧版制品重跑；② 清理变更记录页签的已执行批次行；"
        "③ 确认这是另一次变更（改变更记录后重来）"),
    "change_sheet_invalid": "变更记录页签格式问题——按 mapping-format.md 八列规范改输入",
    "mapping_sheet_invalid": (
        "mapping 实体级/属性级页签缺标准列或列头写错（大小写/全角已归一后仍未命中）"
        "——按 mapping 模板列名修正后重跑"),
    "structural_review": (
        "结构级矛盾待人审——reverse/asset_facts.json 全景可查（排查：逆向到底解析出了什么）。"
        "处置三选一：① 料给错了 → 换对制品重跑 facts；② 矛盾已知悉（存量历史债）→ 显式放行："
        "audit_ingest 重跑带 --accept-review（裁决留痕）；③ 存疑 → 上报人定"),
}


def _target_fields(facts: dict, asset: str) -> Tuple[str, set, Dict[str, str]]:
    """产物目标表字段集+类型集（资产归一对齐；返回 (产物资产名, 字段集, {字段: 类型})）。"""
    a = facts.get("asset") or {}
    got = f"{a.get('schema', '')}.{a.get('table', '')}"
    t_short = (a.get("table") or "").rsplit(".", 1)[-1]
    fields: set = set()
    types: Dict[str, str] = {}
    for t in (facts.get("tables") or []):
        name = (t.get("name") or t.get("table") or "")
        if norm_asset(name) == norm_asset(t_short):
            for f in (t.get("fields") or []):
                fname = str(f.get("name") or f.get("target_field") or "").lower()
                fields.add(fname)
                types[fname] = str(f.get("type") or "").strip()
    return got, fields, types


def audit(facts: dict, asset: str, mapping_path: Optional[Path]) -> Tuple[List[dict], List[dict], List[str]]:
    """返回 (errors, warns, report_lines)。errors 非空=拦。"""
    errors: List[dict] = []
    warns: List[dict] = []
    lines: List[str] = []

    # 1. 契约校验
    violations = validate_baseline_v1(facts)
    if violations:
        errors.append({"code": "contract_violation", "detail": violations})
        return errors, warns, lines

    # 2. 资产对账
    got, tfields, ttypes = _target_fields(facts, asset)
    lines.append(f"产物资产: {got}｜目标表字段 {len(tfields)} 个")
    if norm_asset(got) != norm_asset(asset):
        errors.append({"code": "asset_mismatch",
                       "detail": f"产物资产 {got!r} ≠ 本次资产 {asset!r}（镜像归一后仍不一致）"})
        return errors, warns, lines

    # 3./4. 变更对账（mapping 给了才做——纯逆向建档场景无变更需求，跳过）
    batch_add: List[str] = []
    if mapping_path is not None:
        try:
            entries = read_change_sheet(mapping_path)
            version = pick_batch_version(entries)
            batch = [e for e in entries if e["time"] == version]
            lines.append(f"变更批次: {version}（{len(batch)} 条变更记录）")
            batch_add = [e["key"] for e in batch
                         if e["page"] == "attr" and e["ctype"] == "ADD"
                         and e["column"] == WHOLE_ROW_MARK]
            for k in batch_add:
                if k in tfields:
                    errors.append({"code": "add_field_conflict",
                                   "detail": f"变更记录标新增字段 {k!r}，但制品（产物字段集）已存在"})
            # 反向对账：制品有、mapping 当前态没有、也不是本批次新增 → 台账滞后
            try:
                mapping = parse_mapping_sheets(mapping_path)
            except ValueError as ve:
                errors.append({"code": "mapping_sheet_invalid", "detail": str(ve)})
                mapping = None
            if mapping is not None:
                declared = {(r.get("target_column") or "").strip().lower()
                            for r in mapping["attr"] if r.get("target_column")}
                lag = sorted(tfields - declared - set(batch_add))
                if lag:
                    warns.append({"code": "ledger_lag",
                                  "detail": f"产物有 {len(lag)} 个字段不在 mapping 当前态台账"
                                            f"（制品新于台账/台账缺登记）：{', '.join(lag[:10])}"
                                            + ("…" if len(lag) > 10 else "")})
                # 正向类型对账（同名异容，2026-10-21）：mapping 存量字段类型 vs 产物字段类型
                # ——与 ledger_lag（名字反向）互补的内容级；warn 披露（围栏/冻结列兜底执行）
                for d in field_type_drift(mapping["attr"], ttypes, set(batch_add)):
                    warns.append({"code": d["code"], "detail": d["message"]})
        except ValueError as e:
            errors.append({"code": "change_sheet_invalid", "detail": str(e)})

    # 5. 自检结论消费（v1.4 结论通道：self_check 三态）
    ws = facts.get("warnings") or []
    sc = facts.get("self_check") or {}
    verdict = sc.get("verdict")
    if verdict == "review":
        structurals = [w for w in ws if w.get("severity") == "structural"]
        errors.append({"code": "structural_review",
                       "detail": f"逆向自检结论=待审（结构级矛盾 {sc.get('structural_count', len(structurals))} 条）"
                                 f"——产物全景在 reverse/ 可查："
                                 + "；".join(str(w.get("title") or w)[:60] for w in structurals[:3])})
    elif verdict in ("pass", "pass_with_noise"):
        lines.append(f"自检结论: {verdict}（结构级 {sc.get('structural_count', 0)} / 噪音级 "
                     f"{sc.get('noise_count', len(ws))}）")
        noise = [w for w in ws if w.get("severity") != "structural"]
        for w in noise[:3]:
            lines.append(f"  · 噪音: {str(w.get('title') or w)[:80]}")
        if len(noise) > 3:
            lines.append(f"  · …（共 {len(noise)} 条噪音，全文见产物）")
    else:
        # 旧产物（v1.3 无 self_check）→ 降级折叠披露（向后兼容）
        if ws:
            lines.append(f"产物 warnings: {len(ws)} 条（旧产物无自检结论——降级折叠披露）")
            for w in ws[:5]:
                lines.append(f"  · {json.dumps(w, ensure_ascii=False)[:120]}")
    return errors, warns, lines


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="逆向交付入料审核（建档前的确定性门：契约/资产/变更冲突/台账对账）")
    ap.add_argument("--facts", required=True, help="reverse/ 暂存区的 asset_facts.json 路径")
    ap.add_argument("--asset", required=True, help="资产标识 schema.table（probe 推出——资产对账基准）")
    ap.add_argument("--mapping", default="", help="mapping xlsx 路径（可选：给了做变更冲突/台账对账；纯逆向建档场景省略）")
    ap.add_argument("--accept-review", action="store_true",
                    help="结构级待审的人审放行标记（矛盾已知悉——存量历史债场景；裁决留痕在命令行）")
    args = ap.parse_args(argv)

    facts_path = Path(args.facts)
    if not facts_path.exists():
        print(f"AUDIT_BLOCKED: 产物不存在: {facts_path}（先跑 facts 服务）", file=sys.stderr)
        return 2
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    mapping_path = Path(args.mapping) if args.mapping else None
    if mapping_path is not None and not mapping_path.exists():
        print(f"AUDIT_BLOCKED: mapping 不存在: {mapping_path}", file=sys.stderr)
        return 2

    errors, warns, lines = audit(facts, args.asset, mapping_path)
    if args.accept_review:
        errors = [e for e in errors if e["code"] != "structural_review"]
        print("自检待审已放行（--accept-review，人裁决：矛盾已知悉）")
    for l in lines:
        print(l)
    for w in warns:
        print(f"[WARN][{w['code']}] {w['detail']}", file=sys.stderr)
    if errors:
        print(f"AUDIT_BLOCKED：{len(errors)} 项拦截（处置后重来——档案未建，零残留）：", file=sys.stderr)
        for e in errors:
            print(f"  [ERROR][{e['code']}] {e['detail']}", file=sys.stderr)
            print(f"    → 处置：{ROUTES.get(e['code'], '上报人决策')}", file=sys.stderr)
        return 2
    print(f"AUDIT_PASS（{len(warns)} 项 warn 披露）→ 可建档：assemble_ts_baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
