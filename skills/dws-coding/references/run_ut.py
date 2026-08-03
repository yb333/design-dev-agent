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
import argparse
from pathlib import Path
from datetime import datetime

# 同目录导入 dws_db
sys.path.insert(0, str(Path(__file__).parent))
from dws_db import create_executor, ExecuteResult


def wrap_insert(select_sql: str, target_table: str, fields: list, audit_fields: dict) -> str:
    """把 SELECT 包装成完整 INSERT（按平台固定规则）。

    平台规则：
    - INSERT INTO 目标表 (字段列表)
    - SELECT 内容不变
    - 审计字段已在 SELECT 里带上了（coder 产的 SELECT 含审计字段赋值）
    """
    # 字段列表（业务字段 + 审计字段）
    field_names = [f["target_field"] for f in fields]
    field_names.extend(audit_fields.keys())
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
    args = parser.parse_args()

    # 读 ts.json
    ts = json.loads(Path(args.ts).read_text(encoding="utf-8"))
    rules = ts.get("rules", {})
    design = ts.get("design", {})
    audit_fields = design.get("audit_fields", {})
    business_key = design.get("business_key", [])
    data_flow = ts.get("data_flow", {})

    # 连库
    try:
        executor = create_executor(args.db_config, args.source)
    except Exception as e:
        print(f"错误: 连库失败: {e}", file=sys.stderr)
        sys.exit(2)

    print(f"数据源: {executor.get_current_source()}")
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

            insert_sql = wrap_insert(select_sql, target, rule.get("fields", []), audit_fields)
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

    print("=" * 50)
    print(f"UT 汇总: ✅{passed} 通过  ❌{failed} 失败  ⏭️{skipped} 跳过")
    print("=" * 50)

    # 问题清单（给拍照用——只列失败的）
    if failed:
        print("\n⚠️ 问题清单:")
        for r in all_results:
            if r["status"] == "FAIL":
                print(f"  ❌ {r['rule']}({r['target']}): {r['detail']}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
