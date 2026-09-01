#!/usr/bin/env python3
"""
UT 预检（快，秒级）：回退 → DDL → SELECT 预检

不写数据，只验证：
1. DDL 能建表成功
2. SELECT 能跑通（类型/字段匹配正确）

agent 分步调用：precheck 通过后再跑 ut_execute.py。

用法:
  python ut_precheck.py --ts ts.json --etl-dir etl/ --ddl-dir ddl/
  退出码: 0=全通过, 1=有失败, 2=连库/配置错误
"""

import sys
import os
import json
import argparse
from pathlib import Path

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

# dws_db/config_paths/run_ut 在 shared 公共库（上方 bootstrap 已接通）
from dws_db import create_executor, load_test_params
from config_paths import db_sources_path
from run_ut import substitute_params, resolve_all_params, read_select, inject_tablesample, resolve_sample_blocks


def _deploy_all_ddl(ddl_executor, ddl_dir: Path, rb_dir: Path,
                    table_shorts, i_view_short: str, param_values: dict) -> list:
    """统一部署全部生成的 DDL（视图=F表配套镜像，不是规则——按规则循环会漏）。

    顺序：回退（先视图后表；失败容忍——首次执行时对象不存在，DROP 可能报错）→
    建表 → 建 I 视图。**部署必须全部成功**（表和视图一样，失败即收集返回、整体
    终止）——UT 里建不成功的 DDL，部署生产就是生产问题；只有回退可以容忍。
    """
    def _run(path: Path):
        return ddl_executor.execute(substitute_params(path.read_text(encoding="utf-8"), param_values))

    if i_view_short:
        rb = rb_dir / f"rollback_create_view_{i_view_short}.sql"
        if rb.exists():
            r = _run(rb)
            print(f"  {'🔄' if r.success else '⚠️'} 回退(容忍): {rb.name}")
    for tb in sorted(table_shorts):
        rb = rb_dir / f"rollback_create_table_{tb}.sql"
        if rb.exists():
            r = _run(rb)
            print(f"  {'🔄' if r.success else '⚠️'} 回退(容忍): {rb.name}")

    errors = []
    for tb in sorted(table_shorts):
        f = ddl_dir / f"create_table_{tb}.sql"
        if not f.exists():
            print(f"  ⚠️ DDL未找到: {f.name}")
            continue
        r = _run(f)
        if r.success:
            print(f"  ✅ 建表 {tb}: {r.summary()}")
        else:
            print(f"  ❌ 建表失败 {tb}: {r.error[:100]}")
            errors.append(f"{tb}: {r.error[:100]}")

    if i_view_short:
        f = ddl_dir / f"create_view_{i_view_short}.sql"
        if f.exists():
            r = _run(f)
            if r.success:
                print(f"  ✅ I视图DDL: {r.summary()}")
            else:
                print(f"  ❌ I视图DDL失败: {r.error[:100]}")
                errors.append(f"view_{i_view_short}: {r.error[:100]}")
    return errors


def main():
    parser = argparse.ArgumentParser(description="UT 预检（回退+DDL+SELECT，不写数据）")
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--etl-dir", dest="etl_dir", required=True,
                        help="ETL SQL 目录（etl/）")
    parser.add_argument("--ddl-dir", required=True, help="DDL 目录（ddl/）")
    parser.add_argument("--db-config", default="", help="db-sources.json 路径")
    parser.add_argument("--source", default="", help="数据源名")
    parser.add_argument("--rollback-dir", default="", help="回退脚本目录")
    parser.add_argument("--skip-ddl", action="store_true", help="跳过DDL执行")
    parser.add_argument("--result", default="", help="预检结果输出路径（JSON，默认 ts 同级 ut_precheck_result.json）")
    parser.add_argument("--sample-blocks", type=int, default=None, help="主表块采样百分比（如 10=SYSTEM(10)）。不传=读 config 默认；0=强制不采样；N>0=采样。开发环境加速用")
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
                "DB_CONFIG", str(db_sources_path()))
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
        "DB_CONFIG", str(db_sources_path()))
    param_values = resolve_all_params(ts, config_path)

    print(f"数据源: {ddl_executor.get_current_source()}（schema: {target_schema}）")
    print(f"账号: DDL→admin, SELECT→etl")
    if param_values:
        print(f"参数替换: {param_values}")
    print(f"规则数: {len(rules)}")
    print()

    ddl_dir = Path(args.ddl_dir)
    rb_dir = Path(args.rollback_dir) if args.rollback_dir else ddl_dir.parent / "ddl_rollback"
    # I 视图配套部署（F 表镜像；target 短名比对，多规则写 F 表只部署一次）
    _target_meta = ts.get("meta", {}).get("target", {}) or {}
    f_table_short = (_target_meta.get("f_table", {}) or {}).get("table", "").rsplit(".", 1)[-1]
    i_view_short = (_target_meta.get("i_view", {}) or {}).get("table", "").rsplit(".", 1)[-1]
    i_view_deployed = False

    # init 阶段先（建基线），增量阶段后——符合现实部署顺序
    init_section = ts.get("init") or {}
    init_rules = (init_section.get("rules") or {}) if isinstance(init_section, dict) else {}
    all_rules = dict(rules)
    all_rules.update(init_rules)

    init_groups = []
    if init_rules:
        init_sorted = sorted(init_rules.items(), key=lambda kv: (kv[1].get("exec_sequence", 1), kv[0]))
        init_groups = [{"sequence": 0, "rules": [c for c, _ in init_sorted]}]

    inc_groups = data_flow.get("schedule_groups", [])
    if not inc_groups:
        inc_groups = [{"sequence": r.get("exec_sequence", 1), "rules": [code]}
                       for code, r in rules.items()]

    # ── DDL 统一部署（生成的都执行；建表失败整体终止——后续 SELECT 预检无意义）──
    if not args.skip_ddl:
        _table_shorts = set((ts.get("tables") or {}).keys()) or {f_table_short}
        ddl_errors = _deploy_all_ddl(ddl_executor, ddl_dir, rb_dir,
                                     _table_shorts, i_view_short, param_values)
        if ddl_errors:
            print(f"\n❌ DDL 部署失败 {len(ddl_errors)} 张表，终止预检:", file=sys.stderr)
            for e in ddl_errors:
                print(f"  - {e}", file=sys.stderr)
            result_path = Path(args.result) if args.result else Path("ut_precheck_result.json")
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(
                {"status": "FAIL", "error_type": "DDL", "errors": ddl_errors},
                ensure_ascii=False, indent=2), encoding="utf-8")
            sys.exit(1)
        print()

    results = []
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

            _, table = (target.split(".", 1) + [""])[:2] if "." in target else ("", target)
            r_result = {"rule": rule_code, "target": target}

            print(f"--- {rule_code}: {target} ---")

            if prev_failed:
                r_result["status"] = "SKIP"
                r_result["detail"] = "前序规则失败，级联跳过"
                print(f"  ⏭️ 级联跳过（前序失败）")
                results.append(r_result)
                continue

            # SELECT 预检
            select_sql = read_select(Path(args.etl_dir), rule_code)
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
            # 真 0 行 = 静默空关联的最强信号（关联类型/内容对不上不报错，只 0 匹配）。
            # 不阻断（过滤条件当天无数据也可能是合理 0 行；采样过小同此），给排查方向。
            if pre_rows == 0:
                zero_note = "⚠ 0行——源表有数据却查不出：疑似关联/过滤条件全灭或采样过小，核对关联条件"
                r_result["detail"] += f"（{zero_note}）"
                print(f"  ⚠️ SELECT预检 0 行: 疑似关联/过滤全灭，核对关联条件")
            else:
                print(f"  ✅ SELECT预检: {pre_rows}行, {pre_cols}列")
            r_result["pre_cols"] = pre_cols
            r_result["pre_rows"] = pre_rows
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
