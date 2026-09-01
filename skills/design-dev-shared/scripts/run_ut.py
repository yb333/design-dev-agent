#!/usr/bin/env python3
"""
UT 链路函数库：被 ut_precheck.py / ut_execute.py import，自身不可单独执行。

new-pipe 的 UT 执行走两阶段（ut_precheck 秒级预检 + ut_execute 分钟级执行），
两者共用本库的函数。本库**不含**单执行器入口——历史 main() 单执行器已被
6a/6b 两阶段流程取代（如需独立排查，直接调 ut_precheck/ut_execute）。

提供的函数：
- 参数替换：resolve_test_value / substitute_params / resolve_all_params
- SELECT 包装：wrap_insert / wrap_write / read_select
- 采样：resolve_sample_blocks / inject_tablesample
- UT 检查：run_ut_check（主键唯一 / 审计非空 / 行数，失败抓样例供归因）
"""

import sys
import re
from pathlib import Path
from datetime import datetime, timedelta

# 行缓冲 stdout——子进程模式下主控能实时看到 DDL/SELECT/INSERT 各节点进度
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

# 依赖全在 shared 同目录（dws_db/sql_parse），无需跨目录引导
from dws_db import load_test_params
from sql_parse import extract_select_aliases, read_sql


# ============================================================
# 参数替换：执行前把 ${PARAM} 替换为实际值（模拟术加平台运行时注入）
# ============================================================

# 动态表达式注册表：当天日期类参数在 UT 时按规则算出值
DYNAMIC_EXPRS = {
    "today_ymdhms":  lambda: datetime.now().strftime("%Y%m%d") + "000000",            # 批次号
    "today_ymd":     lambda: datetime.now().strftime("%Y%m%d"),                       # 业务日期
    "yesterday_ymd": lambda: (datetime.now() - timedelta(days=1)).strftime("%Y%m%d"),  # 增量起点（T+1）
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
    """算出全部参数的实际值（UT 执行前替换 ${PARAM}）。

    三层兜底链（都不缺值，不 exit）：
      1. test_params 配置（db-sources.json，精确/动态，最高优先级）
      2. ts.exec_params.{name}.default_value（标准参数内置 / designer 给的业务参数默认值）
      3. 类型兜底（按 value_type 推：date→今天，number→0，string→空）
    第 2/3 层 warn 提示（UT 验证 SQL 结构不受影响），不阻断。
    """
    declared = ts.get("meta", {}).get("schedule", {}).get("exec_params", {})
    if not declared:
        return {}
    test_cfg = load_test_params(config_path)
    values = {}
    defaulted = []
    for pname, pdecl in declared.items():
        # 1. test_params 配置（最高优先级）
        val = resolve_test_value(pname, test_cfg.get(pname))
        if val is None or val == "":
            # 2. ts.default_value（标准参数内置 / designer 给）
            dv = (pdecl or {}).get("default_value")
            if dv is not None and dv != "" and dv != {}:
                val = _resolve_default_value(pname, dv)
                defaulted.append(pname)
            else:
                # 3. 类型兜底（最后退路）
                val = _type_fallback(pdecl)
                defaulted.append(pname)
        values[pname] = val
    if defaulted:
        print(
            f"⚠️ 以下参数未在 test_params 配置，用 default_value/类型兜底: {', '.join(defaulted)}",
            file=sys.stderr,
        )
        print(
            "   UT 验证 SQL 结构不受影响；如需精确数据请在 test_params 段配真实值",
            file=sys.stderr,
        )
    return values


def _resolve_default_value(pname: str, dv) -> str:
    """解析 ts.default_value：支持裸串（=static）或 {type, expr/value}（=static/dynamic）。"""
    if isinstance(dv, dict):
        return resolve_test_value(pname, dv) or ""
    return str(dv)


def _type_fallback(pdecl: dict) -> str:
    """参数既无 test_params 也无 default_value 时的最后兜底（按 value_type 推）。"""
    vt = (pdecl or {}).get("value_type", "string")
    if vt == "date":
        return datetime.now().strftime("%Y%m%d")
    if vt == "datetime":
        return datetime.now().strftime("%Y%m%d%H%M%S")
    if vt == "number":
        return "0"
    return ""


def resolve_sample_blocks(config_path: str, cli_value: int = None) -> int:
    """解析采样块数：CLI 参数（含显式 0）> 配置文件默认值 > 0。

    - CLI 传了 --sample-blocks N → 用 N（含 0=强制不采样）
    - CLI 没传（None）→ 从 db-sources.json 的 security.sample_blocks 读默认值
    - 都没有 → 0（不采样）

    default=None 区分"没传"（读 config）vs"传 0"（强制不采样）——
    避免 CLI 传 0 被当成"没传"反而读了 config 的非 0 值。
    """
    if cli_value is not None:
        return cli_value  # 显式传（含 0=强制不采样）
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


def _resolve_insert_columns(select_sql: str, table_fields: list) -> list[str]:
    """解析 INSERT 字段列表的顺序——按 SELECT 输出列的出现顺序（模拟平台行为）。

    平台按 SELECT 输出列的顺序拼 INSERT 字段列表（有映射能力）。
    本函数用 check_sql.extract_select_aliases 从 SELECT 提取 AS 别名（按出现顺序）。

    回退策略：SELECT 解析不出字段（无 AS 别名等异常情况）→ 用 table_fields 顺序兜底。
    coder 已被规范要求"所有字段用 AS 显式命名"，正常情况都能解析。

    Args:
        select_sql: coder 产的 SELECT。
        table_fields: 表的全部字段（dict 列表或字符串列表），回退用。

    返回: 字段名列表（按 SELECT 顺序），空列表表示两边都拿不到。
    """
    try:
        aliases = extract_select_aliases(select_sql)
        if aliases:
            # 终检：INSERT 列重复 = 解析异常（CTE 边界错位）或 SELECT 真重复输出——
            # 两者拼出的 INSERT 都是非法 SQL，明确报错不静默拼（fail-visible）
            dup = [a for a in set(aliases) if aliases.count(a) > 1]
            if dup:
                raise ValueError(
                    f"INSERT 字段清单解析出重复列 {sorted(dup)}——疑似 CTE 边界识别失败"
                    f"（检查 SELECT 里的字符串字面量/括号配对）或 SELECT 输出了重复别名")
            return aliases
    except ValueError:
        raise
    except Exception:
        pass
    # 回退：table_fields 顺序
    if table_fields and isinstance(table_fields[0], dict):
        return [f.get("target_field", "") for f in table_fields]
    if table_fields and isinstance(table_fields[0], str):
        return list(table_fields)
    return []


def wrap_insert(select_sql: str, target_table: str, table_fields: list) -> str:
    """把 SELECT 包装成 INSERT 语句（模拟平台构建）。

    平台规则：
    - INSERT INTO 目标表 (字段列表)
    - SELECT 内容不变
    - ★ 字段列表按 SELECT 输出列的顺序拼（平台有映射能力，解析 SELECT 别名顺序）

    table_fields: 该表的全部字段（从 tables 段取，已含审计字段）。
    作为解析失败时的回退（兜底用 table_fields 顺序）。
    """
    field_names = _resolve_insert_columns(select_sql, table_fields)
    columns = ",\n    ".join(field_names)

    return f"""INSERT INTO {target_table} (
    {columns}
)
{select_sql.strip().rstrip(';')};
"""


def wrap_write(select_sql: str, target_table: str, table_fields: list,
               load_mode: str = "truncate_table", write_condition: str = "") -> str:
    """按 load_mode + write_condition 把 SELECT 包装成平台写入语句（模拟平台构建）。

    平台规则（用户确认）：目标表别名 T，源（SELECT 结果）别名 T1。
    - truncate_table / no_delete → INSERT（wrap_insert）
    - truncate_partition → INSERT（分区清空由 ut_execute 预处理做，这里仍 INSERT）
    - delete → INSERT（删除由 ut_execute 预处理做，这里仍 INSERT）
    - merge_into / update → MERGE INTO ... USING (SELECT) T1 ON ... WHEN MATCHED/NOT MATCHED

    Args:
        select_sql: coder 产的 SELECT。
        target_table: 目标表全名（schema.table）。
        table_fields: 目标表全部字段（dict列表或字符串列表）。
        load_mode: 写入方式。
        write_condition: 写入条件（merge 的 ON、partition 的分区名、delete 的 WHERE）。
    """
    # 非 merge/update 的都走 INSERT（partition/delete 的清空动作在 ut_execute 预处理）
    if load_mode not in ("merge_into", "update"):
        return wrap_insert(select_sql, target_table, table_fields)

    # MERGE / UPDATE：拼 MERGE INTO 语句
    # ★ 字段列表按 SELECT 输出列顺序（和平台一致），解析失败回退 table_fields
    field_names = _resolve_insert_columns(select_sql, table_fields)
    if not field_names:
        # 没有字段清单，回退 INSERT（无法拼 MERGE 的字段映射）
        return wrap_insert(select_sql, target_table, table_fields)

    columns = ", ".join(field_names)
    # UPDATE SET：源字段赋值（T1.col 对应每个目标字段，审计字段不更新由业务定，这里全量 UPDATE）
    update_set = ",\n        ".join(f"T.{c} = T1.{c}" for c in field_names)
    on_cond = write_condition.strip() if write_condition.strip() else "1=1"

    return f"""MERGE INTO {target_table} T
USING (
{select_sql.strip().rstrip(';')}
) T1
ON {on_cond}
WHEN MATCHED THEN UPDATE SET
        {update_set}
WHEN NOT MATCHED THEN INSERT (
        {columns}
    ) VALUES (
        {", ".join(f"T1.{c}" for c in field_names)}
    );
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


def dq_filename(idx: int, check_type: str) -> str:
    """DQ 检查 SQL 文件确定名：dq_{NN}_{清洗check_type}.sql。

    唯一键是 dq_rules 数组序号（check_type 是"检查类型"不是规则身份，重复是
    常态——两条空值检查同名文件会互相覆盖静默丢检查）；check_type 清洗后保留
    在文件名里（闸口② 人看文件友好）：去首尾空格，非字母/数字/中文/下划线换 `_`。
    单点在本函数：UT 侧（run_dq_checks）与 coder 侧（slice_ts --dq 附 _file）
    同源派生，两侧不自拼。序号两侧按同一 ts.json 的 dq_rules 顺序（闸口①后冻结）。
    """
    safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (check_type or "").strip())
    return f"dq_{idx:02d}_{safe}.sql"


def run_dq_checks(executor, dq_dir, dq_rules: list, param_values: dict,
                  sample_limit: int = 5) -> list[dict]:
    """执行 DQ 检查 SQL（对 UT 已灌数的目标表）——DQ 是上生产的制品，交付前必须执行验证。

    契约：DQ SELECT = **违规行探测器**——0 行通过，非 0 行告警；阈值/比例逻辑全收在
    SQL 的 WHERE/HAVING 里，这里只判行数。文件名 = dq_filename（dq_{NN}_{清洗
    check_type}.sql，序号消重名、清洗消非法字符），缺文件 = 发现项（coder 未按
    切片 _file 契约产出）。

    行数用 COUNT 包裹查（不拉全量结果集），告警才追加 LIMIT 采样抓违规行样例。
    返回 [{rule_name, check_type, file, status, detail, rows, samples}]，status：
    PASS（0 行）/ ALERT（非 0 行）/ FAIL（执行报错/参数缺测试值）/ MISSING（文件缺失）。
    分流：FAIL/MISSING 回 coder（SQL 类）；ALERT 归闸口② 人判（SQL 写错 / 阈值口径
    不合理回 designer / 数据真脏人定）。
    """
    results = []
    for i, rule in enumerate(dq_rules or [], 1):
        check_type = (rule.get("check_type") or "").strip()
        rule_name = rule.get("rule_name") or check_type
        fname = dq_filename(i, check_type)
        entry = {"rule_name": rule_name, "check_type": check_type, "file": fname,
                 "status": "PASS", "detail": "", "rows": 0, "samples": []}
        fpath = Path(dq_dir) / fname
        if not check_type or not fpath.exists():
            entry["status"] = "MISSING"
            entry["detail"] = f"检查 SQL 文件缺失（预期 {fname}）"
            results.append(entry)
            continue
        sql = read_sql(str(fpath)).strip().rstrip(";")
        try:
            sql = substitute_params(sql, param_values)
        except ValueError as ve:
            entry["status"] = "FAIL"
            entry["detail"] = str(ve)
            results.append(entry)
            continue
        count_sql = f"SELECT COUNT(*) AS cnt FROM ({sql}) _dq_check"
        r = executor.execute(count_sql)
        if not r.success:
            entry["status"] = "FAIL"
            entry["detail"] = f"执行失败: {(r.error or '')[:200]}"
            results.append(entry)
            continue
        cnt = ((r.rows or [{}])[0].get("cnt", 0)) or 0
        entry["rows"] = cnt
        if cnt:
            entry["status"] = "ALERT"
            entry["detail"] = f"{cnt} 行违规（0 行=通过，非 0 行=告警）"
            sample_sql = f"SELECT * FROM ({sql}) _dq_check LIMIT {sample_limit}"
            rs = executor.execute(sample_sql)
            entry["samples"] = [" | ".join(f"{k}={v}" for k, v in row.items())
                                for row in (rs.rows or [])[:sample_limit]]
        else:
            entry["detail"] = "0 行，通过"
        results.append(entry)
    return results


def inject_tablesample(select_sql: str, sample_blocks: int = 0) -> str:
    """给 SELECT 注入 TABLESAMPLE SYSTEM（只切 FROM 主表 + INNER/逗号/CROSS JOIN 表）。

    切片范围（避免切片太狠导致空表 UT 假通过 / 外连接从表关联不上变 NULL）：
    - FROM 主表：切
    - INNER JOIN / 隐式逗号 JOIN / CROSS JOIN 表：切（必要表，两边都要匹配才有结果）
    - LEFT/RIGHT/FULL JOIN 从表：**不切**（外连接侧保留全量，避免切片后关联不上字段变 NULL）
    - 子查询里的表 / CTE 定义里的表：不切（只在主查询层注入）

    设计原则（不可违背）：
    - 注入失败时必须返回原 SQL，绝不破坏 coder 的 SQL 可执行性。
    - 用 sqlglot 定位物理表位置 + 判断 JOIN 类型（只读 AST 的 side/kind），用字符串插入注入（从后往前，避免位置偏移）。

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

        # 收集要切 TABLESAMPLE 的物理表（按 JOIN 类型筛选）
        # - FROM 主表：切
        # - INNER/隐式逗号/CROSS JOIN 表：切（side 为空 = 必要表）
        # - LEFT/RIGHT/FULL JOIN 从表：不切（外连接侧保留全量，避免切片后关联不上变 NULL）
        # 只看主查询的直接表（args["from_"]/args["joins"]），不深入子查询
        import re

        all_tables = []
        # ① FROM 主表（from_.this 是直接表，不深入子查询）
        from_node = select_node.args.get("from_") or select_node.args.get("from")
        if from_node:
            ft = from_node.this
            if isinstance(ft, exp.Table) and ft.db:
                all_tables.append((ft.db, ft.name, ft.alias or ""))
        # ② 主查询的直接 JOIN（不深入子查询里的 JOIN）
        for j in (select_node.args.get("joins") or []):
            side = j.args.get("side")
            if side in ("LEFT", "RIGHT", "FULL"):
                continue  # 外连接从表不切
            jt = j.this
            if isinstance(jt, exp.Table) and jt.db:
                all_tables.append((jt.db, jt.name, jt.alias or ""))

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
    """跑 UT 检查，返回检查结果列表。

    每个 entry 含 sql 字段（执行的 SQL），供 ut_execute 落地 debug 用。
    """

    results = []

    # 检查1: 行数
    sql = f"SELECT COUNT(*) AS cnt FROM {target_table}"
    r = executor.execute(sql)
    if r.success and r.rows:
        count = r.rows[0]["cnt"]
        results.append({
            "check": "行数合理",
            "status": "PASS" if count > 0 else "WARN",
            "detail": f"{count} 行" + ("（为空，确认源表是否有数据）" if count == 0 else ""),
            "sql": sql,
        })
    else:
        results.append({
            "check": "行数合理",
            "status": "FAIL",
            "detail": f"查询失败: {r.error}",
            "sql": sql,
        })

    # 检查2: 业务主键唯一（重复时抓样例供 designer 归因，不抓一堆）
    if business_key:
        key_cols = ", ".join(business_key)
        sql = f"SELECT {key_cols}, COUNT(*) AS cnt FROM {target_table} GROUP BY {key_cols} HAVING COUNT(*) > 1 LIMIT 5"
        r = executor.execute(sql)
        if r.success:
            dup_count = len(r.rows)
            entry = {
                "check": "业务主键唯一",
                "status": "PASS" if dup_count == 0 else "FAIL",
                "detail": f"{'无重复' if dup_count == 0 else f'{dup_count} 个重复键（最多展示5个）'}（键: {key_cols}）",
                "sql": sql,
            }
            if dup_count > 0:
                entry["samples"] = [dict(row) for row in r.rows]
            results.append(entry)
        else:
            results.append({
                "check": "业务主键唯一",
                "status": "FAIL",
                "detail": f"查询失败: {r.error}",
                "sql": sql,
            })

    # 检查3: 审计字段非空（有空值时抓样例）
    for aname in audit_fields.keys():
        sql = f"SELECT COUNT(*) AS cnt FROM {target_table} WHERE {aname} IS NULL"
        r = executor.execute(sql)
        if r.success and r.rows:
            null_count = r.rows[0]["cnt"]
            entry = {
                "check": f"审计字段非空({aname})",
                "status": "PASS" if null_count == 0 else "FAIL",
                "detail": f"{null_count} 行为空" if null_count > 0 else "无空值",
                "sql": sql,
            }
            if null_count > 0:
                # 抓3行空值样例，供 designer 判断是关联 LEFT JOIN 配错还是源数据问题
                samp_sql = f"SELECT * FROM {target_table} WHERE {aname} IS NULL LIMIT 3"
                rs = executor.execute(samp_sql)
                if rs.success and rs.rows:
                    entry["samples"] = [dict(row) for row in rs.rows]
            results.append(entry)

    return results
