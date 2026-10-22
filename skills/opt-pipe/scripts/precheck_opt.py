"""precheck_opt —— 优化预检（只检新增子集；对齐 new-pipe 步骤 1b，2026-09-04 补齐）。

只检 change_request 的新增内容（新字段直接复制类 + 新来源 JOIN），存量零预检
（围栏+双跑兜底）。检测原语复用 design-dev-shared（risk_checks/schema_cache）：

  1. 新增字段命名规范（离线：小写/数字/下划线，不以数字开头，≤63——存量不审新增审）
  2. 连库存在性+类型对账（schema_cache 24h 缓存）：源表字段存在？mapping 声明源类型
     vs 库实际——不一致 warn 且**以库为准回填**（声明不可信防线，对齐 new-pipe ⓪）
  3. 类型风险检测（库类型优先）→ 同款 TYPE_RISK_PENDING 决策流（人三选，fill 脚本填，
     重跑放行；返源端阻断——对齐 new-pipe/join 改关联键语义）
  4. 值域探测（整数位溢出 error 退 BA / 字符超长 warn 披露）
  5. 新来源 JOIN 键类型对账（等值对 × schema_cache，跨大类 → JOIN_TYPE_RISK_PENDING
     三选决策：转换/改关联键/接受）

决策回写 change_request：fields[].decision（类型，含"原始输入"披露）/
顶层 join_type_decisions（关联）——designer 读 change_request 见『决策』标记
勿推翻方向（同 new-pipe view 标记语义）。
无库 → 2/3/5 降 warn 放行（UT 兜底；对齐 new-pipe 无 cache 降 warn 不硬拦）。
exit 0/1/2 对齐 precheck 分级。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))

from risk_checks import (
    PrecheckResult, _detect_type_risks, _generate_type_risk_skeleton,
    _validate_type_risk_decision, _generate_join_risk_skeleton,
    _validate_join_risk_decision, _check_value_range,
)
from schema_cache import (
    _load_schema_cache, _save_schema_cache, _is_cache_expired,
    _fetch_tables_schema_batch,
)
from sql_parse import parse_join_pairs
from type_compat import join_key_pair_risky

FIELD_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
NO_DB_WARN = ("无库/无 schema_cache：存在性/类型对账/类型风险/JOIN 对账降 warn 跳过"
              "（UT 兜底——值域类报错分流退人，禁回 coder）")


def _load(cr_path: Path, ts_path: Path) -> tuple[dict, dict]:
    cr = json.loads(cr_path.read_text(encoding="utf-8"))
    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    return cr, ts


def _alias_index(ts: dict) -> dict[str, tuple[str, str]]:
    """baseline 全部规则的源表 alias → (schema, table)（join_condition 另一侧的解析域）。"""
    idx: dict[str, tuple[str, str]] = {}
    for r in (ts.get("rules") or {}).values():
        for s in r.get("source_tables") or []:
            if s.get("alias"):
                idx[str(s["alias"]).lower()] = (s.get("schema", ""), s.get("table", ""))
    return idx


def _get_schema_types(ts: dict, cr: dict, cache_path: Path, result: PrecheckResult) -> dict | None:
    """收集待查表（新源表 ∪ baseline 全部源表——新 JOIN 类型比对需要 ON 两侧），
    schema_cache 命中或连库批量查（24h 缓存）。无库返回 None。"""
    tables = {(f["source"]["schema"], f["source"]["table"])
              for f in cr.get("fields", []) if f.get("source", {}).get("table")}
    for r in (ts.get("rules") or {}).values():
        for s in r.get("source_tables") or []:
            if s.get("table"):
                tables.add((s.get("schema", ""), s.get("table")))
    if not tables:
        return {}
    cache = _load_schema_cache(cache_path)
    need = [(s, t) for (s, t) in tables
            if (s.lower(), t.lower()) not in cache.get("tables", {})]
    if need and not _is_cache_expired(cache.get("cached_at", "")):
        need = []  # 缓存新鲜但缺表 = 查过不存在，不重查
    if need:
        schema = ts["meta"]["target"]["f_table"]["schema"]
        try:
            from dws_db import create_executor_for_schema
            executor = create_executor_for_schema(schema, role="etl")
            try:
                fetched = _fetch_tables_schema_batch(executor, need)
                for k, v in fetched.items():
                    cache.setdefault("tables", {})[k] = v
                _save_schema_cache(cache_path, cache)
            finally:
                executor.close()
        except Exception:
            result.add_warn(f"[预检降级] {NO_DB_WARN}")
            return None
    return cache.get("tables", {})


def _check_existence_and_types(cr: dict, ts: dict, tables: dict, result: PrecheckResult) -> None:
    """新增源字段：存在性（缺=error）+ 声明类型 vs 库实际（不一致 warn 以库为准回填）。"""
    for f in cr.get("fields", []):
        src = f.get("source", {})
        key = (src.get("schema", "").lower(), src.get("table", "").lower())
        cols = tables.get(key) or {}
        col = (src.get("field") or "").lower()
        actual = cols.get(col, "")
        if not actual:
            result.add_error(f"[源字段不存在] {f['field']} 的源 {src.get('schema')}."
                             f"{src.get('table')}.{src.get('field')} 库中无此列"
                             f"——修 mapping 后重跑（退输入）")
            continue
        declared = (src.get("source_type") or "").strip()
        if declared and declared.lower() != actual.lower():
            result.add_warn(f"[类型对账] {f['field']}：mapping 声明源类型 {declared}，"
                            f"库实际 {actual}——以库为准（检测按库类型）")
        src["source_type"] = actual   # 以库为准回填（风险检测/值域探测用）


def _check_join_risks(cr: dict, ts: dict, tables: dict, outdir: Path,
                      cr_path: Path, result: PrecheckResult) -> None:
    """新来源 JOIN 键类型对账：等值对两侧类型跨大类 → 人决策（转换/改关联键/接受）。"""
    alias_idx = _alias_index(ts)
    risks = []
    for f in cr.get("fields", []):
        src = f.get("source", {})
        if not f.get("new_source_table") or not src.get("join_condition"):
            continue
        my = (src.get("schema", ""), src.get("table", ""))
        alias_idx[src.get("alias", "").lower()] = my
        for (a1, c1), (a2, c2) in parse_join_pairs(src["join_condition"]):
            sides = []
            for al, c in ((a1, c1), (a2, c2)):
                sch_tbl = alias_idx.get(al)
                if not sch_tbl:
                    continue
                t = tables.get((sch_tbl[0].lower(), sch_tbl[1].lower())) or {}
                sides.append((f"{sch_tbl[0]}.{sch_tbl[1]}.{c}", t.get(c, "")))
            if len(sides) == 2 and sides[0][1] and sides[1][1]:
                if join_key_pair_risky(sides[0][1], sides[1][1]):
                    risks.append({
                        "condition": f"{a1}.{c1}={a2}.{c2}",
                        "left": sides[0][0], "left_type": sides[0][1],
                        "right": sides[1][0], "right_type": sides[1][1],
                    })
    if not risks:
        return

    decision = outdir / "join_type_decision.yaml"
    if decision.exists():
        if _validate_join_risk_decision(decision, risks, result):
            import yaml
            dec = yaml.safe_load(decision.read_text(encoding="utf-8"))
            entries = {it.get("关联条件", ""): it for it in (dec.get("关联风险对") or [])}
            has_key_change = any((entries.get(r["condition"], {}).get("处置") or "").strip()
                                 == "改关联键" for r in risks)
            if has_key_change:
                result.add_error("关联键决策含'改关联键'——请修正 mapping 关联条件后"
                                 "重跑 preprocess_opt+precheck_opt（rs 侧仍检测到该关联对）")
                return
            cr["join_type_decisions"] = [
                {"condition": r["condition"],
                 "decision": (entries.get(r["condition"], {}).get("处置") or "").strip(),
                 "reason": (entries.get(r["condition"], {}).get("原因") or "").strip()}
                for r in risks]
            result.add_pass(f"关联键决策已回写 change_request（{len(risks)} 对——"
                            "designer 读 join_type_decisions：转换的须在 joins 声明 cast）")
            return
        result.add_error("关联键决策文件未填全或清单不一致，已重新生成骨架，请填后重跑")
    else:
        result.add_error(f"检测到新来源关联键类型跨大类（{len(risks)} 对），待人工决策")
    _generate_join_risk_skeleton(decision, risks)
    print("JOIN_TYPE_RISK_PENDING " + json.dumps(
        {"pairs": risks, "decision_file": str(decision)}, ensure_ascii=False))


def _check_type_risks(cr: dict, outdir: Path, result: PrecheckResult) -> None:
    """直接复制新增字段的类型风险 → 同款决策流；决策回写 fields[].decision。"""
    direct = [f for f in cr.get("fields", [])
              if (f.get("source", {}).get("rule") or "").strip() in ("直取", "直接复制")]
    fm_list = [{"target_column": f["field"], "source_type": f["source"].get("source_type", ""),
                "target_type": f.get("type", ""), "transform_rule": "直接复制"} for f in direct]
    batch, individual = _detect_type_risks({"field_mappings": fm_list})
    if not batch and not individual:
        return

    decision = outdir / "type_risk_decision.yaml"
    if decision.exists():
        if _validate_type_risk_decision(decision, batch, individual, result):
            import yaml
            dec = yaml.safe_load(decision.read_text(encoding="utf-8"))
            batch_on = (dec.get("批量处置策略") or "").strip() == "加安全处理"
            batch_cols = {it.get("目标字段", "") for it in (dec.get("常规风险字段") or [])
                          if isinstance(it, dict) and batch_on}
            ind = {it.get("目标字段", ""): (it.get("处置") or "").strip()
                   for it in (dec.get("跨大类风险字段") or []) if isinstance(it, dict)}
            back = [c for c, a in ind.items() if a == "返源端"]
            if back:
                result.add_error(f"类型决策含'返源端'（字段: {', '.join(sorted(back))}）——"
                                 f"请修正源端字段定义后重跑 preprocess_opt+precheck_opt")
                return
            n = 0
            for f in cr.get("fields", []):
                action = ("加安全处理" if f["field"] in batch_cols
                          else ind.get(f["field"], ""))
                if action in ("加安全处理", "转换"):
                    f["decision"] = ("原始输入='直接复制'，类型风险已人定加处理（勿推翻方向）"
                                     "——译成守卫式转换 design_logic（版本无关写法，"
                                     "见 dws-coding-standards §0）")
                    n += 1
            result.add_pass(f"类型决策已回写 change_request：{n} 个字段带『决策』标记"
                            "（designer 译守卫式转换，勿推翻）")
            return
        result.add_error("类型风险决策文件未填全或字段不一致，已重新生成骨架，请填后重跑")
    else:
        result.add_error(f"检测到类型风险待人工决策（决策文件将生成于：{decision}）")
    _generate_type_risk_skeleton(decision, batch, individual)
    print("TYPE_RISK_PENDING " + json.dumps(
        {"batch": batch, "individual": individual, "decision_file": str(decision)},
        ensure_ascii=False))


def _check_modify_type_risks(cr: dict, outdir: Path, result: PrecheckResult) -> None:
    """目标字段类型修改的方向风险（2026-10-22 场景 B）：assess_type_risk(旧→新) 唯一
    源——None（扩容/同义，如 varchar(64)→128）放行；收窄（length_overflow/
    precision_loss）/跨大类/字符语义 → TYPE_MODIFY_RISK_PENDING 人决策三选：
    确认转换（ALTER 自动转换存量值，UT 抽查新类型列）/重选兼容类型（改 mapping
    当前态类型后重跑 preprocess_opt+precheck_opt）/放弃该条变更（删变更记录行重跑）。
    决策回写 modify_type_fields[].decision（designer 读见『决策』标记勿推翻）。"""
    from type_compat import assess_type_risk, RISK_LABEL_CN
    mods = cr.get("modify_type_fields") or []
    if not mods:
        return
    pending = []
    for m in mods:
        risk = assess_type_risk(m.get("old_type", ""), m.get("new_type", ""))
        if risk is None:
            m["decision"] = "扩容/兼容方向，ALTER 自动转换即可"
            continue
        pending.append({"field": m["field"], "old_type": m.get("old_type", ""),
                        "new_type": m.get("new_type", ""), "risk": risk,
                        "risk_cn": RISK_LABEL_CN.get(risk, risk)})
    if not pending:
        result.add_pass(f"类型修改 {len(mods)} 项均为扩容/兼容方向，无需决策")
        return

    decision = outdir / "modify_type_decision.yaml"
    if decision.exists():
        import yaml
        dec = yaml.safe_load(decision.read_text(encoding="utf-8")) or {}
        items = {it.get("字段", ""): (it.get("处置") or "").strip()
                 for it in (dec.get("类型修改风险字段") or []) if isinstance(it, dict)}
        missing = [p["field"] for p in pending if not items.get(p["field"])]
        bad = [f for f, a in items.items()
               if a and a not in ("确认转换", "重选兼容类型", "放弃该条变更")]
        if missing or bad:
            result.add_error(f"类型修改决策未填全或处置非法（缺: {missing}，非法: {bad}）"
                             f"——处置三选：确认转换/重选兼容类型/放弃该条变更")
        else:
            drop = [f for f, a in items.items() if a == "放弃该条变更"]
            rework = [f for f, a in items.items() if a == "重选兼容类型"]
            if drop or rework:
                result.add_error(
                    f"类型修改决策含回输入处置（放弃: {drop or '无'}，重选: {rework or '无'}）"
                    f"——放弃=删变更记录对应行；重选=改 mapping 当前态类型；改完重跑"
                    f" preprocess_opt+precheck_opt")
                return
            n = 0
            for m in mods:
                if items.get(m["field"]) == "确认转换":
                    m["decision"] = ("类型修改已人定确认（跨大类/收窄方向，ALTER 自动转换"
                                     "存量值——UT 抽查新类型列质量）勿推翻")
                    n += 1
            result.add_pass(f"类型修改决策已回写 change_request：{n} 个字段带『决策』标记")
            return
    else:
        result.add_error(f"检测到类型修改风险待人工决策（决策文件将生成于：{decision}）")
    decision.write_text(
        "# 类型修改风险决策（处置三选：确认转换 / 重选兼容类型 / 放弃该条变更）\n"
        "# 确认转换=接受转换口径（ALTER 自动转换存量值，UT 抽查新类型列）\n"
        "# 重选兼容类型=改 mapping 属性级'目标字段类型'列后重跑\n"
        "# 放弃该条变更=删变更记录页签对应行后重跑\n"
        "类型修改风险字段:\n" + "".join(
            f"  - 字段: {p['field']}\n    旧类型: {p['old_type']}\n"
            f"    新类型: {p['new_type']}\n    风险: {p['risk_cn']}\n    处置: \n"
            for p in pending), encoding="utf-8")
    print("TYPE_MODIFY_RISK_PENDING " + json.dumps(
        {"fields": pending, "decision_file": str(decision)}, ensure_ascii=False))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="优化预检：只检新增子集（对齐 new-pipe 1b）")
    ap.add_argument("--change-request", required=True)
    ap.add_argument("--ts-baseline", required=True)
    ap.add_argument("--outdir", required=True, help="过程目录（决策文件/change_request 回写）")
    args = ap.parse_args(argv)

    cr_path, ts_path, outdir = Path(args.change_request), Path(args.ts_baseline), Path(args.outdir)
    cr, ts = _load(cr_path, ts_path)
    result = PrecheckResult()

    # 1. 命名规范（存量不审、新增按我方标准）
    for f in cr.get("fields", []):
        if not FIELD_NAME_RE.match(f.get("field", "")):
            result.add_error(f"[命名规范] 新增字段 {f.get('field')!r} 不合规范"
                             f"（小写字母/数字/下划线，不以数字开头，≤63）——退输入改 mapping")

    # 2. 连库存在性+类型对账（无库降 warn：3/5 跳过，值域探测自管）
    tables = _get_schema_types(ts, cr, outdir / "schema_cache.json", result)
    if tables is not None:
        _check_existence_and_types(cr, ts, tables, result)

    # 3. 类型风险决策（库类型已回填；无库跳过）
    if tables is not None:
        _check_type_risks(cr, outdir, result)

    # 3.5 类型修改方向风险（场景 B：modify_type_fields——离线判定不依赖库）
    _check_modify_type_risks(cr, outdir, result)

    # 4. 值域探测（原语自管连库；用回填后的库类型）
    _check_value_range({
        "field_mappings": [
            {"target_column": f["field"], "source_type": f.get("source", {}).get("source_type", ""),
             "target_type": f.get("type", ""), "transform_rule": "直接复制",
             "source_schema": f.get("source", {}).get("schema", ""),
             "source_table": f.get("source", {}).get("table", ""),
             "source_column": f.get("source", {}).get("field", "")}
            for f in cr.get("fields", [])],
        "meta": ts.get("meta", {}),
    }, result)

    # 5. 新来源 JOIN 对账（无库跳过）
    if tables is not None:
        _check_join_risks(cr, ts, tables, outdir, cr_path, result)

    # 决策有回写（fields[].decision / join_type_decisions）→ 落盘 change_request
    cr_path.write_text(json.dumps(cr, ensure_ascii=False, indent=2), encoding="utf-8")

    print(result.summary())
    return result.return_code


if __name__ == "__main__":
    sys.exit(main())
