#!/usr/bin/env python3
"""
UT 执行器: DDL + INSERT(包装) + UT检查 + 报告

执行阶段脚本，由 command 调用。不涉及 AI。

流程：
1. 读 ts.json + coder 产的 SELECT 文件
2. 把 SELECT 包装成完整 INSERT（按平台固定规则）
3. 按 schedule_groups 顺序执行：DDL 建表 → INSERT 灌数据
4. 跑 UT 检查（主键唯一/非空/行数）
5. 输出结构化报告

UT 检查项（全脚本化）：
1. DDL 执行通过
2. INSERT 执行通过
3. 记录数合理（>0）
4. 业务主键唯一（business_key）
5. 审计字段非空
6. （数据截断检查留扩展）

用法:
  python run_ut.py --ts ts.json --select-dir etl/ --ddl-dir ddl/ --db-config db-sources.json

退出码: 0=全部通过, 1=有失败
"""

import sys
import json
import re
import argparse
from pathlib import Path
from datetime import datetime

# 同目录导入 dws_db
sys.path.insert(0, str(Path(__file__).parent))
from dws_db import create_executor, ExecuteResult, load_test_params


# ============================================================
# 参数替换：执行前把 ${PARAM} 替换为实际值（模拟术加平台运行时注入）
# ============================================================

# 动态表达式注册表：当天日期类参数在 UT 时按规则算出值
DYNAMIC_EXPRS = {
    "today_ymdhms": lambda: datetime.now().strftime("%Y%m%d") + "000000",  # 批次号
    "today_ymd":    lambda: datetime.now().strftime("%Y%m%d"),             # 业务日期
}


def resolve_test_value(param_name: str, cfg: dict | None) -> str | None:
    """解析单个参数的测试值。

    cfg 取自 db-sources.json 的 test_params.{param_name}，两种形态：
      {"type": "dynamic", "expr": "today_ymdhms"}  → 按表达式算
      {"type": "static",  "value": "20260101"}      → 直接用值
    cfg 为 None → 返回 None（调用方 fail loud）
    """
    if not cfg:
        return None
    t = cfg.get("type", "static")
    if t == "dynamic":
        expr = cfg.get("expr", "")
        fn = DYNAMIC_EXPRS.get(expr)
        if not fn:
            raise ValueError(f"未知动态表达式: {expr}（参数 {param_name}）")
        return fn()
    # static
    return cfg.get("value", "")


def substitute_params(sql: str, param_values: dict) -> str:
    """${PARAM} → 实际值。SQL 里用了某参数但 param_values 没值 → fail loud。"""
    def replacer(m):
        name = m.group(1)
        if name not in param_values:
            raise ValueError(f"SQL 用了参数 ${{{name}}}，但没配测试值")
        return str(param_values[name])
    return re.sub(r"\$\{([A-Z_][A-Z0-9_]*)\}", replacer, sql)


def resolve_all_params(ts: dict, config_path: str) -> dict:
    """从 ts.json 的 exec_params 声明 + db-sources.json 的 test_params 配置，
    算出全部参数的实际值。缺值则 fail loud（退出码 2）。"""
    declared = ts.get("meta", {}).get("schedule", {}).get("exec_params", {})
    if not declared:
        return {}
    test_cfg = load_test_params(config_path)
    values = {}
    missing = []
    for pname in declared:
        val = resolve_test_value(pname, test_cfg.get(pname))
        if val is None or val == "":
            missing.append(pname)
        else:
            values[pname] = val
    if missing:
        print(
            f"❌ 以下参数声明了但 db-sources.json 没配测试值: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(2)
    return values


def wrap_insert(select_sql: str, target_table: str, table_fields: list) -> str:
    """把 SELECT 包装成完整 INSERT（按平台固定规则）。

    平台规则：
    - INSERT INTO 目标表 (字段列表)
    - SELECT 内容不变

    table_fields: 该表的全部字段（从 tables 段取，已含审计字段）。
    INSERT 的字段列表 = 表的全部字段 = SELECT 输出的字段，一一对应。
    """
    # 字段列表：取表的全部字段名（业务 + 审计，已在 tables 段里）
    if table_fields and isinstance(table_fields[0], dict):
        field_names = [f.get("target_field", "") for f in table_fields]
    elif table_fields and isinstance(table_fields[0], str):
        field_names = list(table_fields)
    else:
        field_names = []
    columns = ",\n    ".join(field_names)

    return f"""INSERT INTO {target_table} (
    {columns}
)
{select_sql.strip().rstrip(';')};
"""


def read_select(select_dir: Path, rule_code: str) -> str:
    """读 coder 产的 SELECT 文件"""
    # 文件名约定：{rule_code}.sql
    path = select_dir / f"{rule_code}.sql"
    if not path.exists():
        # 尝试其他命名
        candidates = list(select_dir.glob(f"*{rule_code}*.sql"))
        if candidates:
            path = candidates[0]
        else:
            return ""
    return path.read_text(encoding="utf-8")


def run_ut_check(executor, target_table: str, business_key: list, audit_fields: dict) -> list[dict]:
    """跑 UT 检查，返回检查结果列表"""

    results = []

    # 检查1: 行数
    r = executor.execute(f"SELECT COUNT(*) AS cnt FROM {target_table}")
    if r.success and r.rows:
        count = r.rows[0]["cnt"]
        results.append({
            "check": "行数合理",
            "status": "PASS" if count > 0 else "WARN",
            "detail": f"{count} 行" + ("（为空，确认源表是否有数据）" if count == 0 else ""),
        })
    else:
        results.append({
            "check": "行数合理",
            "status": "FAIL",
            "detail": f"查询失败: {r.error}",
        })

    # 检查2: 业务主键唯一
    if business_key:
        key_cols = ", ".join(business_key)
        sql = f"SELECT {key_cols}, COUNT(*) AS cnt FROM {target_table} GROUP BY {key_cols} HAVING COUNT(*) > 1"
        r = executor.execute(sql)
        if r.success:
            dup_count = len(r.rows)
            results.append({
                "check": "业务主键唯一",
                "status": "PASS" if dup_count == 0 else "FAIL",
                "detail": f"{'无重复' if dup_count == 0 else f'{dup_count} 个重复键'}（键: {key_cols}）",
            })
        else:
            results.append({
                "check": "业务主键唯一",
                "status": "FAIL",
                "detail": f"查询失败: {r.error}",
            })

    # 检查3: 审计字段非空
    for aname in audit_fields.keys():
        sql = f"SELECT COUNT(*) AS cnt FROM {target_table} WHERE {aname} IS NULL"
        r = executor.execute(sql)
        if r.success and r.rows:
            null_count = r.rows[0]["cnt"]
            results.append({
                "check": f"审计字段非空({aname})",
                "status": "PASS" if null_count == 0 else "FAIL",
                "detail": f"{null_count} 行为空" if null_count > 0 else "无空值",
            })

    return results


def main():
    parser = argparse.ArgumentParser(
        description="UT 执行器: DDL + INSERT(包装) + UT检查 + 报告"
    )
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--select-dir", required=True, help="coder 产的 SELECT 文件目录")
    parser.add_argument("--ddl-dir", required=True, help="DDL 文件目录")
    parser.add_argument("--db-config", default="", help="db-sources.json 路径")
    parser.add_argument("--source", default="", help="数据源名（多schema多账号）")
    parser.add_argument("--skip-ddl", action="store_true", help="跳过DDL执行（表已存在）")
    parser.add_argument("--report", default="", help="UT 报告输出路径（ut_report.md）")
    args = parser.parse_args()

    # 读 ts.json
    ts = json.loads(Path(args.ts).read_text(encoding="utf-8"))
    rules = ts.get("rules", {})
    design = ts.get("design", {})
    audit_fields = design.get("audit_fields", {})
    business_key = design.get("business_key", [])
    data_flow = ts.get("data_flow", {})

    # 连库——按 schema 自动匹配数据源
    try:
        # 从 ts.json 读目标 schema，按 schema_mapping 自动选数据源
        target_schema = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", "")
        source = args.source
        if not source and target_schema:
            import os
            config_path = args.db_config or os.environ.get(
                "DB_CONFIG",
                str(Path.home() / ".config" / "opencode" / "db-sources.json"),
            )
            from dws_db import resolve_source_by_schema
            source = resolve_source_by_schema(config_path, target_schema)
        executor = create_executor(args.db_config, source)
    except Exception as e:
        print(f"错误: 连库失败: {e}", file=sys.stderr)
        sys.exit(2)

    # 加载测试参数（模拟术加平台运行时参数注入；缺值即中止）
    config_path = args.db_config or os.environ.get(
        "DB_CONFIG", str(Path.home() / ".config" / "opencode" / "db-sources.json")
    )
    param_values = resolve_all_params(ts, config_path)

    print(f"数据源: {executor.get_current_source()}（schema: {target_schema}）")
    if param_values:
        print(f"参数替换: {param_values}")
    print(f"规则数: {len(rules)}")
    print()

    # 按 schedule_groups 顺序执行
    schedule_groups = data_flow.get("schedule_groups", [])
    if not schedule_groups:
        # 没有 schedule_groups，按 exec_sequence 排
        schedule_groups = [{"sequence": r.get("exec_sequence", 1), "rules": [code]} for code, r in rules.items()]

    all_results = []
    prev_failed = False

    for group in schedule_groups:
        group_rules = group.get("rules", [])
        for rule_code in group_rules:
            rule = rules.get(rule_code)
            if not rule:
                continue

            target = rule.get("target_table", "")
            # 确保 target 带 schema（没有的话从 meta 补全）
            if target and "." not in target:
                f_schema = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", "")
                if f_schema:
                    target = f"{f_schema}.{target}"
            # 提取纯表名（DDL 文件查找用）
            _, table_name = (target.split(".", 1) + [""])[:2] if "." in target else ("", target)
            is_view = rule.get("is_view_step", False)
            rule_result = {"rule": rule_code, "target": target, "checks": []}

            print(f"--- {rule_code}: {target} ---")

            # 级联跳过
            if prev_failed:
                rule_result["status"] = "SKIP"
                rule_result["detail"] = "前序规则失败，级联跳过"
                print(f"  ⏭️ 级联跳过（前序失败）")
                all_results.append(rule_result)
                continue

            # 视图规则：只执行 DDL
            if is_view:
                ddl_dir = Path(args.ddl_dir)
                _, table = (target.split(".", 1) + [""])[:2] if "." in target else ("", target)
                view_ddls = list(ddl_dir.glob(f"*{table}*.sql"))
                if view_ddls:
                    ddl_sql = view_ddls[0].read_text(encoding="utf-8")
                    ddl_sql = substitute_params(ddl_sql, param_values)
                    r = executor.execute(ddl_sql)
                    rule_result["status"] = "PASS" if r.success else "FAIL"
                    rule_result["detail"] = r.summary()
                    print(f"  {'✅' if r.success else '❌'} {r.summary()}")
                else:
                    rule_result["status"] = "SKIP"
                    rule_result["detail"] = "视图DDL文件未找到"
                all_results.append(rule_result)
                continue

            # 表规则：DDL → INSERT → UT
            # 步骤1: DDL
            if not args.skip_ddl:
                ddl_dir = Path(args.ddl_dir)
                _, table = (target.split(".", 1) + [""])[:2] if "." in target else ("", target)
                table_ddls = list(ddl_dir.glob(f"create_table*{table}*.sql"))
                if table_ddls:
                    ddl_sql = table_ddls[0].read_text(encoding="utf-8")
                    ddl_sql = substitute_params(ddl_sql, param_values)
                    r = executor.execute(ddl_sql)
                    if not r.success:
                        rule_result["status"] = "FAIL"
                        rule_result["detail"] = f"DDL失败: {r.error[:100]}"
                        rule_result["error_type"] = "DDL"
                        print(f"  ❌ DDL失败: {r.error[:100]}")
                        all_results.append(rule_result)
                        prev_failed = True
                        continue
                    print(f"  ✅ DDL: {r.summary()}")
                else:
                    print(f"  ⚠️ DDL文件未找到，跳过建表")

            # 步骤2: 包装 + 执行 INSERT
            select_sql = read_select(Path(args.select_dir), rule_code)
            if not select_sql:
                rule_result["status"] = "SKIP"
                rule_result["detail"] = "SELECT文件未找到"
                print(f"  ⏭️ SELECT文件未找到")
                all_results.append(rule_result)
                continue

            # INSERT 字段列表从 tables 段取该表全部字段（含审计）
            target_short = target.rsplit(".", 1)[-1] if "." in target else target
            tbl_fields = ts.get("tables", {}).get(target_short, {}).get("fields", [])
            # 旧格式兼容：tables 段没有时 fallback 到 rule.fields
            if not tbl_fields:
                tbl_fields = rule.get("fields", [])
            insert_sql = wrap_insert(select_sql, target, tbl_fields)
            insert_sql = substitute_params(insert_sql, param_values)
            r = executor.execute(insert_sql)

            if not r.success:
                # 分类错误
                error_msg = r.error[:200] if r.error else "未知错误"
                error_type = "SQL" if any(k in error_msg.upper() for k in ["COLUMN", "TYPE", "SYNTAX", "DOES NOT EXIST"]) else "ENV"
                rule_result["status"] = "FAIL"
                rule_result["detail"] = f"INSERT失败: {error_msg}"
                rule_result["error_type"] = error_type
                print(f"  ❌ INSERT失败({error_type}): {error_msg}")
                all_results.append(rule_result)
                prev_failed = True
                continue

            print(f"  ✅ INSERT: {r.summary()}")

            # 步骤3: UT 检查
            ut_checks = run_ut_check(executor, target, business_key, audit_fields)
            rule_result["checks"] = ut_checks

            # 汇总 UT
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
    report_lines.append(f"> 时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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

    # UT 检查明细（有 checks 的规则）
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

    # 问题清单
    if failed:
        report_lines.append("## ⚠️ 问题清单")
        report_lines.append("")
        for r in all_results:
            if r["status"] == "FAIL":
                report_lines.append(f"- ❌ **{r['rule']}**（{r['target']}）: {r['detail']}")

    report_text = "\n".join(report_lines)

    # 写 ut_report.md（文件名带资产名）
    report_path = args.report
    if not report_path:
        # 从 ts.json 取资产名
        f_table_name = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("table", "ts")
        report_path = str(Path(args.ts).parent / f"{f_table_name}_ut_report.md")
    Path(report_path).write_text(report_text, encoding="utf-8")

    print("=" * 50)
    print(f"UT 汇总: ✅{passed} 通过  ❌{failed} 失败  ⏭️{skipped} 跳过")
    print(f"UT 报告: {report_path}")
    print("=" * 50)

    if failed:
        print("\n⚠️ 问题清单:")
        for r in all_results:
            if r["status"] == "FAIL":
                print(f"  ❌ {r['rule']}({r['target']}): {r['detail']}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
