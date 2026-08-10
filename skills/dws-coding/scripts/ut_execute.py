#!/usr/bin/env python3
"""
UT 执行（慢，分钟级）：load_mode预处理 → INSERT → UT检查 → 报告

在 ut_precheck.py 通过后调用。把 SELECT 结果灌入目标表并做数据质量检查。

用法:
  python ut_execute.py --ts ts.json --select-dir etl/ --ddl-dir ddl/ --report ut_report.md
  退出码: 0=全通过, 1=有失败, 2=连库/配置错误
"""

import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

# dws_db 在 design-dev-shared 公共库（与本 skill 平级）；run_ut 仍在同目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dws_db import create_executor
from run_ut import substitute_params, resolve_all_params, read_select, wrap_insert, wrap_write, run_ut_check, inject_tablesample, resolve_sample_blocks


def main():
    parser = argparse.ArgumentParser(description="UT 执行（INSERT+UT检查，慢操作）")
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--select-dir", required=True, help="ETL SQL 目录（etl/）")
    parser.add_argument("--ddl-dir", required=True, help="DDL 目录（ddl/）")
    parser.add_argument("--db-config", default="", help="db-sources.json 路径")
    parser.add_argument("--source", default="", help="数据源名")
    parser.add_argument("--report", default="", help="UT 报告输出路径（ut_report.md）")
    parser.add_argument("--precheck-result", default="", help="预检结果 JSON（默认 ts 同级 ut_precheck_result.json）")
    parser.add_argument("--sample-blocks", type=int, default=0, help="主表块采样百分比（如 10=SYSTEM(10)），0=不采样。开发环境加速用")
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
                "DB_CONFIG", str(Path.home() / ".config" / "opencode" / "db-sources.json"))
            from dws_db import resolve_source_by_schema
            source = resolve_source_by_schema(config_path, target_schema)
        # 本脚本只做数据读写（TRUNCATE/INSERT/UT检查），用 etl 账号；DDL 在 ut_precheck 阶段用 admin 已建好
        executor = create_executor(args.db_config, source, role="etl")
    except Exception as e:
        print(f"错误: 连库失败: {e}", file=sys.stderr)
        sys.exit(2)

    config_path = args.db_config or os.environ.get(
        "DB_CONFIG", str(Path.home() / ".config" / "opencode" / "db-sources.json"))
    param_values = resolve_all_params(ts, config_path)

    print(f"数据源: {executor.get_current_source()}（schema: {target_schema}）")
    print()

    schedule_groups = data_flow.get("schedule_groups", [])
    if not schedule_groups:
        schedule_groups = [{"sequence": r.get("exec_sequence", 1), "rules": [code]}
                           for code, r in rules.items()]

    all_results = []
    prev_failed = False

    for group in schedule_groups:
        for rule_code in group.get("rules", []):
            rule = rules.get(rule_code)
            if not rule:
                continue

            target = rule.get("target_table", "")
            if target and "." not in target:
                f_schema = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", "")
                if f_schema:
                    target = f"{f_schema}.{target}"

            is_view = rule.get("is_view_step", False)
            rule_result = {"rule": rule_code, "target": target, "checks": []}

            print(f"--- {rule_code}: {target} ---")

            # 视图规则：预检已建好，跳过
            if is_view:
                pre = precheck_results.get(rule_code, {})
                rule_result["status"] = pre.get("status", "SKIP")
                rule_result["detail"] = "视图已在预检阶段完成"
                all_results.append(rule_result)
                continue

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
            select_sql = read_select(Path(args.select_dir), rule_code)
            if not select_sql:
                rule_result["status"] = "SKIP"
                rule_result["detail"] = "SELECT文件未找到"
                all_results.append(rule_result)
                continue
            select_sql = substitute_params(select_sql, param_values)
            # 采样：CLI参数优先，不传则从 db-sources.json 的 security.sample_blocks 读默认
            sample_n = resolve_sample_blocks(config_path, args.sample_blocks)
            select_sql = inject_tablesample(select_sql, sample_n)

            # load_mode 预处理（模拟平台写入前的清空动作）
            load_mode = rule.get("load_mode", "truncate_table")
            write_condition = rule.get("write_condition", "")
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

            # 写入语句（按 load_mode 拼 INSERT 或 MERGE）
            target_short = target.rsplit(".", 1)[-1] if "." in target else target
            tbl_fields = ts.get("tables", {}).get(target_short, {}).get("fields", [])
            if not tbl_fields:
                tbl_fields = rule.get("fields", [])
            insert_sql = wrap_write(select_sql, target, tbl_fields, load_mode, write_condition)

            print(f"  ⏳ INSERT 执行中...")
            r = executor.execute(insert_sql)
            if not r.success:
                error_msg = r.error[:200] if r.error else "未知错误"
                error_type = "SQL" if any(k in error_msg.upper() for k in ["COLUMN", "TYPE", "SYNTAX", "DOES NOT EXIST"]) else "ENV"
                rule_result["status"] = "FAIL"
                rule_result["error_type"] = error_type
                rule_result["detail"] = f"INSERT失败: {error_msg}"
                print(f"  ❌ INSERT失败({error_type}): {error_msg}")
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

            all_results.append(rule_result)
            print()

    # 汇总报告
    passed = sum(1 for r in all_results if r["status"] == "PASS")
    failed = sum(1 for r in all_results if r["status"] == "FAIL")
    skipped = sum(1 for r in all_results if r["status"] == "SKIP")

    report_lines = []
    report_lines.append("# UT 报告")
    report_lines.append(f"> 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("")
    report_lines.append(f"**汇总**: ✅{passed} 通过  ❌{failed} 失败  ⏭️{skipped} 跳过")
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
    print(f"UT 报告: {report_path}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
