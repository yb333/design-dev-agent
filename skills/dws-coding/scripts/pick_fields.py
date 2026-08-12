#!/usr/bin/env python3
"""
字段查询器 (pick_fields): coder 写 SQL 时随取随用的字段工具。

★ 定位：coder 的"复制粘贴"工具，不是代码生成器。
   coder 先看加工字段构思框架，再随写随查——
   写到某个 JOIN 时，查这个表的直取字段，粘贴进 SELECT。
   SQL 的所有结构决策（FROM/JOIN/WHERE/CTE/del_flag/聚合）都由 coder 做。

三个查询命令：
  --list          规则总览：每个源表有多少直取字段 + 加工字段数
  --alias <别名>  该表的直取字段行（别名.字段 AS 目标，可直接粘贴）
  --field <字段>  单字段详情（类型/来源/design_logic/是否直取）

用法:
  python pick_fields.py --ts ts.json --rule R0001 --list
  python pick_fields.py --ts ts.json --rule R0001 --alias duf
  python pick_fields.py --ts ts.json --rule R0001 --field order_status

退出码: 0=成功, 1=规则不存在/找不到, 2=文件错误
"""

import sys
import argparse
from pathlib import Path

# 复用 slice_ts 的切片逻辑
try:
    from slice_ts import slice_rule
except ImportError:
    _here = Path(__file__).resolve().parent
    if str(_here) not in sys.path:
        sys.path.insert(0, str(_here))
    from slice_ts import slice_rule


# ============================================================
# direct 字段行生成
# ============================================================

def gen_direct_line(field: dict, alias_map: dict = None) -> str:
    """生成 direct 字段的取值行（别名.字段 AS 目标字段）。

    ★ 不自动加 COALESCE——该不该 COALESCE、用什么默认值，是业务语义判断：
      - 金额类 NULL→0 合理
      - 主键/外键 NULL→0 会掩盖 LEFT JOIN 关联失败，不该加
      - 状态字段 NULL 可能有业务含义，不该盲目转空串
    这些由 coder 根据字段语义决定，工具只负责机械填充取值表达式。

    alias_map（可选）: {table: alias} 唯一映射。当 source_fields.alias 为空
    但 table 有时，从这里反查补全 alias（BA 常漏填 source_alias）。
    同表多别名（一对多）不进 map，留 TODO 让 coder 判断来自哪个关联。

    不带缩进、不带尾逗号——调用方决定格式。
    """
    target = field.get("target_field", "")
    sf_list = field.get("source_fields", [])
    if not sf_list:
        return f"/* TODO: {target} — 直取但 source_fields 为空 */"
    sf = sf_list[0]
    alias = sf.get("alias", "").strip()
    src = sf.get("field", "").strip()
    table = sf.get("table", "").strip()

    # alias 为空时，从 alias_map 反查（table → alias）
    if not alias and table and alias_map:
        alias = alias_map.get(table, "")

    if not alias or not src:
        hint = "源别名缺失" if not alias else "源字段缺失"
        return f"/* TODO: {target} — 直取但{hint} */"
    return f"{alias}.{src} AS {target}"


# ============================================================
# 查询实现
# ============================================================

def _alias_to_table_map(sliced: dict) -> dict[str, str]:
    """alias → 'schema.table' 显示名。"""
    m = {}
    for st in sliced.get("source_tables", []):
        a = st.get("alias", "")
        s = st.get("schema", "")
        t = st.get("table", "")
        if a:
            m[a] = f"{s}.{t}" if s and t else t
    return m


def _build_table_alias_map(sliced: dict) -> dict[str, str]:
    """table → alias 的唯一映射（用于反查补全 source_fields 里漏填的 alias）。

    只含"一个 table 只对应一个 alias"的映射。
    同表多别名（如 dub/dub7/dub10 都是 dim_user_base_d）不进 map——
    这时 coder 要判断字段来自哪个关联，工具不能瞎猜。
    """
    from collections import defaultdict
    t2aliases = defaultdict(list)
    for st in sliced.get("source_tables", []):
        t = st.get("table", "").strip()
        a = st.get("alias", "").strip()
        if t and a:
            t2aliases[t].append(a)
    return {t: aliases[0] for t, aliases in t2aliases.items() if len(set(aliases)) == 1}
    return m


def query_list(sliced: dict) -> str:
    """规则总览：源表清单 + 每表直取字段数 + 加工字段数。

    帮 coder 建立全貌——写 JOIN 时心里有数每个表取多少字段。
    """
    rule_code = sliced.get("rule_code", "")
    rule_name = sliced.get("rule_name", "")
    fields = sliced.get("fields", [])
    alias_map = _alias_to_table_map(sliced)

    # 按别名分组统计 direct
    direct_by_alias: dict[str, list[dict]] = {}
    for f in fields:
        if f.get("transform_type") != "direct":
            continue
        sf_list = f.get("source_fields", [])
        alias = sf_list[0].get("alias", "?") if sf_list else "?"
        direct_by_alias.setdefault(alias, []).append(f)

    # 加工字段（aggregate/其他非 direct 非 assign）
    processed = [f for f in fields
                 if f.get("transform_type") not in ("direct", "assign")]

    lines = [f"/* {rule_code}: {rule_name} */", ""]

    if direct_by_alias:
        lines.append("/* 直取字段（按源表分布，用 --alias <别名> 查具体行）:")
        # 按字段数降序
        for alias in sorted(direct_by_alias, key=lambda a: -len(direct_by_alias[a])):
            display = alias_map.get(alias, alias)
            n = len(direct_by_alias[alias])
            lines.append(f"  {alias:10s} ({display}): {n} 个")
        lines.append("*/")
        lines.append("")

    if processed:
        lines.append(f"/* 加工字段 {len(processed)} 个（需按 design_logic 实现，用 --field <字段> 查详情）:")
        for f in processed:
            lines.append(f"  {f.get('target_field', ''):30s} {f.get('transform_type', '')}")
        lines.append("*/")
        lines.append("")

    n_direct = sum(len(v) for v in direct_by_alias.values())
    n_audit = sum(1 for f in fields
                  if f.get("transform_type") == "assign"
                  and f.get("target_field") in ("del_flag", "crt_cycle_id",
                                                "last_upd_cycle_id", "dw_last_update_date"))
    lines.append(f"/* 汇总: 直取 {n_direct} / 加工 {len(processed)} / 审计字段 {n_audit} */")
    if not direct_by_alias:
        lines.append("/* 此规则无直取字段，纯聚合/加工规则 */")

    return "\n".join(lines)


def query_alias(sliced: dict, alias: str) -> str:
    """查某表的直取字段行（可粘贴进 SELECT）。"""
    fields = sliced.get("fields", [])
    alias_map = _alias_to_table_map(sliced)
    table_alias_map = _build_table_alias_map(sliced)
    display = alias_map.get(alias, alias)

    matched = []
    for f in fields:
        if f.get("transform_type") != "direct":
            continue
        sf_list = f.get("source_fields", [])
        f_alias = sf_list[0].get("alias", "") if sf_list else ""
        f_table = sf_list[0].get("table", "") if sf_list else ""
        # 匹配：alias 直接匹配，或 alias 空但 table 反查到这个 alias
        # （BA 常漏填 source_alias，但填了 source_table，可反查补全）
        if f_alias == alias:
            matched.append(f)
        elif not f_alias and f_table and table_alias_map.get(f_table) == alias:
            matched.append(f)

    if not matched:
        # 检查这个 alias 是否存在（可能是打错了）
        all_aliases = set(alias_map.keys())
        direct_aliases = {sf.get("alias", "")
                          for f in fields if f.get("transform_type") == "direct"
                          for sf in f.get("source_fields", [])}
        if alias in all_aliases:
            return f"/* {display} ({alias}) 存在但无直取字段（可能全是加工字段） */"
        return (f"/* 未找到 alias '{alias}'。*/\n"
                f"/* 规则的 source_tables 别名: {sorted(all_aliases)} */\n"
                f"/* 有直取字段的别名: {sorted(direct_aliases)} */")

    lines = [f"/* {display} ({alias}) 直取字段 {len(matched)} 个 */"]
    for f in matched:
        lines.append("    " + gen_direct_line(f, table_alias_map) + ",")
    return "\n".join(lines)


def query_field(sliced: dict, field_name: str) -> str:
    """查单字段详情。"""
    fields = sliced.get("fields", [])

    # 大小写不敏感匹配
    for f in fields:
        if f.get("target_field", "").lower() == field_name.lower():
            ttype = f.get("transform_type", "")
            lines = [f"[字段] {f.get('target_field', '')}"]
            lines.append(f"   类型: {f.get('field_type', '')}")
            lines.append(f"   注释: {f.get('field_comment', '')}")
            lines.append(f"   分类: {ttype}")

            sf_list = f.get("source_fields", [])
            if sf_list:
                for sf in sf_list:
                    a = sf.get("alias", "")
                    s = sf.get("field", "")
                    lines.append(f"   来源: {a}.{s}" if a and s else f"   来源: (缺失)")
            else:
                lines.append("   来源: (无)")

            logic = f.get("design_logic", "")
            if logic:
                lines.append(f"   口径: {logic}")

            # 如果是 direct，额外给出生成行（带 alias_map 反查补全）
            if ttype == "direct":
                table_alias_map = _build_table_alias_map(sliced)
                lines.append("")
                lines.append(f"   生成行: {gen_direct_line(f, table_alias_map)}")

            return "\n".join(lines)

    # 模糊匹配建议
    all_fields = [f.get("target_field", "") for f in fields]
    similar = [fn for fn in all_fields if field_name.lower() in fn.lower()]
    hint = f"\n[提示] 字段名含 '{field_name}' 的: {similar}" if similar else ""
    return f"[未找到] 字段 '{field_name}'。{hint}"


def _resolve_source_table(sliced: dict, name: str) -> tuple[str, str] | None:
    """把入参（别名/表名短名/全名）解析成 (schema, table)。

    查找顺序：别名 → 表短名 → schema.table 全名。
    返回 None 表示在 source_tables 里找不到。
    """
    sts = sliced.get("source_tables", [])
    name_lower = name.lower().strip()
    # 1. 当别名找
    for st in sts:
        if st.get("alias", "").lower() == name_lower:
            return st.get("schema", ""), st.get("table", "")
    # 2. 当表短名找
    for st in sts:
        if st.get("table", "").lower() == name_lower:
            return st.get("schema", ""), st.get("table", "")
    # 3. 当 schema.table 全名找
    for st in sts:
        full = f"{st.get('schema','')}.{st.get('table','')}".lower()
        if full == name_lower:
            return st.get("schema", ""), st.get("table", "")
    return None


def query_table_fields(sliced: dict, name: str, ts_path) -> str:
    """查某张源表的完整字段清单（来自 schema_cache，连库时产出）。

    coder 写加工字段时确认 design_logic 引用的字段在不在源表里。
    schema_cache 不存在（未连库）→ 提示不阻断。
    """
    resolved = _resolve_source_table(sliced, name)
    if not resolved:
        all_sts = sliced.get("source_tables", [])
        hints = [f"{st.get('alias','')}({st.get('table','')})" for st in all_sts]
        return (f"[未找到] '{name}' 不在本规则的 source_tables 里。\n"
                f"[提示] 本规则的源表: {', '.join(hints[:10])}"
                + (" ..." if len(hints) > 10 else ""))

    schema, table = resolved
    # 定位 schema_cache.json：ts.json 同级的 _internal/
    cache_path = Path(ts_path).parent / "_internal" / "schema_cache.json"
    if not cache_path.exists():
        return (f"[未连库] schema_cache.json 不存在（{cache_path}）。\n"
                f"无法确认 {schema}.{table} 的字段存在性，凭 design_logic 写，标注待连库确认。")

    try:
        cache = __import__("json").loads(cache_path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"[错误] schema_cache.json 读取失败: {e}"

    tables_map = cache.get("tables", {})
    cached_at = cache.get("cached_at", "")
    # schema_cache 的 key 是 "schema.table" 小写
    key = f"{schema}.{table}".lower()
    cols = tables_map.get(key)
    if not cols:
        return (f"[未缓存] {schema}.{table} 不在 schema_cache 里（连库时可能没查这张表）。\n"
                f"缓存的表: {sorted(tables_map.keys())[:10]}")

    # 输出字段清单
    lines = [f"/* {schema}.{table} 字段清单（来自 schema_cache，连库时间: {cached_at}）*/"]
    for col, ctype in cols.items():
        lines.append(f"  {col:30s} {ctype}")
    lines.append("")
    lines.append(f"/* 共 {len(cols)} 个字段 */")
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="字段查询器: coder 写 SQL 时随取随用（--list/--alias/--field/--table-fields）"
    )
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--rule", required=True, help="规则编号，如 R0001")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="规则总览：源表直取字段分布 + 加工字段清单")
    group.add_argument("--alias", help="查某表的直取字段行（别名，如 duf）")
    group.add_argument("--field", help="查单字段详情（字段名）")
    group.add_argument("--table-fields", help="查源表完整字段清单（别名/表名，如 dub/dwd_user_behavior_f）",
                       dest="table_fields")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    if not ts_path.exists():
        print(f"错误: ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(2)
    ts = __import__("json").loads(ts_path.read_text(encoding="utf-8"))

    try:
        sliced = slice_rule(ts, args.rule)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    if args.list:
        print(query_list(sliced))
    elif args.alias:
        print(query_alias(sliced, args.alias))
    elif args.field:
        print(query_field(sliced, args.field))
    elif args.table_fields:
        print(query_table_fields(sliced, args.table_fields, ts_path))


if __name__ == "__main__":
    main()
