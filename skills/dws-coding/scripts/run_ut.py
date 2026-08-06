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

# 行缓冲 stdout——子进程模式下主控能实时看到 DDL/SELECT/INSERT 各节点进度
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

# dws_db 在 design-dev-shared 公共库（与本 skill 平级）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
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


def resolve_sample_blocks(config_path: str, cli_value: int = 0) -> int:
    """解析采样块数：CLI 参数 > 配置文件默认值 > 0。

    - CLI 传了 --sample-blocks N（N>0）→ 用 N
    - CLI 没传（0）→ 从 db-sources.json 的 security.sample_blocks 读默认值
    - 都没有 → 0（不采样）

    这样 AI 不用传参数，配置里写了 sample_blocks 就自动采样。
    开发环境配 sample_blocks=10，UAT/生产配 0。
    """
    if cli_value > 0:
        return cli_value
    try:
        import json
        from pathlib import Path
        p = Path(config_path)
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            return int(raw.get("security", {}).get("sample_blocks", 0))
    except Exception:
        pass
    return 0


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
    """读 coder 产的 SELECT 文件。

    文件名约定：{rule_code}.sql 或 {rule_code}_描述_loadmode.sql
    确定文件名优先，不以 glob 模糊匹配。
    """
    # 尝试精确文件名
    path = select_dir / f"{rule_code}.sql"
    if path.exists():
        return path.read_text(encoding="utf-8")
    # coder 可能产出了 {rule_code}_描述.sql 格式，用前缀确定匹配（不用两侧通配）
    candidates = sorted(select_dir.glob(f"{rule_code}_*.sql"))
    if candidates:
        return candidates[0].read_text(encoding="utf-8")
    return ""


def inject_tablesample(select_sql: str, sample_blocks: int = 0) -> str:
    """给 SELECT 的所有物理表（FROM + JOIN）注入 TABLESAMPLE SYSTEM。

    多主表场景（两个事实表 INNER JOIN）每张都要采样，否则没采样的那张
    还是全量扫，照样慢。CTE/子查询里的表不注入。

    设计原则（不可违背）：
    - 注入失败时必须返回原 SQL，绝不破坏 coder 的 SQL 可执行性。
    - 用 sqlglot 定位物理表位置（只读 AST），用字符串插入注入（从后往前，避免位置偏移）。

    Args:
        select_sql: coder 产的 SELECT SQL。
        sample_blocks: 采样块数百分比（如 10 = SYSTEM(10)）。0=不注入。

    Returns:
        注入后的 SQL；sample_blocks=0 或注入失败时返回原 SQL。
    """
    if sample_blocks <= 0:
        return select_sql

    try:
        import sqlglot
        from sqlglot import exp
    except ImportError:
        return select_sql

    try:
        trees = sqlglot.parse(select_sql, dialect="postgres")
        tree = None
        for t in trees:
            if t is not None:
                tree = t
                break
        if tree is None:
            return select_sql

        # 找最外层 SELECT（跳过 CTE 定义体内的 SELECT）
        # 如果有 WITH，主查询的 SELECT 在 CTE 定义之后
        main_select_start = 0
        if select_sql.strip().upper().startswith("WITH"):
            cte_end = _find_cte_section_end(select_sql)
            if cte_end is not None:
                main_select_start = cte_end

        select_node = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
        if select_node is None:
            return select_sql

        # 收集主查询里所有物理表（FROM + JOIN 的，有 schema 的）
        # 用 sqlglot AST 找 Table 节点（可靠区分表引用 vs 列引用）
        import re

        # 从 sqlglot AST 拿到主查询里的所有 Table 节点
        # Table 节点有 .db（schema）和 .name（表名）和 .alias
        all_tables = []
        for tbl in select_node.find_all(exp.Table):
            schema = tbl.db or ""
            if not schema:
                continue  # 无 schema，可能是 CTE 引用，跳过
            all_tables.append((schema, tbl.name, tbl.alias or ""))

        if not all_tables:
            return select_sql

        # 对每张表，在原 SQL 中找其引用位置并注入
        insertions = []
        for schema, table, alias in all_tables:
            # 在原 SQL 中匹配 schema.table [AS] alias
            if alias:
                pattern_t = re.compile(
                    rf'\b{re.escape(schema)}\.{re.escape(table)}\s+(?:AS\s+)?{re.escape(alias)}\b',
                    re.IGNORECASE,
                )
            else:
                pattern_t = re.compile(
                    rf'\b{re.escape(schema)}\.{re.escape(table)}\b',
                    re.IGNORECASE,
                )

            match = pattern_t.search(select_sql)
            if not match:
                continue

            pos = match.end()

            # 排除已经在 TABLESAMPLE 里的（避免重复注入）
            after = select_sql[pos:pos + 30]
            if "TABLESAMPLE" in after:
                continue

            # 排除 CTE 定义体里的表（位置在 CTE 段内的跳过）
            if select_sql.strip().upper().startswith("WITH"):
                cte_end = _find_cte_section_end(select_sql)
                if cte_end is not None and pos < cte_end:
                    continue  # 在 CTE 定义内，跳过

            insertions.append(pos)


        if not insertions:
            return select_sql

        # 从后往前插入（避免位置偏移）
        sample_clause = f" TABLESAMPLE SYSTEM ({sample_blocks})"
        result = select_sql
        for pos in sorted(insertions, reverse=True):
            result = result[:pos] + sample_clause + result[pos:]

        # 验证注入后 SQL 仍可解析（不破坏结构）
        try:
            sqlglot.parse_one(result, dialect="postgres")
        except Exception:
            return select_sql  # 注入后解析失败，回退原 SQL

        return result

    except Exception:
        return select_sql


def _find_cte_section_end(sql: str) -> int | None:
    """找 WITH CTE 定义段的结束位置（最后一个 CTE 体闭合括号后）。

    用于判断主表位置是否在 CTE 定义之后。
    返回字符位置；找不到返回 None。
    """
    # 简化：找 WITH 后的括号配对，最后一个 ) AS 之前的 ) 就是 CTE 结束
    # 更简单：找 "WITH ... ) SELECT" 模式里的 ) 位置
    import re
    # 找 CTE 定义结束（最后的 ")" 在主 SELECT 之前）
    # 主 SELECT 的标志：) SELECT 或 ) 主查询
    m = re.search(r'\)\s*(?:SELECT|INSERT)', sql, re.IGNORECASE)
    if m:
        return m.start()  # ) 的位置
    return None


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
    parser.add_argument("--ddl-dir", required=True, help="DDL 文件目录（ddl/）")
    parser.add_argument("--rollback-dir", default="", help="回退脚本目录（ddl_rollback/，默认 ddl-dir 同级）")
    parser.add_argument("--db-config", default="", help="db-sources.json 路径")
    parser.add_argument("--source", default="", help="数据源名（多schema多账号）")
    parser.add_argument("--skip-ddl", action="store_true", help="跳过DDL执行（表已存在）")
    parser.add_argument("--report", default="", help="UT 报告输出路径（ut_report.md）")
    parser.add_argument("--sample-blocks", type=int, default=0, help="主表块采样百分比（如 10=SYSTEM(10)），0=不采样。开发环境加速用")
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
        # 两个 role：admin 跑 DDL（建表删表），etl 跑 SELECT/INSERT/UT检查（数据读写）
        ddl_executor = create_executor(args.db_config, source, role="admin")
        etl_executor = create_executor(args.db_config, source, role="etl")
    except Exception as e:
        print(f"错误: 连库失败: {e}", file=sys.stderr)
        sys.exit(2)

    # 加载测试参数（模拟术加平台运行时参数注入；缺值即中止）
    config_path = args.db_config or os.environ.get(
        "DB_CONFIG", str(Path.home() / ".config" / "opencode" / "db-sources.json")
    )
    param_values = resolve_all_params(ts, config_path)

    print(f"数据源: {ddl_executor.get_current_source()}（schema: {target_schema}）")
    print(f"账号: DDL→admin, SELECT/INSERT→etl")
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

            # 视图规则：回退 → 建 DDL
            if is_view:
                ddl_dir = Path(args.ddl_dir)
                rb_dir = Path(args.rollback_dir) if args.rollback_dir else ddl_dir.parent / "ddl_rollback"
                _, view_name = (target.split(".", 1) + [""])[:2] if "." in target else ("", target)

                # 先跑回退（DROP VIEW，确定文件名）—— admin 账号
                rb_file = rb_dir / f"rollback_create_view_{view_name}.sql"
                if rb_file.exists():
                    rb_sql = substitute_params(rb_file.read_text(encoding="utf-8"), param_values)
                    ddl_executor.execute(rb_sql)  # 回退失败不阻断

                # 再跑 DDL（CREATE VIEW，确定文件名）—— admin 账号
                view_file = ddl_dir / f"create_view_{view_name}.sql"
                if view_file.exists():
                    ddl_sql = substitute_params(view_file.read_text(encoding="utf-8"), param_values)
                    r = ddl_executor.execute(ddl_sql)
                    rule_result["status"] = "PASS" if r.success else "FAIL"
                    rule_result["detail"] = r.summary()
                    print(f"  {'✅' if r.success else '❌'} {r.summary()}")
                else:
                    rule_result["status"] = "SKIP"
                    rule_result["detail"] = f"视图DDL文件未找到: {view_file.name}"
                all_results.append(rule_result)
                continue

            # 表规则：回退 → DDL → INSERT → UT
            # 步骤0: 回退脚本（DROP TABLE，清理上次的残留 + 验证回退脚本）
            if not args.skip_ddl:
                ddl_dir = Path(args.ddl_dir)
                rb_dir = Path(args.rollback_dir) if args.rollback_dir else ddl_dir.parent / "ddl_rollback"
                _, table = (target.split(".", 1) + [""])[:2] if "." in target else ("", target)

                # 先跑回退（DROP TABLE，确定文件名）—— admin 账号
                rb_file = rb_dir / f"rollback_create_table_{table}.sql"
                if rb_file.exists():
                    rb_sql = substitute_params(rb_file.read_text(encoding="utf-8"), param_values)
                    r_rb = ddl_executor.execute(rb_sql)
                    if r_rb.success:
                        print(f"  🔄 回退: {rb_file.name}")
                    else:
                        print(f"  ⚠️ 回退失败(忽略): {r_rb.error[:80]}")

                # 步骤1: DDL（CREATE TABLE，确定文件名）—— admin 账号
                ddl_file = ddl_dir / f"create_table_{table}.sql"
                if ddl_file.exists():
                    ddl_sql = substitute_params(ddl_file.read_text(encoding="utf-8"), param_values)
                    r = ddl_executor.execute(ddl_sql)
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
                    print(f"  ⚠️ DDL文件未找到: {ddl_file.name}，跳过建表")

            # 步骤2: 读 SELECT + 参数替换
            select_sql = read_select(Path(args.select_dir), rule_code)
            if not select_sql:
                rule_result["status"] = "SKIP"
                rule_result["detail"] = "SELECT文件未找到"
                print(f"  ⏭️ SELECT文件未找到")
                all_results.append(rule_result)
                continue
            select_sql = substitute_params(select_sql, param_values)
            # 采样：CLI参数优先，不传则从 db-sources.json 的 security.sample_blocks 读默认
            sample_n = resolve_sample_blocks(config_path, args.sample_blocks)
            select_sql = inject_tablesample(select_sql, sample_n)

            # 步骤2.5: SELECT 预检（快速发现类型/字段问题，不写数据）—— etl 账号
            r_pre = etl_executor.execute(select_sql)
            if not r_pre.success:
                error_msg = r_pre.error[:200] if r_pre.error else "未知错误"
                error_type = "SQL" if any(k in error_msg.upper() for k in ["COLUMN", "TYPE", "SYNTAX", "DOES NOT EXIST"]) else "ENV"
                rule_result["status"] = "FAIL"
                rule_result["detail"] = f"SELECT预检失败({error_type}): {error_msg}"
                rule_result["error_type"] = error_type
                print(f"  ❌ SELECT预检失败({error_type}): {error_msg}")
                all_results.append(rule_result)
                prev_failed = True
                continue
            pre_cols = r_pre.columns or []
            pre_rows = len(r_pre.rows) if r_pre.rows else 0
            print(f"  ✅ SELECT预检: {pre_rows}行, {len(pre_cols)}列")

            # 步骤3: 按写入模式预处理（模拟术加平台行为）—— etl 账号
            load_mode = rule.get("load_mode", "truncate_table")
            if load_mode == "truncate_table":
                etl_executor.execute(f"TRUNCATE TABLE {target}")
                print(f"  🔄 TRUNCATE（load_mode=truncate_table）")
            elif load_mode == "delete" and rule.get("delete_condition"):
                del_sql = f"DELETE FROM {target} WHERE {rule['delete_condition']}"
                etl_executor.execute(del_sql)
                print(f"  🔄 DELETE（load_mode=delete）")
            # no_delete / merge_into 不预处理

            # 步骤4: INSERT 灌数据
            # INSERT 字段列表从 tables 段取该表全部字段（含审计）
            target_short = target.rsplit(".", 1)[-1] if "." in target else target
            tbl_fields = ts.get("tables", {}).get(target_short, {}).get("fields", [])
            if not tbl_fields:
                tbl_fields = rule.get("fields", [])
            insert_sql = wrap_insert(select_sql, target, tbl_fields)
            r = etl_executor.execute(insert_sql)

            if not r.success:
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

            # 步骤5: UT 检查 —— etl 账号
            ut_checks = run_ut_check(etl_executor, target, business_key, audit_fields)
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
