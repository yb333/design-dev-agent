#!/usr/bin/env python3
"""
UT 预检（快，秒级）：回退 → DDL → SELECT 预检

不写数据，只验证：
1. DDL 能建表成功
2. SELECT 能跑通（类型/字段匹配正确）

agent 分步调用：precheck 通过后再跑 ut_execute.py。

用法:
  python ut_precheck.py --ts ts.json --select-dir etl/ --ddl-dir ddl/
  退出码: 0=全通过, 1=有失败, 2=连库/配置错误
"""

import sys
import os
import json
import argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

# dws_db 在 design-dev-shared 公共库（与本 skill 平级）；run_ut 仍在同目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dws_db import create_executor, load_test_params
from run_ut import substitute_params, resolve_all_params, read_select, inject_tablesample, resolve_sample_blocks


def main():
    parser = argparse.ArgumentParser(description="UT 预检（回退+DDL+SELECT，不写数据）")
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--select-dir", required=True, help="ETL SQL 目录（etl/）")
    parser.add_argument("--ddl-dir", required=True, help="DDL 目录（ddl/）")
    parser.add_argument("--db-config", default="", help="db-sources.json 路径")
    parser.add_argument("--source", default="", help="数据源名")
    parser.add_argument("--rollback-dir", default="", help="回退脚本目录")
    parser.add_argument("--skip-ddl", action="store_true", help="跳过DDL执行")
    parser.add_argument("--result", default="", help="预检结果输出路径（JSON，默认 ts 同级 ut_precheck_result.json）")
    parser.add_argument("--sample-blocks", type=int, default=0, help="主表块采样百分比（如 10=SYSTEM(10)），0=不采样。开发环境加速用")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    rules = ts.get("rules", {})
    data_flow = ts.get("data_flow", {})

    # 连库
    try:
        target_schema = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", "")
        source = args.source
        if not source and target_schema:
            config_path = args.db_config or os.environ.get(
                "DB_CONFIG", str(Path.home() / ".config" / "opencode" / "db-sources.json"))
            from dws_db import resolve_source_by_schema
            source = resolve_source_by_schema(config_path, target_schema)
        # 两个 role：admin 跑 DDL（建表删表），etl 跑 SELECT 预检（查数据）
        ddl_executor = create_executor(args.db_config, source, role="admin")
        etl_executor = create_executor(args.db_config, source, role="etl")
    except Exception as e:
        print(f"错误: 连库失败: {e}", file=sys.stderr)
        sys.exit(2)

    # 参数替换
    config_path = args.db_config or os.environ.get(
        "DB_CONFIG", str(Path.home() / ".config" / "opencode" / "db-sources.json"))
    param_values = resolve_all_params(ts, config_path)

    print(f"数据源: {ddl_executor.get_current_source()}（schema: {target_schema}）")
    print(f"账号: DDL→admin, SELECT→etl")
    if param_values:
        print(f"参数替换: {param_values}")
    print(f"规则数: {len(rules)}")
    print()

    ddl_dir = Path(args.ddl_dir)
    rb_dir = Path(args.rollback_dir) if args.rollback_dir else ddl_dir.parent / "ddl_rollback"

    # 按 schedule_groups 顺序
    schedule_groups = data_flow.get("schedule_groups", [])
    if not schedule_groups:
        schedule_groups = [{"sequence": r.get("exec_sequence", 1), "rules": [code]}
                           for code, r in rules.items()]

    results = []
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

            _, table = (target.split(".", 1) + [""])[:2] if "." in target else ("", target)
            is_view = rule.get("is_view_step", False)
            r_result = {"rule": rule_code, "target": target}

            print(f"--- {rule_code}: {target} ---")

            if prev_failed:
                r_result["status"] = "SKIP"
                r_result["detail"] = "前序规则失败，级联跳过"
                print(f"  ⏭️ 级联跳过（前序失败）")
                results.append(r_result)
                continue

            # 视图规则：回退 + DDL（视图不跑 SELECT 预检）—— 用 admin 账号
            if is_view:
                rb_file = rb_dir / f"rollback_create_view_{table}.sql"
                if rb_file.exists():
                    ddl_executor.execute(substitute_params(rb_file.read_text(encoding="utf-8"), param_values))

                view_file = ddl_dir / f"create_view_{table}.sql"
                if view_file.exists():
                    r = ddl_executor.execute(substitute_params(view_file.read_text(encoding="utf-8"), param_values))
                    r_result["status"] = "PASS" if r.success else "FAIL"
                    r_result["detail"] = r.summary()
                    print(f"  {'✅' if r.success else '❌'} 视图DDL: {r.summary()}")
                else:
                    r_result["status"] = "SKIP"
                    r_result["detail"] = f"视图DDL未找到: {view_file.name}"
                results.append(r_result)
                continue

            # 表规则：回退 → DDL → SELECT 预检
            if not args.skip_ddl:
                # 回退（admin 账号）
                rb_file = rb_dir / f"rollback_create_table_{table}.sql"
                if rb_file.exists():
                    r_rb = ddl_executor.execute(substitute_params(rb_file.read_text(encoding="utf-8"), param_values))
                    print(f"  {'🔄' if r_rb.success else '⚠️'} 回退: {rb_file.name}")

                # DDL（admin 账号）
                ddl_file = ddl_dir / f"create_table_{table}.sql"
                if ddl_file.exists():
                    r = ddl_executor.execute(substitute_params(ddl_file.read_text(encoding="utf-8"), param_values))
                    if not r.success:
                        r_result["status"] = "FAIL"
                        r_result["error_type"] = "DDL"
                        r_result["detail"] = f"DDL失败: {r.error[:100]}"
                        print(f"  ❌ DDL失败: {r.error[:100]}")
                        results.append(r_result)
                        prev_failed = True
                        continue
                    print(f"  ✅ DDL: {r.summary()}")
                else:
                    print(f"  ⚠️ DDL未找到: {ddl_file.name}")

            # SELECT 预检
            select_sql = read_select(Path(args.select_dir), rule_code)
            if not select_sql:
                r_result["status"] = "SKIP"
                r_result["detail"] = "SELECT文件未找到"
                print(f"  ⏭️ SELECT文件未找到")
                results.append(r_result)
                continue

            select_sql = substitute_params(select_sql, param_values)
            # 采样：CLI参数优先，不传则从 db-sources.json 的 security.sample_blocks 读默认
            sample_n = resolve_sample_blocks(config_path, args.sample_blocks)
            select_sql = inject_tablesample(select_sql, sample_n)
            r_pre = etl_executor.execute(select_sql)
            if not r_pre.success:
                error_msg = r_pre.error[:200] if r_pre.error else "未知错误"
                error_type = "SQL" if any(k in error_msg.upper() for k in ["COLUMN", "TYPE", "SYNTAX", "DOES NOT EXIST"]) else "ENV"
                r_result["status"] = "FAIL"
                r_result["error_type"] = error_type
                r_result["detail"] = f"SELECT预检失败({error_type}): {error_msg}"
                print(f"  ❌ SELECT预检失败({error_type}): {error_msg}")
                results.append(r_result)
                prev_failed = True
                continue

            pre_cols = len(r_pre.columns) if r_pre.columns else 0
            pre_rows = len(r_pre.rows) if r_pre.rows else 0
            r_result["status"] = "PASS"
            r_result["detail"] = f"SELECT预检通过: {pre_rows}行, {pre_cols}列"
            r_result["pre_cols"] = pre_cols
            r_result["pre_rows"] = pre_rows
            print(f"  ✅ SELECT预检: {pre_rows}行, {pre_cols}列")
            results.append(r_result)

    # 输出结果
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")

    print()
    print(f"预检汇总: ✅{passed} 通过  ❌{failed} 失败  ⏭️{skipped} 跳过")

    # 写结果文件（供 ut_execute 读）——默认放 _internal/ 过程产物目录
    internal_dir = ts_path.parent / "_internal"
    internal_dir.mkdir(exist_ok=True)
    result_path = args.result or str(internal_dir / "ut_precheck_result.json")
    Path(result_path).write_text(json.dumps({
        "results": results,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果: {result_path}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
