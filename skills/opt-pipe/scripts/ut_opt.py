"""ut_opt —— 优化模式 UT（2026-10-26 统一 UT 重构：opt 编排壳）。

架构定调（用户多轮拍板）：优化与新建的 UT 本质无区别——幂等地执行脚本+对着资产
做数据检查（UT 视角不区分 CREATE/ALTER、不豁免基本项）。本脚本瘦身为 opt 编排壳：
围栏时效+ALTER+EXPLAIN 前置，写路径/数据检查/DQ 全走共享内核（run_ut）。

流程（现成开发环境上）：
  1. 围栏时效校验（回路铁律机器化：产物变→围栏重跑→才进 UT）
  2. 应用 ALTER（ddl/alter_table_*.sql 确定文件名；表不存在=环境归人 exit 3；
     **逐句判定 r.success**——类型 MODIFY 转换失败当场爆）
  3. EXPLAIN 单侧真跑（新 SELECT——opt 无 6a 前置故内嵌；计划两门槛+顶层行数）
  4. 写路径（共享内核 execute_write_path：load_mode 真形态——merge_into 拼真 MERGE
     +写前清理，**多次重跑不再累积残留**）+ **merge 族幂等第二遍**
     （verify_merge_idempotent：同语句两遍行数不变——WHEN MATCHED 分支覆盖+
     生产重叠窗口重跑安全性镜像）
  5. run_ut_check **全集**（行数/主键唯一/审计非空——2026-10-26 豁免移除：UT 是
     资产质量门不是 diff 门，口径修改后主键唯一性必须独立验证）
  6. 新列/新类型抽查（全 NULL=新 JOIN 关联不上；类型修改列转换 NULL=事故信号）
  7. DQ 真跑（数据不完整跳过）
  8. 报告 ut_report_opt.md

双跑对比（新老 SELECT 数据 diff）2026-10-26 退役（ROI 拍板）：SQL 围栏 AST 级更严
更早（确定性无时间列误报）+ run_ut_check 主键全集替代行数对账；纵深代价=围栏漏放
时少一层数据兜底，已知悉。
"""
import argparse
import json
import sys
from pathlib import Path

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from typing import Dict, List, Optional

from run_ut import (read_select, run_dq_checks, load_dq_rules, rule_output_fields,
                    execute_write_path, verify_merge_idempotent, run_ut_check,
                    substitute_params, resolve_all_params, compare_column_order)
from explain_check import _analyze_plan, _parse_actual_rows

# 报告样例上限（不搬全量数据）
SAMPLE_LIMIT = 5


def run_explain_single(executor, ts_v2: dict, etl_dir: Path, ts_path: Path,
                       param_values: Optional[dict] = None) -> List[dict]:
    """逐规则 EXPLAIN ANALYZE 单侧真跑（新 SELECT——opt 无 6a 前置故内嵌）：
    真跑通验证 + 计划两门槛（不下推/STREAM——提示级不阻断）+ 顶层行数（0 行告警）
    + describe 列序对账（2026-10-23 缺 b 补齐——对齐 6a：INSERT 按位置对齐，coder
    输出多/缺/乱序=静默错位，权威解释器是数据库；列序 FAIL=硬阻断归 coder）。
    计划原文全量落盘 _internal/diagnose/ 可回溯。返回检查结果列表。
    执行前过参数替换（2026-10-23 补：存量 SQL 平台变量 #name={constants,val}# /
    ${PARAM} 形态——统一 UT 重构时 opt 侧漏接，裸跑必 DB 报错）。"""
    tables_meta = ts_v2.get("tables", {}) or {}
    results = []
    for rule_code, rule in ts_v2.get("rules", {}).items():
        new_sql = read_select(etl_dir, rule_code)   # {code}.sql 或 {code}_描述_模式.sql
        if not new_sql:
            continue   # 视图/未产出规则跳过（dispatch 层已保证清单）
        try:
            new_sql = substitute_params(new_sql, param_values or {})
        except ValueError as e:
            results.append({"rule": rule_code, "status": "ERROR", "detail": str(e)})
            continue
        r_plan = executor.execute(f"EXPLAIN ANALYZE {new_sql}")
        if not r_plan.success:
            results.append({"rule": rule_code, "status": "ERROR",
                            "detail": f"新 SELECT 执行失败: {(r_plan.error or '')[:200]}"})
            continue
        plan_text = "\n".join(str(v) for row in (r_plan.rows or []) for v in row.values())
        pre_rows = _parse_actual_rows(plan_text)
        plan_issues, plan_file = _analyze_plan(
            plan_text, rule_code, ts_path,
            diag_dir=etl_dir.parent / "_internal" / "diagnose")
        if pre_rows == 0:
            plan_issues = [f"⚠ 0 行——源表有数据却查不出：疑似关联/过滤条件全灭，核对关联条件"] + plan_issues
        row_note = f"EXPLAIN {pre_rows}行" if pre_rows is not None else "行数未解析"
        # 列序对账（对齐 6a 口径：期望=结构源序 ∩ 规则产出列；describe 无列宁放过披露）
        target = rule.get("target_table", "")
        t_short = target.rsplit(".", 1)[-1] if "." in target else target
        expected = [str(f.get("target_field", "")).lower()
                    for f in (tables_meta.get(t_short) or {}).get("fields", [])
                    if isinstance(f, dict) and f.get("target_field")]
        produced = rule_output_fields(rule)
        if produced:
            expected = [c for c in expected if c in {str(p).lower() for p in produced}]
        if expected:
            r_desc = executor.execute(
                f"SELECT * FROM ({new_sql.strip().rstrip(';')}) _ut_cols LIMIT 0")
            if r_desc.success and r_desc.columns:
                actual = [str(c).lower() for c in r_desc.columns]
                ok, diffs = compare_column_order(expected, actual)
                if not ok:
                    results.append({"rule": rule_code, "status": "FAIL",
                                    "detail": f"列序对账失败（SQL 输出列 ≠ ts 字段声明）: "
                                              f"{'; '.join(diffs)}——回 coder 修 SELECT 输出列"})
                    continue
                row_note += f"，列序对账 {len(expected)} 列一致"
            else:
                row_note += "，列序对账跳过（describe 无列返回）"
        results.append({"rule": rule_code, "status": "PASS",
                        "detail": f"真跑通（{row_note}）",
                        "plan_issues": plan_issues, "plan_file": plan_file})
    return results


def check_new_column_nulls(executor, ts_v2: dict, schema: str) -> List[dict]:
    """新列空值检查（写路径后真实数据）：逐目标表统计新列 NULL——兑现 06 §一
    '空值只查新列'的承诺；全 NULL = 疑似新 JOIN 关联不上的信号（LEFT JOIN 常态形态）。
    类型修改列（场景 B·2026-10-22）同款抽查：MINUS 豁免后由空值/转换异常守——
    ALTER 自动转换失败的存量脏值落 NULL（PG 语义）→ 空值率异常即转换事故信号。"""
    change = ts_v2.get("change") or {}
    by_table: Dict[str, List[str]] = {}
    for f in change.get("fields", []):
        by_table.setdefault(f.get("target_table", ""), []).append(f["field"])
    _mod_by_table: Dict[str, List[str]] = {}
    for m in change.get("modify_types", []):
        _mod_by_table.setdefault(m.get("target_table", ""), []).append(m.get("field", ""))
    out = []
    for table, cols in sorted({**by_table, **{t: [] for t in _mod_by_table}}.items()):
        cols = sorted(set(by_table.get(table, [])))
        mod_cols = sorted(set(_mod_by_table.get(table, [])))
        all_check = cols + mod_cols
        if not all_check:
            continue
        null_exprs = ", ".join(f'COUNT(*) - COUNT("{c}") AS null_{c}' for c in all_check)
        try:
            rows = executor.fetch_all(
                f'SELECT COUNT(*) AS total, {null_exprs} FROM {schema}.{table}') or [{}]
            r = rows[0]
            total = int(r.get("total") or 0)
            for c in all_check:
                nulls = int(r.get(f"null_{c}") or 0)
                rate = (nulls / total) if total else 0
                note = ""
                if c in mod_cols:
                    if total and nulls > 0:
                        note = (f" ⚠ 类型修改列存量转换出现 {nulls} 个 NULL——"
                                f"ALTER 自动转换失败的脏值落 NULL（转换事故信号，闸口②'人判）")
                    else:
                        note = "（类型修改列：转换零 NULL）"
                elif total and nulls == total:
                    note = " ⚠ 全 NULL——疑似新 JOIN 关联不上（LEFT JOIN 关联不上的常态形态），核对 ON 条件"
                elif rate > 0.5:
                    note = " ⚠ 过半 NULL——抽查关联条件"
                out.append({"table": table, "col": c, "total": total,
                            "nulls": nulls, "rate": f"{rate:.1%}".rstrip("0").rstrip("."),
                            "note": note.strip()})
        except Exception as e:
            out.append({"table": table, "col": ",".join(all_check), "total": 0, "nulls": 0,
                        "rate": "-", "note": f"查询失败: {str(e)[:120]}"})
    return out


def apply_alters(executor, ddl_dir: Path, tables: List[str], schema: str) -> List[str]:
    """应用 ALTER 变更单（确定文件名拼接，禁 glob）。表不存在让 DB 报错 → 环境问题归人。

    变更单文件缺失 → fail loud（不静默跳过：缺 ALTER 直接跑 INSERT 会报新列不存在，
    错误会被分流给 coder——先跑 assemble_ddl_opt 生成 ddl/ 再进 UT）。
    """
    applied = []
    missing = [t for t in tables if not (ddl_dir / f"alter_table_{t}.sql").exists()]
    if missing:
        raise ValueError(
            f"ALTER 变更单缺失: {missing}（{ddl_dir}）——先跑 assemble_ddl_opt 生成变更单再执行 UT")
    for t in tables:
        p = ddl_dir / f"alter_table_{t}.sql"
        # 逐句判定（2026-10-26 契约修复：execute 失败=返回 success=False 不抛异常——
        # 此前返回值丢弃，类型 MODIFY 转换失败被静默吞掉后带病继续跑写路径）
        for stmt in [x.strip() for x in p.read_text(encoding="utf-8").split(";") if x.strip()]:
            r = executor.execute(stmt)
            if not r.success:
                raise RuntimeError(
                    f"ALTER 失败（表 {t}）：{(r.error or '')[:200]}——"
                    f"类型转换失败=存量脏值塞不进新类型（闸口②'事故信号）")
        applied.append(t)
    return applied


def render_report(ts_v2: dict, alters: List[str], explains: List[dict],
                  writes: List[dict], ut_checks: List[dict], nulls: List[dict],
                  dq_results: List[dict] = None) -> str:
    lines = ["# UT 报告（优化模式·统一 UT 内核）", "",
             f"- ALTER 已应用：{', '.join(alters) or '（无）'}",
             f"- 数据检查：run_ut_check 全集（行数/主键唯一/审计非空——不豁免）", ""]
    lines.append("## EXPLAIN 真跑（单侧新 SELECT + 计划两门槛）")
    for r in explains:
        lines.append(f"- [{r['status']}] {r['rule']}：{r['detail']}")
        for pi in (r.get("plan_issues") or [])[:5]:
            lines.append(f"    - 计划门槛: {pi}")
    lines.append("")
    lines.append("## 写路径（load_mode 真形态 + merge 幂等验证）")
    for r in writes:
        lines.append(f"- [{r['status']}] {r['rule']}：{r['detail']}")
    lines.append("")
    lines.append("## 资产数据检查（run_ut_check 全集）")
    for r in ut_checks:
        lines.append(f"- [{r['status']}] {r['table']}·{r['check']}：{r['detail']}")
        for smp in (r.get("samples") or [])[:SAMPLE_LIMIT]:
            lines.append(f"    - 样例: {smp}")
    lines.append("")
    lines.append("## 新列/新类型抽查（写路径后真实数据）")
    for n in nulls:
        lines.append(f"- {n['table']}.{n['col']}：{n['nulls']}/{n['total']} NULL"
                     f"（{n['rate']}）{n['note']}")
    lines.append("")

    # DQ 段（2026-09-14 DQ 拆分补环）：重做/全部条目在 opt 场景真跑（上生产的检查，变更后必须验证）
    dq_results = dq_results or []
    if dq_results:
        lines.append("## DQ 检查（0 行=通过，非 0 行=告警）")
        lines.append("")
        for d in dq_results:
            symbol = {"PASS": "✅", "ALERT": "🚨", "FAIL": "❌", "MISSING": "❓"}.get(d["status"], "?")
            mode = "对比" if d.get("mode") == "compare" else "断言"
            lines.append(f"- {symbol} {d['rule_name']}（{mode}，`{d['file']}`）：{d['detail']}")
            for s in (d.get("samples") or [])[:SAMPLE_LIMIT]:
                lines.append(f"    - 样例: {s}")
        lines.append("")
        cmp_zero = [d for d in dq_results
                    if d.get("mode") == "compare" and d["status"] == "PASS" and not d.get("waived")]
        if cmp_zero:
            lines.append("> **⚠️ 对比式 0 行双义**（" + "、".join(d["rule_name"] for d in cmp_zero)
                         + "）：口径一致通过 / 重算口径写错恒等失效——闸口②' 人审口径。")
        lines.append("> 分流：FAIL/MISSING 回 dws-dq-producer（限 3 轮）；ALERT 攒闸口②' 人判三选一（回改/人定口径或取消/豁免），零自动回路。")
        lines.append("")

    lines.append("> 闸口②'素材：新列 NULL 率/新类型转换 NULL/幂等结论见上各段；"
                 "开发库数据代表性限制如实声明。")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="优化模式 UT：ALTER + 输出对比 + INSERT")
    ap.add_argument("--ts", required=True, help="ts_v2.json")
    ap.add_argument("--etl-dir", required=True, help="新 SELECT 目录 etl/")
    ap.add_argument("--baseline-dir", required=True, help="etl_baseline/")
    ap.add_argument("--ddl-dir", required=True, help="ddl/（alter_table_*.sql）")
    ap.add_argument("--report", required=True, help="ut_report_opt.md 输出")
    args = ap.parse_args(argv)

    ts_v2 = json.loads(Path(args.ts).read_text(encoding="utf-8"))
    change = ts_v2.get("change") or {}
    if not change.get("fields"):
        print("UT_OPT_ERROR: ts 无 change 段——这不是优化模式的 ts", file=sys.stderr)
        return 2

    # 围栏时效（回路铁律机器化）：SQL 落盘晚于最近一次围栏结果 = 围栏已过期，
    # 先重跑 sql_fence_check 再进 UT——纪律变闸门，防"改了 SQL 忘了重跑围栏"。
    fence_result = Path(args.etl_dir).parent / "_internal" / "sql_fence_result.json"
    if not fence_result.exists():
        print("UT_OPT_ERROR: 未见 SQL 围栏结果（_internal/sql_fence_result.json）——"
              "先跑 sql_fence_check 再执行 UT", file=sys.stderr)
        return 2
    fence_mtime = fence_result.stat().st_mtime
    stale = [f.name for f in sorted(Path(args.etl_dir).glob("*.sql"))
             if f.stat().st_mtime > fence_mtime]
    if stale:
        print(f"UT_OPT_ERROR: SQL 围栏已过期（这些 SQL 晚于最近围栏: {stale}）——"
              f"产物变→围栏重跑→才进 UT（回路铁律）", file=sys.stderr)
        return 2

    # 依赖数据库：延迟导入（与 check_db 探活配合）
    from dws_db import create_executor_for_schema
    schema = ts_v2["meta"]["target"]["f_table"]["schema"]
    try:
        executor = create_executor_for_schema(schema, role="admin")
    except Exception as e:
        print(f"UT_OPT_NO_DB: 数据源不可用（{e}）——环境问题归人", file=sys.stderr)
        return 3

    # 1. ALTER（变更单缺失=流程顺序错——先 assemble_ddl_opt 再 UT，与环境问题分开报）
    try:
        tables = sorted({f.get("target_table", "") for f in change["fields"]} |
                        {t for f in change["fields"] for t in f.get("intermediate_tables", [])})
        alters = apply_alters(executor, Path(args.ddl_dir), tables, schema)
    except ValueError as e:
        print(f"UT_OPT_ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"UT_OPT_ENV: ALTER 失败（表不存在=环境问题归人）: {e}", file=sys.stderr)
        return 3

    # 参数值解析（与 ut_execute 同款三层兜底：test_params 配置 > ts 默认值 > 类型兜底；
    # 平台变量形态内默认值在 substitute_params 里兜底——配置优先）
    from config_paths import db_sources_path
    param_values = resolve_all_params(ts_v2, str(db_sources_path()))

    # 2. EXPLAIN 单侧真跑（新 SELECT——opt 无 6a 前置故内嵌）
    explains = run_explain_single(executor, ts_v2, Path(args.etl_dir), Path(args.ts),
                                  param_values)

    # 3. 写路径（共享内核：load_mode 真形态+写前清理）+ merge 族幂等第二遍
    writes = []
    tables_meta = ts_v2.get("tables", {}) or {}
    design = ts_v2.get("design", {}) or {}
    global_bk = design.get("business_key", [])
    audit_fields = design.get("audit_fields", {}) or {}
    for rule_code, rule in ts_v2.get("rules", {}).items():
        select_sql = read_select(Path(args.etl_dir), rule_code)
        if not select_sql:
            continue
        try:
            select_sql = substitute_params(select_sql, param_values)
        except ValueError as e:
            writes.append({"rule": rule_code, "status": "FAIL",
                           "error_type": "ENV", "detail": str(e)})
            continue
        target = rule.get("target_table", "")
        if not target:
            continue
        t_short = target.rsplit(".", 1)[-1] if "." in target else target
        tbl_fields = (tables_meta.get(t_short) or {}).get("fields", [])
        wp = execute_write_path(executor, rule_code, target, select_sql,
                                tbl_fields, rule.get("load_mode", "truncate_table"),
                                rule.get("write_condition", ""), rule_output_fields(rule))
        writes.append(wp)
        # merge 族：幂等第二遍（WHEN MATCHED 覆盖+生产重跑安全性镜像）
        if wp["status"] == "PASS" and rule.get("load_mode") in ("merge_into", "update"):
            writes.append(verify_merge_idempotent(executor, rule_code, target,
                                                  wp["insert_sql"]))

    # 4. 资产数据检查（run_ut_check 全集——2026-10-26 豁免移除：UT 是资产质量门）
    ut_checks = []
    for target in sorted({w_target for w_target in
                          (r.get("target_table") or (r.get("rule") and
                           (ts_v2.get("rules", {}).get(r["rule"], {}) or {}).get("target_table"))
                           for r in ts_v2.get("rules", {}).values()) if w_target}):
        t_short = target.rsplit(".", 1)[-1] if "." in target else target
        tbl_bk = (tables_meta.get(t_short) or {}).get("business_key") or global_bk
        for c in run_ut_check(executor, target, tbl_bk, audit_fields):
            ut_checks.append({"table": t_short, **c})

    nulls = check_new_column_nulls(executor, ts_v2, schema)

    # DQ 段（2026-09-14 补环）：重做后的 DQ 在变更现场真跑——上生产的检查，变更后必须执行验证。
    # 规则来源 load_dq_rules（arc_tmp 的 dq.json 优先[producer 重做装配后] / 旧 ts.dq_rules 兜底）；
    # 数据不完整（EXPLAIN/写路径有失败）时 DQ 结果无意义，跳过。DQ ALERT 同样阻断出口（闸口②' 人判）。
    dq_results = []
    dq_note = ""
    dq_rules_list = load_dq_rules(Path(args.ts).parent)
    if dq_rules_list:
        if all(r["status"] == "PASS" for r in explains + writes) and (explains or writes):
            dq_results = run_dq_checks(executor, Path(args.ts).parent / "dq",
                                       dq_rules_list, param_values)
        else:
            dq_note = "EXPLAIN/写路径存在失败——DQ 未执行（修复后重跑自带）"
            print(f"⏭️ DQ 跳过：{dq_note}", file=sys.stderr)

    Path(args.report).write_text(
        render_report(ts_v2, alters, explains, writes, ut_checks, nulls, dq_results),
        encoding="utf-8")
    failed = (any(r["status"] in ("FAIL", "ERROR") for r in explains + writes)
              or any(c["status"] == "FAIL" for c in ut_checks))
    dq_alert = sum(1 for d in dq_results if d["status"] == "ALERT")
    dq_bad = sum(1 for d in dq_results if d["status"] in ("FAIL", "MISSING"))
    print(f"ut_report_opt: {args.report}")
    null_notes = [n for n in nulls if n["note"]]
    print(f"explain: {len(explains)} 规则, writes: {len(writes)} 条, "
          f"ut_checks: {len(ut_checks)} 项, result: {'FAIL' if failed else 'PASS'}")
    if dq_results or dq_note:
        print(f"DQ: ✅{sum(1 for d in dq_results if d['status'] == 'PASS')} 通过  "
              f"🚨{dq_alert} 告警  ❌{dq_bad} 失败/缺失")
    for n in null_notes:
        print(f"  ⚠️ 新列空值: {n['table']}.{n['col']} {n['note']}")
    return 1 if (failed or dq_alert or dq_bad) else 0


if __name__ == "__main__":
    sys.exit(main())
