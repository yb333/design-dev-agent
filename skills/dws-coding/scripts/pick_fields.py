#!/usr/bin/env python3
"""
字段查询器 (pick_fields): coder 写 SQL 时随取随用的字段工具。

★ 定位：coder 的"复制粘贴"工具，不是代码生成器。
   coder 先看加工字段构思框架，再随写随查——
   写到某个 JOIN 时，查这个表的直取字段，粘贴进 SELECT。
   SQL 的所有结构决策（FROM/JOIN/WHERE/CTE/del_flag/聚合）都由 coder 做。

三个查询命令：
  --list          规则总览：每个源表有多少直取字段 + 加工字段数
  --alias <别名>  该表的直取字段行（COALESCE 已填好，可直接粘贴）
  --field <字段>  单字段详情（类型/来源/design_logic/是否直取）

用法:
  python pick_fields.py --ts ts.json --rule R0001 --list
  python pick_fields.py --ts ts.json --rule R0001 --alias duf
  python pick_fields.py --ts ts.json --rule R0001 --field order_status

退出码: 0=成功, 1=规则不存在/找不到, 2=文件错误
"""

import sys
import re
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
# field_type → COALESCE 默认值推断
# ============================================================

_NUMERIC_TYPES = {
    "int", "integer", "bigint", "smallint", "tinyint",
    "decimal", "numeric", "number",
    "float", "double", "real", "double precision", "money",
}
_STRING_TYPES = {
    "varchar", "char", "text", "nvarchar", "nchar",
    "varchar2", "nvarchar2", "clob",
}
_TIME_TYPES = {
    "date", "datetime", "timestamp", "time",
    "timestamp without time zone", "timestamp with time zone",
    "timestamp(0)", "timestamp(0) without time zone",
    "datetime2", "smalldatetime",
}


def _normalize_type(field_type: str) -> str:
    """归一化 field_type：去括号数值参数、转小写。"""
    if not field_type:
        return ""
    t = field_type.strip().lower()
    t = re.sub(r"\(\s*\d+\s*(,\s*\d+\s*)?\)", "", t)
    return t.strip()


def infer_default(field_type: str) -> str | None:
    """推断 COALESCE 默认值：'0'(数值) / "''"(字符串) / None(时间或未知，不 COALESCE)。"""
    t = _normalize_type(field_type)
    if not t:
        return None
    if t in _NUMERIC_TYPES:
        return "0"
    if t in _STRING_TYPES:
        return "''"
    if t in _TIME_TYPES:
        return None
    # 前缀模糊匹配（处理带精度的类型名）
    for nt in _NUMERIC_TYPES:
        if t.startswith(nt):
            return "0"
    for st in _STRING_TYPES:
        if t.startswith(st):
            return "''"
    for tt in ("date", "time", "timestamp"):
        if t.startswith(tt):
            return None
    if t.startswith("bool") or t.startswith("bit"):
        return None
    return None


def gen_direct_line(field: dict) -> str:
    """生成 direct 字段的 COALESCE 行（拿不准留注释，不猜 alias）。

    不带缩进、不带尾逗号——调用方决定格式。
    """
    target = field.get("target_field", "")
    ftype = field.get("field_type", "")
    sf_list = field.get("source_fields", [])
    if not sf_list:
        return f"-- TODO: {target} — 直取但 source_fields 为空"
    sf = sf_list[0]
    alias = sf.get("alias", "").strip()
    src = sf.get("field", "").strip()
    if not alias or not src:
        return f"-- TODO: {target} — 直取但源别名/源字段缺失"

    default = infer_default(ftype)
    if default is not None:
        return f"COALESCE({alias}.{src}, {default}) AS {target}"
    if ftype:
        return f"{alias}.{src} AS {target}"
    return f"{alias}.{src} AS {target}  -- REVIEW: 类型未知，未加 COALESCE"


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

    lines = [f"-- {rule_code}: {rule_name}", ""]

    if direct_by_alias:
        lines.append("-- 直取字段（按源表分布，用 --alias <别名> 查具体行）:")
        # 按字段数降序
        for alias in sorted(direct_by_alias, key=lambda a: -len(direct_by_alias[a])):
            display = alias_map.get(alias, alias)
            n = len(direct_by_alias[alias])
            lines.append(f"  {alias:10s} ({display}): {n} 个")
        lines.append("")

    if processed:
        lines.append(f"-- 加工字段 {len(processed)} 个（需按 design_logic 实现，用 --field <字段> 查详情）:")
        for f in processed:
            lines.append(f"  {f.get('target_field', ''):30s} {f.get('transform_type', '')}")
        lines.append("")

    n_direct = sum(len(v) for v in direct_by_alias.values())
    n_audit = sum(1 for f in fields
                  if f.get("transform_type") == "assign"
                  and f.get("target_field") in ("del_flag", "crt_cycle_id",
                                                "last_upd_cycle_id", "dw_last_update_date"))
    lines.append(f"-- 汇总: 直取 {n_direct} / 加工 {len(processed)} / 审计字段 {n_audit}")
    if not direct_by_alias:
        lines.append("-- （此规则无直取字段，纯聚合/加工规则）")

    return "\n".join(lines)


def query_alias(sliced: dict, alias: str) -> str:
    """查某表的直取字段行（可粘贴进 SELECT）。"""
    fields = sliced.get("fields", [])
    alias_map = _alias_to_table_map(sliced)
    display = alias_map.get(alias, alias)

    matched = []
    for f in fields:
        if f.get("transform_type") != "direct":
            continue
        sf_list = f.get("source_fields", [])
        f_alias = sf_list[0].get("alias", "") if sf_list else ""
        if f_alias == alias:
            matched.append(f)

    if not matched:
        # 检查这个 alias 是否存在（可能是打错了）
        all_aliases = set(alias_map.keys())
        direct_aliases = {sf.get("alias", "")
                          for f in fields if f.get("transform_type") == "direct"
                          for sf in f.get("source_fields", [])}
        if alias in all_aliases:
            return f"-- {display} ({alias}) 存在但无直取字段（可能全是加工字段）"
        return (f"-- 未找到 alias '{alias}'。\n"
                f"-- 规则的 source_tables 别名: {sorted(all_aliases)}\n"
                f"-- 有直取字段的别名: {sorted(direct_aliases)}")

    lines = [f"-- {display} ({alias}) 直取字段 {len(matched)} 个:"]
    for f in matched:
        lines.append("    " + gen_direct_line(f) + ",")
    return "\n".join(lines)


def query_field(sliced: dict, field_name: str) -> str:
    """查单字段详情。"""
    fields = sliced.get("fields", [])

    # 大小写不敏感匹配
    for f in fields:
        if f.get("target_field", "").lower() == field_name.lower():
            ttype = f.get("transform_type", "")
            lines = [f"-- 字段: {f.get('target_field', '')}"]
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

            # 如果是 direct，额外给出生成行
            if ttype == "direct":
                lines.append("")
                lines.append(f"   生成行: {gen_direct_line(f)}")

            return "\n".join(lines)

    # 模糊匹配建议
    all_fields = [f.get("target_field", "") for f in fields]
    similar = [fn for fn in all_fields if field_name.lower() in fn.lower()]
    hint = f"\n-- 字段名含 '{field_name}' 的: {similar}" if similar else ""
    return f"-- 未找到字段 '{field_name}'。{hint}"


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="字段查询器: coder 写 SQL 时随取随用（--list 总览 / --alias 按表查 / --field 查单字段）"
    )
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--rule", required=True, help="规则编号，如 R0001")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="规则总览：源表直取字段分布 + 加工字段清单")
    group.add_argument("--alias", help="查某表的直取字段行（别名，如 duf）")
    group.add_argument("--field", help="查单字段详情（字段名）")
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


if __name__ == "__main__":
    main()
