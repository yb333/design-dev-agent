"""ut_opt —— 优化模式 UT（2026-10-26 统一 UT 重构：opt 编排壳）。

架构定调（用户多轮拍板）：优化与新建的 UT 本质无区别——幂等地执行脚本+对着资产
做数据检查（UT 视角不区分 CREATE/ALTER、不豁免基本项）。本脚本瘦身为 opt 编排壳：
围栏时效+ALTER+EXPLAIN 前置，写路径/数据检查/DQ 全走共享内核（run_ut）。

流程（现成开发环境上）：
  1. 围栏时效校验（回路铁律机器化：产物变→围栏重跑→才进 UT）
  2. 回退（ddl_rollback/rollback_*.sql——UT 幂等重跑：先回到变更前状态再应用，
     首次"列不存在"容忍；回退=变更的逆：TRUNCATE 空表起步+列级结构逆）
  3. 应用 ALTER（ddl/alter_table_*.sql 确定文件名；表不存在=环境归人 exit 3；
     **逐句判定 r.success**——类型 MODIFY 转换失败当场爆）
  4. EXPLAIN 单侧真跑（新 SELECT——opt 无 6a 前置故内嵌；计划两门槛+顶层行数）
  4. 写路径（共享内核 execute_write_path：load_mode 真形态——merge_into 拼真 MERGE
     +写前清理，**多次重跑不再累积残留**；**按名投影包裹**[2026-11-06 统一改造，
     平台实证同款：INSERT(清单) SELECT 清单 FROM (原SELECT) _src——内层序/多列无关，
     新建/优化同一形态]）+ **merge 族幂等第二遍**（verify_merge_idempotent：同语句
     两遍行数不变——两分支覆盖）
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
import re
import sys
from pathlib import Path

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from typing import Dict, List, Optional

from run_ut import (read_select, run_dq_checks, load_dq_rules, rule_output_fields,
                    execute_write_path, verify_merge_idempotent, run_ut_check,
                    substitute_params, resolve_all_params)
from explain_check import _analyze_plan, _parse_actual_rows

# 报告样例上限（不搬全量数据）
SAMPLE_LIMIT = 5


def describe_output_columns(executor, select_sql: str) -> List[str]:
    """describe SELECT 实际输出列（LIMIT 0 不取数）——opt INSERT 列清单权威
    （2026-11-04 问题7 层1：UT 还原平台拼接动作，列清单跟随 SQL 序；权威解释器
    是数据库，零文本解析）。失败/无列返回空列表（调用方 fail loud）。"""
    r = executor.execute(
        f"SELECT * FROM ({select_sql.strip().rstrip(';')}) _ut_cols LIMIT 0")
    if r.success and r.columns:
        return [str(c) for c in r.columns]
    return []


def run_explain_single(executor, ts_v2: dict, etl_dir: Path, ts_path: Path,
                       param_values: Optional[dict] = None) -> List[dict]:
    """逐规则 EXPLAIN ANALYZE 单侧真跑（新 SELECT——opt 无 6a 前置故内嵌）：
    真跑通验证 + 计划两门槛（不下推/STREAM——提示级不阻断）+ 顶层行数（0 行告警）
    + **列存在性对账**（2026-11-04 问题7：opt 不做序对账——逆向档 tables 序[物理/
    DDL 序]与 SQL 投影序独立来源、常态错位，序在 opt 无意义且 coder 老列不许动；
    存在性照拦幻觉列[describe 列 ⊆ 表结构∪ALTER 后]，表有列 SQL 不产的差集披露
    给人[平台配置补的审计列等]——层2 查证平台按名/位置匹配后决定是否升级）。
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
        # 列存在性对账（opt 语义；describe 无列=宁放过披露）
        target = rule.get("target_table", "")
        t_short = target.rsplit(".", 1)[-1] if "." in target else target
        table_cols = [str(f.get("target_field", "")).lower()
                      for f in (tables_meta.get(t_short) or {}).get("fields", [])
                      if isinstance(f, dict) and f.get("target_field")]
        actual_cols = describe_output_columns(executor, new_sql)
        if actual_cols and table_cols:
            actual_l = [c.lower() for c in actual_cols]
            extra = [c for c in actual_l if c not in set(table_cols)]
            if extra:
                results.append({"rule": rule_code, "status": "FAIL",
                                "detail": f"SELECT 输出列不在表结构内: {extra}——"
                                          f"ALTER 变更单缺失或幻觉列（对照 ts.tables/变更单）"})
                continue
            missing = [c for c in table_cols if c not in set(actual_l)]
            if missing:
                row_note += (f"，差集披露：表结构 {len(table_cols)} 列 / SQL 输出 "
                             f"{len(actual_l)} 列（表有 SQL 未产出: {missing[:10]}"
                             f"{'…' if len(missing) > 10 else ''}——平台配置补值列待层2查证）")
            else:
                row_note += f"，列存在性对账 {len(actual_l)} 列全在表内"
        elif not actual_cols:
            row_note += "，列对账跳过（describe 无列返回）"
        results.append({"rule": rule_code, "status": "PASS",
                        "detail": f"真跑通（{row_note}）",
                        "plan_issues": plan_issues, "plan_file": plan_file})
    return results


def check_new_column_nulls(executor, ts_v2: dict, schema: str) -> List[dict]:
    """新列空值检查（写路径后真实数据）：逐目标表统计新列 NULL——兑现 06 §一
    '空值只查新列'的承诺；全 NULL = 疑似新 JOIN 关联不上的信号（LEFT JOIN 常态形态）。
    类型修改列（场景 B·2026-10-22）同款抽查（双跑对比退役后由空值/转换异常守）——
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


def _exec_ddl_script(executor, script: Path, label: str) -> None:
    """逐句执行 DDL 脚本文件（按分号切句、剥空段——与 apply_alters 同款；块/行注释
    前缀 DB 接受）。失败 raise RuntimeError（调用方归环境问题）。"""
    for stmt in [x.strip() for x in script.read_text(encoding="utf-8").split(";") if x.strip()]:
        r = executor.execute(stmt)
        if not r.success:
            raise RuntimeError(f"{label} 失败: {(r.error or '')[:200]}")


def apply_new_table_creates(executor, ddl_dir: Path, tables: List[str]) -> List[str]:
    """新表 CREATE（2026-11-11 缺口补环）：回退段对新表只有 DROP、首次 CREATE 无执行
    路径。此文件由 assemble_ddl_opt 仅为新表产出——存在性=新表判定（确定性文件名，
    不 glob）；CREATE TABLE IF NOT EXISTS 双保险。返回已建表名。"""
    created = []
    for t in sorted(set(tables)):
        p = Path(ddl_dir) / f"create_table_{t}.sql"
        if p.exists():
            _exec_ddl_script(executor, p, f"新表 CREATE（{t}）")
            created.append(t)
    return created


def rebuild_i_view(executor, ddl_dir: Path, ts_v2: dict) -> str:
    """I 视图重建（2026-11-11 实报补环）：ALTER 加列后镜像不重建则 UT 全绿但视图缺新列
    ——平台从 I 视图取数上线即缺列。视图名=ts meta 确定性拼接；文件存在才跑（无 i_view
    资产 assemble_ddl_opt 不产此文件）。返回视图名（未执行返回空）。"""
    iv = (ts_v2.get("meta", {}).get("target", {}) or {}).get("i_view", {}) or {}
    name = (iv.get("table") or "").strip()
    if not name:
        return ""
    p = Path(ddl_dir) / f"create_or_replace_view_{name}.sql"
    if not p.exists():
        return ""
    _exec_ddl_script(executor, p, f"I 视图重建（{name}）")
    return name


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


def run_rollback(executor, rb_dir: Path, tables: List[str], schema: str = "") -> List[dict]:
    """执行回退（UT 重跑幂等——2026-11-04 内网实报补环：ALTER 已应用的重跑
    "column already exists" 归 ENV 假故障；先回退到变更前状态再应用，重跑=从头）。

    两段（2026-11-05 用户定调拆职责——交付件与执行器分家）：
    - 数据清空 TRUNCATE：**本函数运行时执行**（UT 语义=空表起步全量装载，与新建
      DROP+CREATE 同语义——UT 从来是空表起步验证交付物，不是生产历史仿真；不进
      回退脚本交付件）；新表（rollback_create_table_ 文件）跳过——DROP 即清。
    - 结构逆 DDL：执行 rollback_*.sql 脚本语句（纯 DDL——列级逆/新表 DROP）。
    逐句执行**逐句容忍**：首次执行列/表不存在属正常（回退无物可退）；非首次失败
    分色汇总进报告人可查（与 new-pipe ut_precheck 回退容忍同款纪律）。
    缺目录=fail loud（流程顺序错）。
    """
    if not rb_dir.exists():
        raise ValueError(
            f"回退脚本目录缺失: {rb_dir}——先跑 assemble_ddl_opt（产 ddl/ + ddl_rollback/）再执行 UT")
    results = []

    def _exec(table: str, stmt: str):
        r = executor.execute(stmt)
        results.append({
            "table": table,
            "stmt": re.sub(r"\s+", " ", stmt)[:80],
            "ok": bool(r.success),
            "error": (r.error or "")[:80] if not r.success else "",
        })

    for t in tables:
        p = rb_dir / f"rollback_alter_{t}.sql"
        is_new = False
        if not p.exists():
            p = rb_dir / f"rollback_create_table_{t}.sql"
            is_new = True
        if not p.exists():
            raise ValueError(f"回退脚本缺失: rollback_*_{t}.sql（{rb_dir}）——重跑 assemble_ddl_opt")
        if not is_new and schema:
            _exec(t, f"TRUNCATE TABLE {schema}.{t}")   # UT 时数据清空（非交付件）
        # 与 apply_alters 同款切句：注释行与语句同 chunk 合法（注释前缀 DB 接受）
        for stmt in [x.strip() for x in p.read_text(encoding="utf-8").split(";") if x.strip()]:
            _exec(t, stmt)
    return results


def render_report(ts_v2: dict, alters: List[str], explains: List[dict],
                  writes: List[dict], ut_checks: List[dict], nulls: List[dict],
                  dq_results: List[dict] = None,
                  rollbacks: List[dict] = None) -> str:
    rollbacks = rollbacks or []
    _rb_ok = sum(1 for r in rollbacks if r["ok"])
    lines = ["# UT 报告（优化模式·统一 UT 内核）", "",
             f"- ALTER 已应用：{', '.join(alters) or '（无）'}",
             f"- 回退（UT 幂等重跑=空表起步，与新建统一语义）：{_rb_ok}/{len(rollbacks)} 句成功"
             + ("（其余容忍失败——首次对象不存在属正常）" if _rb_ok < len(rollbacks) else ""),
             f"- 数据检查：run_ut_check 全集（行数/主键唯一/审计非空——不豁免）", ""]
    if rollbacks and _rb_ok < len(rollbacks):
        lines.append("**回退容忍失败明细**（非首次出现=需查——对象状态与预期不符）:")
        lines.append("")
        for r in rollbacks:
            if not r["ok"]:
                lines.append(f"- ⚠️ {r['table']}: `{r['stmt']}` — {r['error']}")
        lines.append("")
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
    ap = argparse.ArgumentParser(description="优化模式 UT：回退→CREATE 新表→ALTER→I 视图重建→EXPLAIN/写路径（按名包裹）→资产检查+DQ")
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

    # 1. 回退（UT 幂等重跑——2026-11-04 内网实报补环：ALTER 已应用的重跑
    #    "column already exists" 归 ENV 假故障；先回到变更前状态再应用。
    #    回退表集=与 assemble_ddl_opt 同一确定集合（alter 表 ∪ 全部规则目标表 ∩ 物理表））
    _rb_tables = ({f.get("target_table", "") for f in change["fields"]} |
                  {t for f in change["fields"] for t in f.get("intermediate_tables", [])} |
                  {m.get("target_table", "") for m in change.get("modify_types", [])} |
                  {str(r.get("target_table", "")).rsplit(".", 1)[-1]
                   for r in (ts_v2.get("rules") or {}).values() if r.get("target_table")})
    _rb_tables &= set((ts_v2.get("tables") or {}).keys())
    try:
        rollbacks = run_rollback(executor, Path(args.ddl_dir).parent / "ddl_rollback",
                                 sorted(_rb_tables))
    except ValueError as e:
        print(f"UT_OPT_ERROR: {e}", file=sys.stderr)
        return 2
    _rb_ok = sum(1 for r in rollbacks if r["ok"])
    _rb_fail = len(rollbacks) - _rb_ok
    print(f"回退汇总: ✅{_rb_ok} 成功  ⚠️{_rb_fail} 失败(容忍——首次对象不存在属正常,非首次需查)")

    # 1.5 新表 CREATE（回退→CREATE→ALTER 序列——见 apply_new_table_creates 注释）
    ddl_dir = Path(args.ddl_dir)
    try:
        _created = apply_new_table_creates(executor, ddl_dir, _rb_tables)
    except Exception as e:
        print(f"UT_OPT_ENV: {e}", file=sys.stderr)
        return 3
    for t in _created:
        print(f"新表 CREATE: {t} ✅")

    # 2. ALTER（变更单缺失=流程顺序错——先 assemble_ddl_opt 再 UT，与环境问题分开报）
    try:
        tables = sorted({f.get("target_table", "") for f in change["fields"]} |
                        {t for f in change["fields"] for t in f.get("intermediate_tables", [])})
        alters = apply_alters(executor, ddl_dir, tables, schema)
    except ValueError as e:
        print(f"UT_OPT_ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"UT_OPT_ENV: ALTER 失败（表不存在=环境问题归人）: {e}", file=sys.stderr)
        return 3

    # 2.5 I 视图重建（ALTER 后 F 表结构定型，镜像同步——见 rebuild_i_view 注释）
    try:
        _rebuilt = rebuild_i_view(executor, ddl_dir, ts_v2)
    except Exception as e:
        print(f"UT_OPT_ENV: {e}", file=sys.stderr)
        return 3
    if _rebuilt:
        print(f"I 视图重建: {_rebuilt} ✅")

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
        # 写路径=共享内核**按名投影包裹**（2026-11-06 统一改造，平台实证同款）：
        # INSERT(清单) SELECT 清单 FROM (原SELECT) _src——内层序/多列无关，
        # 新建/优化同一形态（2026-11-04 的 describe 序 column_order 方案随之退役。
        # 2026-11-09 修复：227c13e 半改——run_ut 已删 column_order 参数而本调用点
        # 残留 column_order=actual_cols 致内网 UT TypeError，补上当时未落盘的改动）
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
        render_report(ts_v2, alters, explains, writes, ut_checks, nulls, dq_results,
                      rollbacks),
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
