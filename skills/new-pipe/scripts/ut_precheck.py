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

    # 回退结果明确标识（2026-09-03 用户反馈：容忍只该对首次——后续轮回退执行
    # 成功与否必须说清楚，不然分不清"没跑"和"跑失败被容忍"）
    rb_ok = rb_fail = 0
    def _rollback(path: Path):
        nonlocal rb_ok, rb_fail
        r = _run(path)
        if r.success:
            rb_ok += 1
            print(f"  ✅ 回退成功: {path.name}{f'（{r.summary()}）' if r.summary() else ''}")
        else:
            rb_fail += 1
            print(f"  ⚠️ 回退失败(容忍——首次对象不存在属正常,非首次需查): {path.name} | {r.error[:80]}")
    if i_view_short:
        rb = rb_dir / f"rollback_create_view_{i_view_short}.sql"
        if rb.exists():
            _rollback(rb)
    for tb in sorted(table_shorts):
        rb = rb_dir / f"rollback_create_table_{tb}.sql"
        if rb.exists():
            _rollback(rb)
    if rb_ok or rb_fail:
        print(f"  回退汇总: ✅{rb_ok} 成功  ⚠️{rb_fail} 失败(容忍)")

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


# ── 执行计划两门槛（2026-09-02 第二批，用户定调：只做这两个，其他性能分析暂不做）──
# 纯 EXPLAIN（毫秒级零执行成本——两门槛都是计划形状信号，无需 ANALYZE 实际行数）。
# 不下推判据=Data Node Scan（官方）；首版误用 Row Adapter 已纠正（行列转换算子非判据）。
# 过程可视：计划原文全量落盘 _internal/diagnose/plan_{rule}.txt（好坏都留，人可回溯），
# stdout 只出结论。提示级不阻断（性能归人判——与质检体系"披露不代答"一致）。
import re as _re

# STREAM 算子计数：所有 Streaming/Stream 算子节点（Gather/Redistribute/Broadcast 及
# PART 变体——type: 任意值都算），Streaming (type: GATHER) / Stream[name:S1, type: ...] 格式都认
_STREAM_PATTERN = _re.compile(
    r"(?:Streaming|Stream)\s*[\(\[][^)\]]*?type\s*:", _re.IGNORECASE)
# 不下推标志（华为云《语句下推调优》官方判据，2026-09-02 查证）：
#   计划中出现 Data Node Scan 节点（伴随 _REMOTE_TABLE_QUERY_）= 不可下推——
#   可下推部分下推、剩余中间结果拉到 CN 执行，CN 成性能瓶颈；
#   出现 Streaming 节点 = 可下推（分布式计划）。Row Adapter 只是行列转换算子
#   （混合存储合法出现），不是判据（首版误用已纠正）。
_NO_PUSHDOWN_MARKERS = ("Data Node Scan",)
STREAM_LIMIT = 50   # 算子出现个数上限（过多→大量线程消耗、性能下降）


def _explain_check(executor, sql: str, rule_code: str, ts_path) -> tuple[list[str], str]:
    """纯 EXPLAIN 拿计划文本，跑两门槛：①不下推 ②STREAM 算子数≤50。
    返回 (问题列表[空=通过], 计划落盘路径)。EXPLAIN 失败=跳过门槛（披露不阻断）。"""
    r = executor.execute(f"EXPLAIN {sql}")
    if not r.success:
        return [f"EXPLAIN 失败（计划门槛跳过）: {(r.error or '')[:100]}"], ""
    plan_text = "\n".join(str(v) for row in (r.rows or []) for v in row.values())
    plan_path = ts_path.parent / "_internal" / "diagnose" / f"plan_{rule_code}.txt"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(f"-- EXPLAIN {rule_code}\n{sql}\n\n{plan_text}\n", encoding="utf-8")
    issues = []
    streams = _STREAM_PATTERN.findall(plan_text)
    if len(streams) > STREAM_LIMIT:
        issues.append(f"STREAM 算子 {len(streams)} 个 > {STREAM_LIMIT}"
                      f"（gather/redistribute/broadcast 过多→大量线程消耗性能下降，人判改写/分布键）")
    hits = [m for m in _NO_PUSHDOWN_MARKERS if m in plan_text]
    if hits:
        remote = "（伴随 _REMOTE_TABLE_QUERY_）" if "_REMOTE_TABLE_QUERY_" in plan_text else ""
        issues.append(f"疑似不下推（计划含 {'/'.join(hits)}{remote}——官方判据：中间结果拉回 CN 执行，"
                      f"CN 成瓶颈；常见诱因：不支持下推的函数/语法/分布列不齐，人判改写）")
    return issues, str(plan_path)


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
            full_sql = select_sql  # 未采样版（计划分析用——TABLESAMPLE 会歪曲行数估算与计划形状）
            # 采样：CLI参数优先，不传则从 db-sources.json 的 security.sample_blocks 读默认
            sample_n = resolve_sample_blocks(config_path, args.sample_blocks)
            select_sql = inject_tablesample(select_sql, sample_n)
            sample_note = f"TABLESAMPLE {sample_n}" if sample_n else "全量"
            print(f"  ⏱️ SELECT预检（{sample_note}）...")
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
            # 执行计划两门槛（未采样 SQL；计划原文落盘可回溯；提示级不阻断——性能人判）
            # 成功也打印结论行——静默通过看起来像"检查没了"（2026-09-03 内网反馈）
            plan_issues, plan_file = _explain_check(etl_executor, full_sql, rule_code, ts_path)
            r_result["plan_issues"] = plan_issues
            if plan_file:
                r_result["plan_file"] = plan_file
            if plan_issues:
                for pi in plan_issues:
                    print(f"  ⚠️ 计划门槛: {pi}")
            else:
                streams = 0
                try:
                    streams = len(_STREAM_PATTERN.findall(Path(plan_file).read_text(encoding="utf-8")))
                except Exception:
                    pass
                print(f"  📋 计划检查: 通过（STREAM {streams}/{STREAM_LIMIT}，无 Data Node Scan）→ {plan_file}")
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
