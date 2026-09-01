#!/usr/bin/env python3
"""
UT 执行（慢，分钟级）：load_mode预处理 → INSERT → UT检查 → 报告

在 ut_precheck.py 通过后调用。把 SELECT 结果灌入目标表并做数据质量检查。

用法:
  python ut_execute.py --ts ts.json --etl-dir etl/ --ddl-dir ddl/ --report ut_report.md
  退出码: 0=全通过, 1=有失败, 2=连库/配置错误
"""

import sys
import os
import json
import argparse
from pathlib import Path

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from datetime import datetime

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

# dws_db/config_paths/run_ut 在 shared 公共库（上方 bootstrap 已接通）；ut_diagnose 同目录
from dws_db import create_executor
from config_paths import db_sources_path
from run_ut import substitute_params, resolve_all_params, read_select, wrap_insert, wrap_write, run_ut_check, inject_tablesample, resolve_sample_blocks, run_dq_checks


def _dump_rule_sql(ts_path: Path, rule_code: str, target_table: str,
                   select_sql: str, insert_sql: str, insert_result: str,
                   ut_checks: list) -> None:
    """落地单规则的 UT 执行 SQL 到 _internal/ut_sql/{rule}.sql（debug 用）。

    含三段：原始 SELECT、拼接 INSERT、UT 检查 SQL，每段注释带执行结果。
    出错时凭此区分是 coder 的 SELECT 错，还是 ut 拼接/检查 SQL 错。

    Args:
        ts_path: ts.json 路径（定位 _internal/）。
        rule_code: 规则号。
        target_table: 目标表全名。
        select_sql: coder 的原始 SELECT（参数已替换，tablesample 已注入）。
        insert_sql: wrap_write 拼接后的 INSERT/MERGE。
        insert_result: INSERT 执行结果摘要（成功带行数/失败带报错）。
        ut_checks: run_ut_check 返回的检查列表（每个含 sql/status/detail）。
    """
    out_dir = ts_path.parent / "_internal" / "ut_sql"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{rule_code}.sql"

    lines = [
        f"/* =====================================================",
        f"   {rule_code} UT 执行 SQL 落地（debug 用，可直接复制到库重跑）",
        f"   目标表: {target_table}",
        f"   落地时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"   ===================================================== */",
        "",
        f"/* ===== 原始 SELECT（coder 产出，参数已替换/tablesample已注入）===== */",
        select_sql.strip().rstrip(";") + ";",
        "",
        f"/* ===== 拼接后 INSERT（wrap_write 产出）===== {insert_result} */",
        insert_sql.strip().rstrip(";") + ";",
        "",
    ]

    if ut_checks:
        lines.append("/* ===== UT 检查 ===== */")
        for c in ut_checks:
            status = c.get("status", "?")
            detail = c.get("detail", "")
            symbol = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
            lines.append(f"/* {c.get('check', '')} — {symbol} {status}: {detail} */")
            sql = c.get("sql", "")
            if sql:
                lines.append(sql.strip().rstrip(";") + ";")
            if c.get("samples"):
                lines.append(f"/* 样例数据: {c['samples'][:3]} */")
            lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


# 类型转换类报错的关键字（DB 报错通常英文）。
# operator does not exist = 裸 JOIN 跨类型（解析期报，自带两侧类型）——也是 conversion 类
_TYPE_ERROR_KEYWORDS = ("invalid input syntax", "for type", "cast", "could not convert",
                        "failed to convert", "invalid value", "operator does not exist")


def _is_type_conversion_error(error_msg: str) -> bool:
    """报错是否属类型转换类（值得跑自动诊断）。"""
    low = (error_msg or "").lower()
    return any(k in low for k in _TYPE_ERROR_KEYWORDS)


def _diagnose_insert_failure(executor, rule: dict, ts: dict, ts_path: Path,
                             error_msg: str = "") -> str:
    """conversion 类报错 → 嫌疑报告（报错分类 + 关联键 ts 反查 + 字段脏数据探测）。

    设计为增益不是依赖：诊断异常/无缓存都诚实返回提示，绝不抛出影响主流程。
    路由建议是漏斗不是证明——有关联嫌疑优先退 designer/人，禁止改字段类型。
    """
    try:
        from ut_diagnose import (
            diagnose_type_error, format_diagnosis, _load_schema_cache,
            classify_db_error, diagnose_join_suspicion, format_suspicion_report,
        )
        cache_path = ts_path.parent / "_internal" / "schema_cache.json"
        entries = diagnose_type_error(executor, rule, ts, cache_path)
        field_diag = format_diagnosis(entries)
        cls = classify_db_error(error_msg)
        suspects = []
        if cls is not None:
            cache = _load_schema_cache(cache_path)
            if cache:
                suspects = diagnose_join_suspicion(rule, ts, cache, executor)
        return format_suspicion_report(error_msg, cls, suspects, field_diag)
    except Exception as e:
        return f"自动诊断异常（无法定位，附原始报错请人排查）: {e}"


def main():
    parser = argparse.ArgumentParser(description="UT 执行（INSERT+UT检查，慢操作）")
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--etl-dir", dest="etl_dir", required=True,
                        help="ETL SQL 目录（etl/）")
    parser.add_argument("--ddl-dir", required=True, help="DDL 目录（ddl/）")
    parser.add_argument("--db-config", default="", help="db-sources.json 路径")
    parser.add_argument("--source", default="", help="数据源名")
    parser.add_argument("--report", default="", help="UT 报告输出路径（ut_report.md）")
    parser.add_argument("--precheck-result", default="", help="预检结果 JSON（默认 ts 同级 ut_precheck_result.json）")
    parser.add_argument("--sample-blocks", type=int, default=None, help="主表块采样百分比（如 10=SYSTEM(10)）。不传=读 config 默认；0=强制不采样；N>0=采样。开发环境加速用")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    rules = ts.get("rules", {})
    design = ts.get("design", {})
    audit_fields = design.get("audit_fields", {})
    business_key = design.get("business_key", [])
    data_flow = ts.get("data_flow", {})

    # 读预检结果（确认表已建好）——默认从 _internal/ 读，读不到直接退出避免误灌数据
    precheck_path = args.precheck_result or str(ts_path.parent / "_internal" / "ut_precheck_result.json")
    if not Path(precheck_path).exists():
        print(f"❌ 预检结果文件不存在: {precheck_path}\n   请先跑 ut_precheck.py（其 --result 路径需与本参数一致）。",
              file=sys.stderr)
        sys.exit(2)
    precheck = json.loads(Path(precheck_path).read_text(encoding="utf-8"))
    precheck_results = {r["rule"]: r for r in precheck.get("results", [])}

    # 连库
    try:
        target_schema = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", "")
        source = args.source
        if not source and target_schema:
            config_path = args.db_config or os.environ.get(
                "DB_CONFIG", str(db_sources_path()))
            from dws_db import resolve_source_by_schema
            source = resolve_source_by_schema(config_path, target_schema)
        # 本脚本只做数据读写（TRUNCATE/INSERT/UT检查），用 etl 账号；DDL 在 ut_precheck 阶段用 admin 已建好
        executor = create_executor(args.db_config, source, role="etl")
    except Exception as e:
        print(f"错误: 连库失败: {e}", file=sys.stderr)
        sys.exit(2)

    config_path = args.db_config or os.environ.get(
        "DB_CONFIG", str(db_sources_path()))
    param_values = resolve_all_params(ts, config_path)

    print(f"数据源: {executor.get_current_source()}（schema: {target_schema}）")
    print()

    # init 阶段先（建基线），增量阶段后（在基线上 merge）——符合现实部署顺序（首次全量→日常增量）
    init_section = ts.get("init") or {}
    init_rules = (init_section.get("rules") or {}) if isinstance(init_section, dict) else {}
    all_rules = dict(rules)
    all_rules.update(init_rules)  # init 规则也进查找表（loop 按 rule_code 取）

    init_groups = []
    if init_rules:
        init_sorted = sorted(init_rules.items(), key=lambda kv: (kv[1].get("exec_sequence", 1), kv[0]))
        init_codes = [c for c, _ in init_sorted]
        init_groups = [{"sequence": 0, "rules": init_codes}]
        print(f"▶ init 阶段（建基线，truncate+全量插）：{init_codes}")

    inc_groups = data_flow.get("schedule_groups", [])
    if not inc_groups:
        inc_groups = [{"sequence": r.get("exec_sequence", 1), "rules": [code]}
                       for code, r in rules.items()]
    if init_rules:
        print(f"▶ 增量阶段（在基线上 merge）")

    all_results = []
    prev_failed = False

    for group in (init_groups + inc_groups):
        for rule_code in group.get("rules", []):
            rule = all_rules.get(rule_code)
            if not rule:
                continue

            target = rule.get("target_table", "")
            if target and "." not in target:
                f_schema = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", "")
                if f_schema:
                    target = f"{f_schema}.{target}"

            rule_result = {"rule": rule_code, "target": target, "checks": []}

            print(f"--- {rule_code}: {target} ---")

            # 预检跳过/失败的规则，级联跳过
            pre = precheck_results.get(rule_code, {})
            if pre.get("status") != "PASS":
                rule_result["status"] = "SKIP"
                rule_result["detail"] = f"预检未通过，跳过执行（{pre.get('detail', '未知')}）"
                print(f"  ⏭️ 跳过（预检未通过）")
                all_results.append(rule_result)
                continue

            if prev_failed:
                rule_result["status"] = "SKIP"
                rule_result["detail"] = "前序规则失败，级联跳过"
                print(f"  ⏭️ 级联跳过")
                all_results.append(rule_result)
                continue

            # 读 SELECT
            select_sql = read_select(Path(args.etl_dir), rule_code)
            if not select_sql:
                rule_result["status"] = "SKIP"
                rule_result["detail"] = "SELECT文件未找到"
                all_results.append(rule_result)
                continue
            select_sql = substitute_params(select_sql, param_values)
            # 采样语义（防"加速导致数据错误"）：采样只当【快速失败闸门】，不做最终审视——
            # SELECT 跑通 ≠ INSERT 全量跑通（目标列类型转换靠行数据触发，采样会漏检脏行）。
            # 流程：truncate_table 模式且采样开启 → 采样试跑 INSERT → 失败秒级快速报 /
            # 通过 → TRUNCATE 清试跑数据 → 全量 INSERT（终审按全量）。
            # ★ 其他 load_mode 不试跑：no_delete/merge 的表混有前序规则成果，试跑数据
            #   无法辨清（TRUNCATE 会伤前序），全量失败由报错直接暴露。
            sample_n = resolve_sample_blocks(config_path, args.sample_blocks)
            load_mode = rule.get("load_mode", "truncate_table")
            write_condition = rule.get("write_condition", "")

            # load_mode 预处理（模拟平台写入前的清空动作）
            if load_mode == "truncate_table":
                executor.execute(f"TRUNCATE TABLE {target}")
                print(f"  🔄 TRUNCATE")
            elif load_mode == "truncate_partition" and write_condition:
                # write_condition 是分区名（如 P_1001）
                executor.execute(f"TRUNCATE TABLE {target} PARTITION ( {write_condition} )")
                print(f"  🔄 TRUNCATE PARTITION {write_condition}")
            elif load_mode == "delete" and write_condition:
                executor.execute(f"DELETE FROM {target} WHERE {write_condition}")
                print(f"  🔄 DELETE WHERE {write_condition}")
            # merge_into/update 不预处理（MERGE 语句自带 upsert 语义）

            # 写入语句构造（试跑/全量共用同一套 wrap）
            target_short = target.rsplit(".", 1)[-1] if "." in target else target
            tbl_fields = ts.get("tables", {}).get(target_short, {}).get("fields", [])
            if not tbl_fields:
                tbl_fields = rule.get("fields", [])
            try:
                _wrap_probe = wrap_write(select_sql, target, tbl_fields, load_mode, write_condition)
            except ValueError as ve:
                # INSERT 列清单解析异常（重复列=CTE 边界错位/重复别名）——规则级 FAIL，不拖垮整轮
                rule_result["status"] = "FAIL"
                rule_result["error_type"] = "SQL"
                rule_result["detail"] = f"INSERT 构造失败: {ve}"
                print(f"  ❌ INSERT 构造失败: {ve}")
                _dump_rule_sql(ts_path, rule_code, target, select_sql, "",
                               f"构造失败: {ve}", [])
                all_results.append(rule_result)
                prev_failed = True
                continue

            # ── 采样试跑（快速失败闸门，仅 truncate_table 模式）──
            trial_used = False
            if sample_n > 0 and load_mode == "truncate_table":
                trial_select = inject_tablesample(select_sql, sample_n)
                trial_insert = wrap_write(trial_select, target, tbl_fields, load_mode, write_condition)
                print(f"  🧪 采样试跑(TABLESAMPLE {sample_n}%)...")
                r_trial = executor.execute(trial_insert)
                if not r_trial.success:
                    error_msg = r_trial.error[:200] if r_trial.error else "未知错误"
                    error_type = "SQL" if any(k in error_msg.upper() for k in ["COLUMN", "TYPE", "SYNTAX", "DOES NOT EXIST"]) else "ENV"
                    rule_result["status"] = "FAIL"
                    rule_result["error_type"] = error_type
                    rule_result["detail"] = f"试跑(采样{sample_n}%)失败: {error_msg}"
                    print(f"  ❌ 试跑失败({error_type}): {error_msg}")
                    # 类型转换类报错 → 自动诊断嫌疑脏数据（增益，不阻断）
                    if _is_type_conversion_error(error_msg):
                        diag = _diagnose_insert_failure(executor, rule, ts, ts_path, error_msg)
                        if diag:
                            rule_result["diagnosis"] = diag
                            print(f"  🔍 {diag.splitlines()[0]}")
                    _dump_rule_sql(ts_path, rule_code, target, trial_select, trial_insert,
                                   f"试跑(采样{sample_n}%)失败({error_type}): {error_msg}", [])
                    all_results.append(rule_result)
                    prev_failed = True
                    continue
                print(f"  ✅ 试跑通过 → TRUNCATE 清试跑数据，全量执行（终审按全量）")
                executor.execute(f"TRUNCATE TABLE {target}")
                trial_used = True

            insert_sql = wrap_write(select_sql, target, tbl_fields, load_mode, write_condition)

            print(f"  ⏳ INSERT 执行中..." + ("（试跑已过，全量）" if trial_used else ""))
            r = executor.execute(insert_sql)
            if not r.success:
                error_msg = r.error[:200] if r.error else "未知错误"
                error_type = "SQL" if any(k in error_msg.upper() for k in ["COLUMN", "TYPE", "SYNTAX", "DOES NOT EXIST"]) else "ENV"
                rule_result["status"] = "FAIL"
                rule_result["error_type"] = error_type
                rule_result["detail"] = f"INSERT失败: {error_msg}"
                print(f"  ❌ INSERT失败({error_type}): {error_msg}")
                # 类型转换类报错 → 自动诊断嫌疑脏数据（增益，不阻断）
                if _is_type_conversion_error(error_msg):
                    diag = _diagnose_insert_failure(executor, rule, ts, ts_path, error_msg)
                    if diag:
                        rule_result["diagnosis"] = diag
                        print(f"  🔍 {diag.splitlines()[0]}")
                # 落地 SQL（失败也要落，这是最需要 debug 的场景）
                _dump_rule_sql(ts_path, rule_code, target, select_sql, insert_sql,
                               f"执行失败({error_type}): {error_msg}", [])
                all_results.append(rule_result)
                prev_failed = True
                continue
            print(f"  ✅ INSERT: {r.summary()}")

            # UT 检查
            ut_checks = run_ut_check(executor, target, business_key, audit_fields)
            rule_result["checks"] = ut_checks

            ut_fails = [c for c in ut_checks if c["status"] == "FAIL"]
            if ut_fails:
                rule_result["status"] = "FAIL"
                rule_result["detail"] = f"UT失败{len(ut_fails)}项"
                for c in ut_checks:
                    symbol = "✅" if c["status"] == "PASS" else "❌" if c["status"] == "FAIL" else "⚠️"
                    print(f"  {symbol} {c['check']}: {c['detail']}")
                prev_failed = True
            else:
                rule_result["status"] = "PASS"
                for c in ut_checks:
                    symbol = "✅" if c["status"] == "PASS" else "⚠️"
                    print(f"  {symbol} {c['check']}: {c['detail']}")

            # 落地 SQL（成功场景：含 INSERT + UT 检查全部 SQL）
            _dump_rule_sql(ts_path, rule_code, target, select_sql, insert_sql,
                           f"执行成功: {r.summary()}", ut_checks)
            all_results.append(rule_result)
            print()

    # ── DQ 检查（数据全部就位后）：契约 0 行=通过，非 0 行=告警 ──
    # DQ 是上生产的制品，UT 里执行验证（SQL 错误/方向反只有执行能暴露）。
    # 数据不完整（有失败/跳过）时 DQ 结果无意义，不执行——修复后重跑 UT 自带。
    dq_results = []
    dq_note = ""
    dq_rules_list = ts.get("dq_rules") or []
    if dq_rules_list:
        if all_results and all(r["status"] == "PASS" for r in all_results):
            print("▶ DQ 检查（0 行=通过，非 0 行=告警）")
            dq_results = run_dq_checks(executor, ts_path.parent / "dq", dq_rules_list, param_values)
            for d in dq_results:
                symbol = {"PASS": "✅", "ALERT": "🚨", "FAIL": "❌", "MISSING": "❓"}.get(d["status"], "?")
                print(f"  {symbol} {d['rule_name']}: {d['detail']}")
        else:
            dq_note = "规则存在失败/跳过，数据不完整——DQ 未执行（修复后重跑 UT 自带 DQ）"
            print(f"⏭️ DQ 跳过：{dq_note}")

    # 汇总报告
    passed = sum(1 for r in all_results if r["status"] == "PASS")
    failed = sum(1 for r in all_results if r["status"] == "FAIL")
    skipped = sum(1 for r in all_results if r["status"] == "SKIP")
    dq_pass = sum(1 for d in dq_results if d["status"] == "PASS")
    dq_alert = sum(1 for d in dq_results if d["status"] == "ALERT")
    dq_bad = sum(1 for d in dq_results if d["status"] in ("FAIL", "MISSING"))

    report_lines = []
    report_lines.append("# UT 报告")
    report_lines.append(f"> 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    # 采样语义标注：试跑只是快速失败闸门，最终审视按全量（防"采样通过"被误读为"全量没问题"）
    _eff_sample = resolve_sample_blocks(config_path, args.sample_blocks)
    if _eff_sample > 0:
        report_lines.append(f"> ⚠️ 采样模式：试跑 TABLESAMPLE({_eff_sample}%) 作快速失败闸门，"
                            f"试跑通过后清表全量执行——**最终审视按全量结果**（仅 truncate_table 规则试跑）")
    report_lines.append("")
    report_lines.append(f"**汇总**: ✅{passed} 通过  ❌{failed} 失败  ⏭️{skipped} 跳过")
    if dq_results or dq_note:
        report_lines.append(f"**DQ**: ✅{dq_pass} 通过  🚨{dq_alert} 告警  ❌{dq_bad} 失败/缺失"
                            f"（0 行=通过，非 0 行=告警——提交部署前必须确认为 0 行）")
    report_lines.append("")
    report_lines.append("## 规则明细")
    report_lines.append("")
    report_lines.append("| 规则 | 目标表 | 状态 | 详情 |")
    report_lines.append("|------|--------|------|------|")
    for r in all_results:
        symbol = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}[r["status"]]
        report_lines.append(f"| {r['rule']} | `{r['target']}` | {symbol} | {r.get('detail', '')} |")
    report_lines.append("")

    has_checks = any(r.get("checks") for r in all_results)
    if has_checks:
        report_lines.append("## UT 检查明细")
        report_lines.append("")
        for r in all_results:
            if r.get("checks"):
                report_lines.append(f"### {r['rule']}（{r['target']}）")
                report_lines.append("")
                report_lines.append("| 检查项 | 结果 | 详情 |")
                report_lines.append("|--------|------|------|")
                for c in r["checks"]:
                    symbol = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(c["status"], "?")
                    report_lines.append(f"| {c['check']} | {symbol} | {c['detail']} |")
                report_lines.append("")

    if dq_results or dq_note:
        report_lines.append("## DQ 检查（0 行=通过，非 0 行=告警）")
        report_lines.append("")
        if dq_note:
            report_lines.append(f"> ⏭️ {dq_note}")
        if dq_results:
            report_lines.append("| 规则 | 文件 | 结果 | 违规行数 | 详情 |")
            report_lines.append("|------|------|------|---------|------|")
            for d in dq_results:
                symbol = {"PASS": "✅", "ALERT": "🚨", "FAIL": "❌", "MISSING": "❓"}.get(d["status"], "?")
                report_lines.append(f"| {d['rule_name']} | `{d['file']}` | {symbol} {d['status']} | {d['rows']} | {d['detail']} |")
            if dq_alert:
                report_lines.append("")
                report_lines.append("**告警样例（违规行）**：")
                for d in dq_results:
                    if d["status"] == "ALERT" and d.get("samples"):
                        report_lines.append(f"- {d['rule_name']}:")
                        for s in d["samples"]:
                            report_lines.append(f"  - {s}")
            report_lines.append("")
            report_lines.append("> **DQ 分流**：执行报错/文件缺失 → 回 coder（SQL 类）；阈值或口径不合理 → 回 designer"
                                " 改 rule_desc（或退 RS 源）；数据真脏 → 人定。中间阈值的结果依赖数据分布，"
                                "人工确认预期后再放行。")
        report_lines.append("")

    if failed:
        report_lines.append("## ⚠️ 问题清单（数据质量类，需人确认根因）")
        report_lines.append("")
        report_lines.append("> **提示**：开发环境数据量/质量与生产不一致，主键重复等问题需结合业务认知判断根因")
        report_lines.append("> （设计问题 / 环境数据脏 / 业务一对多），不能仅凭 UT 结果下结论。")
        report_lines.append("> 下面是客观事实（重复键+样例），请人确认根因后再决定处理方案。")
        report_lines.append("")
        for r in all_results:
            if r["status"] == "FAIL":
                report_lines.append(f"- ❌ **{r['rule']}**（{r['target']}）: {r['detail']}")
                # 类型转换类失败的自动诊断（脏数据定位，贴在 FAIL detail 下）
                if r.get("diagnosis"):
                    for ln in r["diagnosis"].splitlines():
                        report_lines.append(f"  - {ln}")
                for c in r.get("checks", []):
                    if c["status"] == "FAIL" and c.get("samples"):
                        report_lines.append(f"  - {c['check']} 样例:")
                        for row in c["samples"]:
                            report_lines.append(f"    - {row}")

    report_text = "\n".join(report_lines)
    report_path = args.report or str(ts_path.parent / "ut_report.md")
    Path(report_path).write_text(report_text, encoding="utf-8")

    print("=" * 50)
    print(f"UT 汇总: ✅{passed} 通过  ❌{failed} 失败  ⏭️{skipped} 跳过")
    if dq_results or dq_note:
        print(f"DQ 汇总: ✅{dq_pass} 通过  🚨{dq_alert} 告警  ❌{dq_bad} 失败/缺失")
    print(f"UT 报告: {report_path}")

    # DQ 告警同样阻断出口（提交部署前必须确认为 0 行，处置权在闸口② 的人）
    sys.exit(0 if failed == 0 and dq_alert == 0 and dq_bad == 0 else 1)


if __name__ == "__main__":
    main()
