#!/usr/bin/env python3
"""
直取字段骨架生成器: 从 ts.json 规则切片生成 SELECT 填空骨架。

把 coder 从"写整个 SELECT"降级为"填空"。自动生成确定性的内容：
- 文件头注释（rule_name/design_intent/source_tables）
- CTE 骨架（join_safety 非 unique 的表 → 收敛到主表粒度）
- FROM/JOIN/WHERE 骨架（主表 + 维表 JOIN + del_flag 过滤 + 增量 filter）
- direct 字段（按 field_type 推断 COALESCE 默认值）
- assign 字段（审计字段固定 4 行）

只留 aggregate/计算字段为 TODO 占位，coder 填这些需要语义的部分。

生成原则（降级策略）：
- 拿不准坚决不生成，留 TODO（宁可漏让 coder 补，不要错让他 debug）
- source_fields 缺 alias → TODO
- field_type 无法识别 → 原样取值 + REVIEW 注释（不瞎加 COALESCE）
- join_safety.strategy 为空但非 unique → CTE 骨架 + 内部全 TODO

用法:
  python codegen_direct.py --ts ts.json --rule R0001
  python codegen_direct.py --ts ts.json --rule R0001 --output R0001_xxx.sql

退出码: 0=成功, 1=规则不存在, 2=文件错误
"""

import sys
import re
import argparse
from pathlib import Path

# 复用 slice_ts 的切片逻辑（同一个目录）
try:
    from slice_ts import slice_rule
except ImportError:
    # 允许从其他 cwd 调用时找到同目录模块
    _here = Path(__file__).resolve().parent
    if str(_here) not in sys.path:
        sys.path.insert(0, str(_here))
    from slice_ts import slice_rule


# ============================================================
# field_type → COALESCE 默认值推断
# ============================================================

# 数值类型 → 默认 0
_NUMERIC_TYPES = {
    "int", "integer", "bigint", "smallint", "tinyint",
    "decimal", "numeric", "number",
    "float", "double", "real", "double precision",
    "money",
}

# 字符串类型 → 默认 ''
_STRING_TYPES = {
    "varchar", "char", "text", "nvarchar", "nchar",
    "varchar2", "nvarchar2", "clob",
}

# 时间类型 → 不 COALESCE（时间无默认值语义）
_TIME_TYPES = {
    "date", "datetime", "timestamp", "time",
    "timestamp without time zone", "timestamp with time zone",
    "timestamp(0)", "timestamp(0) without time zone",
    "datetime2", "smalldatetime",
}


def _normalize_type(field_type: str) -> str:
    """归一化 field_type：去括号参数、去空格、转小写。

    'DECIMAL(18,2)' → 'decimal'
    'TIMESTAMP(0) WITHOUT TIME ZONE' → 'timestamp(0) without time zone'
    """
    if not field_type:
        return ""
    t = field_type.strip().lower()
    # 去掉类型参数：decimal(18,2) → decimal；varchar(100) → varchar
    # 但保留 timestamp(0) without time zone 这种（0 是精度，without time zone 是修饰）
    # 简化：只去 (数字[,数字]) 这种数值参数
    t = re.sub(r"\(\s*\d+\s*(,\s*\d+\s*)?\)", "", t)
    return t.strip()


def infer_default(field_type: str) -> str | None:
    """根据 field_type 推断 COALESCE 默认值。

    返回:
      "0"   → 数值类
      "''"  → 字符串类
      None  → 时间类或无法识别（不 COALESCE）
    """
    t = _normalize_type(field_type)
    if not t:
        return None
    # 精确匹配
    if t in _NUMERIC_TYPES:
        return "0"
    if t in _STRING_TYPES:
        return "''"
    if t in _TIME_TYPES:
        return None
    # 模糊匹配（带精度/区间修饰的，如 timestamp(0) without time zone）
    for nt in _NUMERIC_TYPES:
        if t.startswith(nt):
            return "0"
    for st in _STRING_TYPES:
        if t.startswith(st):
            return "''"
    for tt in ("date", "time", "timestamp"):
        if t.startswith(tt):
            return None
    # 布尔类
    if t.startswith("bool") or t.startswith("bit"):
        return None
    return None  # 无法识别 → 不 COALESCE


# ============================================================
# 表名 → CTE 名映射
# ============================================================

def _cte_name_for_table(table: str) -> str:
    """表名 → CTE 名：去 dwd_/dim_/ods_ 前缀 + 去 _f/_d/_i 后缀。

    dwd_payment_f → payment
    dim_user_level_d → user_level
    """
    t = table.lower().strip()
    # 去前缀
    for prefix in ("dwd_", "dim_", "ods_", "dws_", "dwb_", "dwm_", "dws_", "stg_"):
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    # 去后缀
    for suffix in ("_f", "_d", "_i", "_t"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    return f"cte_{t}" if t else f"cte_{table}"


# ============================================================
# SQL 片段生成
# ============================================================

def gen_direct_field_line(field: dict, rule_code: str) -> str:
    """生成 direct 字段的 SELECT 行。

    拿不准（缺 alias）→ 返回 TODO 注释行。
    """
    target = field.get("target_field", "")
    ftype = field.get("field_type", "")
    sf_list = field.get("source_fields", [])
    if not sf_list:
        return f"    -- TODO({rule_code}): {target} — 直取但 source_fields 为空"
    sf = sf_list[0]
    alias = sf.get("alias", "").strip()
    src_field = sf.get("field", "").strip()
    if not alias or not src_field:
        return f"    -- TODO({rule_code}): {target} — 直取但源别名/源字段缺失"

    default = infer_default(ftype)
    if default is not None:
        return f"    COALESCE({alias}.{src_field}, {default}) AS {target}"
    # 时间或无法识别
    if ftype:
        return f"    {alias}.{src_field} AS {target}"
    # 类型完全空 → 原样取值 + REVIEW
    return f"    {alias}.{src_field} AS {target}  -- REVIEW: 类型未知，未加 COALESCE"


def gen_assign_field_line(field: dict) -> str | None:
    """生成 assign 字段的 SELECT 行（审计字段固定值）。

    非 assign 或非审计字段 → 返回 None（调用方应改用 TODO）。
    """
    target = field.get("target_field", "")
    if target == "del_flag":
        return "    'N' AS del_flag"
    if target == "crt_cycle_id":
        return "    '${P_CYCLE_ID}' AS crt_cycle_id"
    if target == "last_upd_cycle_id":
        return "    '${P_CYCLE_ID}' AS last_upd_cycle_id"
    if target == "dw_last_update_date":
        return "    CURRENT_TIMESTAMP AS dw_last_update_date"
    # assign 但非审计字段 → None（交给 TODO）
    return None


def gen_aggregate_todo(field: dict, rule_code: str) -> str:
    """生成 aggregate/计算字段的 TODO 占位行。"""
    target = field.get("target_field", "")
    logic = field.get("design_logic", "")
    # 截断过长的 design_logic
    if len(logic) > 100:
        logic = logic[:97] + "..."
    return f"    -- TODO({rule_code}): {target} — {logic}"


# ============================================================
# CTE 骨架生成
# ============================================================

def _extract_join_key_from_condition(condition: str) -> str | None:
    """从 JOIN condition 抽取关联键字段名。

    'dof.user_id = dpf.user_id' → 'user_id'
    返回关联键的裸字段名（两边应该同名）。
    """
    if not condition:
        return None
    # 匹配 alias.field = alias.field
    m = re.search(r"(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)", condition)
    if m:
        # 优先返回非主表别名的那个（被关联表的键），但通常两边同名
        return m.group(2)
    return None


def gen_cte_block(join_safety: list, joins: list, source_tables: list,
                  rule_code: str) -> tuple[str, dict[str, str]]:
    """生成 CTE 骨架块。

    只对 join_safety 标记 join_key_unique=False 的表生成 CTE。
    返回 (cte_sql_block, table_to_cte_map)。
    table_to_cte_map: {源表名: cte名}，供主查询 JOIN 时用 CTE 名替代原表名。
    """
    if not join_safety:
        return "", {}

    # 找出需要收敛的表（非 unique）
    non_unique_tables = []
    for js in join_safety:
        table = js.get("table", "")
        is_unique = js.get("join_key_unique", True)
        if table and not is_unique:
            non_unique_tables.append(js)

    if not non_unique_tables:
        return "", {}

    # 源表 schema/alias 映射
    st_map = {}
    for st in source_tables:
        tname = st.get("table", "")
        st_map[tname] = {
            "schema": st.get("schema", ""),
            "alias": st.get("alias", ""),
        }

    # join condition → 关联键
    table_to_cte = {}
    cte_defs = []
    for js in non_unique_tables:
        table = js.get("table", "")
        strategy = js.get("strategy", "") or ""
        reason = js.get("reason", "") or ""
        cte_name = _cte_name_for_table(table)
        table_to_cte[table] = cte_name

        st_info = st_map.get(table, {})
        schema = st_info.get("schema", "")
        alias = st_info.get("alias", table[:3] if table else "t")

        # 找关联键：从 join_safety 里没有直接的 key，去 joins 找该表的 condition
        join_key = None
        for j in joins:
            j_alias = j.get("alias", "")
            # alias 对应的表名：从 source_tables 反查
            for s2 in source_tables:
                if s2.get("alias") == j_alias and s2.get("table") == table:
                    join_key = _extract_join_key_from_condition(j.get("condition", ""))
                    break
            if join_key:
                break
        # 兜底：从 reason 里抽标识符
        if not join_key:
            for m in re.finditer(r"([A-Za-z_]\w*)", reason):
                kw = m.group(1).lower()
                if kw not in ("按", "分组", "聚合", "收敛", "粒度", "group", "by"):
                    join_key = m.group(1)
                    break

        # 拼 CTE 骨架
        full_table = f"{schema}.{table}" if schema else table
        key_expr = f"{alias}.{join_key} AS {join_key}" if join_key else f"-- TODO: 补关联键（join_safety 未明确）"

        # strategy 提示
        strategy_hint = strategy if strategy else reason
        if not strategy_hint:
            strategy_hint = "需收敛到主表粒度（join_safety 未给 strategy）"

        cte_sql = (
            f"/* CTE {cte_name}: 收敛 {table} 到主表粒度\n"
            f"   join_safety: {strategy_hint} */\n"
            f"{cte_name} AS (\n"
            f"    SELECT\n"
            f"        {key_expr}"
        )
        if not join_key:
            cte_sql += "\n        -- TODO: 补关联键字段"
        cte_sql += (
            f"\n        -- TODO({cte_name}): 按 design_logic 填聚合/收敛字段\n"
            f"    FROM {full_table} {alias}\n"
            f"    WHERE {alias}.del_flag = 'N'"
        )
        if join_key:
            cte_sql += f"\n    GROUP BY {alias}.{join_key}"
        cte_sql += "\n)"
        cte_defs.append(cte_sql)

    if not cte_defs:
        return "", {}

    block = "WITH\n" + ",\n\n".join(cte_defs) + "\n\n"
    return block, table_to_cte


# ============================================================
# 主 SELECT 生成
# ============================================================

def gen_file_header(sliced: dict) -> str:
    """生成文件头注释。"""
    rule_code = sliced.get("rule_code", "")
    rule_name = sliced.get("rule_name", "")
    design_intent = sliced.get("design_intent", "")
    target_table = sliced.get("target_table", "")
    load_mode = sliced.get("load_mode", "truncate_table")
    source_tables = sliced.get("source_tables", [])

    src_lines = []
    for st in source_tables:
        schema = st.get("schema", "")
        table = st.get("table", "")
        alias = st.get("alias", "")
        src_lines.append(f"     - {schema}.{table}" + (f" ({alias})" if alias else ""))

    return (
        "/* =====================================================\n"
        f"   ETL 转换脚本（纯 SELECT，由调度/UT 包装 INSERT）\n"
        f"   规则: {rule_code} - {rule_name}\n"
        f"   目标表: {target_table}\n"
        f"   来源表:\n"
        + "\n".join(src_lines) + "\n"
        f"   写入方式: {load_mode}\n"
        f"   设计意图: {design_intent}\n"
        f"   =====================================================\n"
        f"   ★ 本文件由 codegen_direct.py 生成骨架，direct/assign 字段已填好。\n"
        f"   ★ 你的工作：填充 TODO 占位（aggregate/计算字段/CTE 收敛逻辑）。\n"
        f"   ★ 拿不准的内容工具会留 TODO，不会瞎生成——填完调 check_sql.py 校验。 */"
    )


def gen_select_fields(sliced: dict) -> list[str]:
    """生成主 SELECT 的字段行列表（按切片字段顺序）。"""
    rule_code = sliced.get("rule_code", "")
    fields = sliced.get("fields", [])
    lines = []
    for f in fields:
        ttype = f.get("transform_type", "")
        if ttype == "direct":
            lines.append(gen_direct_field_line(f, rule_code))
        elif ttype == "assign":
            assign_line = gen_assign_field_line(f)
            if assign_line:
                lines.append(assign_line)
            else:
                # assign 但非审计字段 → TODO
                lines.append(gen_aggregate_todo(f, rule_code))
        else:
            # aggregate / pivot / 其他加工类 → TODO
            lines.append(gen_aggregate_todo(f, rule_code))
    return lines


def _is_chinese_filter(filt: str) -> bool:
    """判断 filter 字段是否是中文说明（而非 SQL）。

    designer 常把业务说明写进 filter（如"取省份名称"、"CTE 聚合结果"），
    这些不能拼进 SQL。判断标准：含中文字符 → 是说明，跳过。
    """
    if not filt:
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", filt))


def gen_from_join(sliced: dict, table_to_cte: dict) -> str:
    """生成 FROM/JOIN/WHERE 骨架。

    关键：designer 在 joins 里声明的 alias 可能比 source_tables 多——
    有 CTE 名（behavior_agg）、中间表别名（tmp1）、同表二次别名（drf/drf_city）。
    alias 不在 source_tables 里的，当作 CTE/中间表直接用别名当表名（不加 schema）。
    """
    source_tables = sliced.get("source_tables", [])
    joins = sliced.get("joins", [])
    incremental = sliced.get("incremental", {}) or {}

    # 别名 → 表信息映射（只含 source_tables 里的物理表）
    alias_to_table = {}
    alias_to_schema = {}
    for st in source_tables:
        a = st.get("alias", "")
        t = st.get("table", "")
        s = st.get("schema", "")
        if a:
            alias_to_table[a] = t
            alias_to_schema[a] = s

    # 找主表：joins 里 type=main，或 source_tables 第一个
    main_alias = None
    for j in joins:
        if j.get("type", "").lower() == "main":
            main_alias = j.get("alias", "")
            break
    if not main_alias and source_tables:
        main_alias = source_tables[0].get("alias", "")
    if not main_alias:
        return "-- TODO: 未找到主表，请手动写 FROM"

    main_table = alias_to_table.get(main_alias, "")
    main_schema = alias_to_schema.get(main_alias, "")
    main_full = f"{main_schema}.{main_table}" if main_schema and main_table else main_table

    lines = [f"FROM {main_full} {main_alias}"]

    # JOIN 子句
    for j in joins:
        jtype = j.get("type", "").upper()
        if jtype == "MAIN" or not jtype:
            continue
        j_alias = j.get("alias", "")
        condition = j.get("condition", "")
        jfilter = j.get("filter", "")

        j_table = alias_to_table.get(j_alias, "")
        j_schema = alias_to_schema.get(j_alias, "")

        # 如果该表需要收敛（在 table_to_cte 里），JOIN CTE 名
        if j_table in table_to_cte:
            cte_name = table_to_cte[j_table]
            join_cond = condition
            if j_alias and j_alias in condition:
                join_cond = condition.replace(f"{j_alias}.", f"{cte_name}.")
            line = f"{jtype} {cte_name} ON {join_cond}"
        elif j_table:
            # 物理表：带 schema + 维表加 del_flag 过滤
            j_full = f"{j_schema}.{j_table}" if j_schema else j_table
            join_cond = condition if condition else "-- TODO: 补 JOIN 条件"
            del_flag_clause = f" AND {j_alias}.del_flag = 'N'" if j_alias else ""
            line = f"{jtype} {j_full} {j_alias} ON {join_cond}{del_flag_clause}"
        else:
            # alias 不在 source_tables → 是 CTE 名或中间表别名，直接用别名当表名
            join_cond = condition if condition else "-- TODO: 补 JOIN 条件"
            # 中间表/CTE 一般不需要 del_flag（设计已在内部处理），但加上也无害
            line = f"{jtype} {j_alias} ON {join_cond}"

        # filter：只在是合法 SQL 片段时才拼（中文说明跳过）
        if jfilter and not _is_chinese_filter(jfilter):
            line += f" AND {j_alias}.{jfilter}" if j_alias and "=" not in jfilter.split()[0] else f" AND {jfilter}"
        lines.append(line)

    # WHERE
    where_parts = [f"{main_alias}.del_flag = 'N'"]
    # 增量过滤
    inc_filter = incremental.get("filter", "") if isinstance(incremental, dict) else ""
    if inc_filter:
        where_parts.append(inc_filter)

    lines.append("WHERE " + "\n  AND ".join(where_parts))

    # GROUP BY：聚合规则留 TODO 让 coder 按 design_logic 填。
    # 不自动用 business_key——聚合规则的主查询分组键可能和 business_key 不同
    # （如 business_key=order_id 但聚合到 user_id 粒度），猜错了反而误导 coder。
    grain = sliced.get("grain", {}) or {}
    grain_change = str(grain.get("change", ""))
    main_query_aggregate = "多行聚合" in grain_change or "聚合收敛" in grain_change
    if main_query_aggregate:
        lines.append("-- TODO: 补 GROUP BY（按 design_logic 的分组键，通常见 grain.output 描述的粒度）")

    return "\n".join(lines)


def gen_select_sql(sliced: dict) -> str:
    """生成完整的填空版 SELECT SQL。"""
    rule_code = sliced.get("rule_code", "")

    # 1. 文件头
    header = gen_file_header(sliced)

    # 2. CTE 骨架
    cte_block, table_to_cte = gen_cte_block(
        sliced.get("join_safety", []),
        sliced.get("joins", []),
        sliced.get("source_tables", []),
        rule_code,
    )

    # 3. 主 SELECT 字段
    field_lines = gen_select_fields(sliced)

    # 4. FROM/JOIN/WHERE
    from_join = gen_from_join(sliced, table_to_cte)

    # 组装
    parts = [header, ""]
    if cte_block:
        parts.append(cte_block)
    parts.append("SELECT")
    parts.append(",\n".join(field_lines))
    parts.append(from_join + ";")

    return "\n".join(parts)


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="直取字段骨架生成器: 从 ts.json 规则切片生成 SELECT 填空骨架"
    )
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--rule", required=True, help="规则编号，如 R0001")
    parser.add_argument("--output", default="", help="输出 SQL 路径（默认打印到 stdout）")
    args = parser.parse_args()

    # 读 ts.json
    ts_path = Path(args.ts)
    if not ts_path.exists():
        print(f"错误: ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(2)
    ts = __import__("json").loads(ts_path.read_text(encoding="utf-8"))

    # 切片
    try:
        sliced = slice_rule(ts, args.rule)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 生成
    sql = gen_select_sql(sliced)

    # 统计
    fields = sliced.get("fields", [])
    n_direct = sum(1 for f in fields if f.get("transform_type") == "direct")
    n_assign = sum(1 for f in fields if f.get("transform_type") == "assign")
    n_other = len(fields) - n_direct - n_assign

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(sql + "\n", encoding="utf-8")
        print(f"骨架产出: {out}", file=sys.stderr)
        print(f"规则: {args.rule}, 字段: {len(fields)} (direct={n_direct} assign={n_assign} 待填TODO={n_other})",
              file=sys.stderr)
    else:
        print(sql)


if __name__ == "__main__":
    main()
