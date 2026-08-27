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

# 查缓存字段的能力下沉在 design-dev-shared（designer/coder 公共），--table-fields 复用
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from schema_query import query_fields


# ============================================================
# direct 字段行生成
# ============================================================

def _alias_to_table_map(sliced: dict) -> dict:
    """alias → 'schema.table' 显示名。"""
    m = {}
    for st in sliced.get("source_tables", []):
        a = st.get("alias", "")
        s = st.get("schema", "")
        t = st.get("table", "")
        if a:
            m[a] = f"{s}.{t}" if s and t else t
    return m


def _bucket_targets(fields: dict) -> set:
    """三桶的全部目标字段名（小写）。direct 串解析 AS 后名（无 AS 则列名）。"""
    out = set()
    for p_ in fields.get("processed", []):
        if p_.get("target"):
            out.add(p_["target"].lower())
    for a in fields.get("assign", []):
        if a.get("target"):
            out.add(a["target"].lower())
    for d in fields.get("direct", []):
        t = str(d).rsplit(" AS ", 1)[-1].strip() if " AS " in str(d) else str(d).rsplit(".", 1)[-1].strip()
        if t:
            out.add(t.lower())
    return out


def _direct_col(ref: str) -> str:
    """direct 串 → 源列名（a.col AS x → col；a.col → col）。"""
    base = str(ref).split(" AS ")[0].strip()
    return base.rsplit(".", 1)[-1].strip()


def query_list(sliced: dict) -> str:
    """规则总览：源表清单 + 每别名直取数 + 加工/赋值字段。"""
    rule_code = sliced.get("rule_code", "")
    rule_name = sliced.get("rule_name", "")
    fields = sliced.get("fields") or {}
    alias_map = _alias_to_table_map(sliced)

    direct_by_alias: dict[str, list[str]] = {}
    for d in fields.get("direct", []):
        a = str(d).split(".", 1)[0].strip()
        direct_by_alias.setdefault(a, []).append(str(d))
    processed = fields.get("processed", [])
    assigns = fields.get("assign", [])
    from dws_standards import STANDARD_AUDIT_NAMES
    n_audit = sum(1 for a in assigns if a.get("target") in STANDARD_AUDIT_NAMES)

    lines = [f"/* {rule_code}: {rule_name} */", ""]
    if direct_by_alias:
        lines.append("/* 直取字段（按源表分布，用 --alias <别名> 查具体行）:")
        for alias in sorted(direct_by_alias, key=lambda a: -len(direct_by_alias[a])):
            display = alias_map.get(alias, alias)
            lines.append(f"  {alias:10s} ({display}): {len(direct_by_alias[alias])} 个")
        lines.append("*/")
        lines.append("")
    if processed:
        lines.append(f"/* 加工字段 {len(processed)} 个（需按 logic 实现，用 --field <字段> 查详情）:")
        for f in processed:
            lines.append(f"  {f.get('target', '')}")
        lines.append("*/")
        lines.append("")
    n_direct = sum(len(v) for v in direct_by_alias.values())
    lines.append(f"/* 汇总: 直取 {n_direct} / 加工 {len(processed)} / 赋值 {len(assigns)}（含审计 {n_audit}） */")
    if not direct_by_alias:
        lines.append("/* 此规则无直取字段，纯聚合/加工规则 */")
    return "\n".join(lines)


def query_alias(sliced: dict, alias: str) -> str:
    """查某别名的直取字段行（可粘贴进 SELECT，带尾逗号）。"""
    fields = sliced.get("fields") or {}
    alias_map = _alias_to_table_map(sliced)
    display = alias_map.get(alias, alias)
    matched = [str(d) for d in fields.get("direct", []) if str(d).split(".", 1)[0].strip() == alias]
    if not matched:
        all_aliases = set(alias_map.keys())
        direct_aliases = {str(d).split(".", 1)[0].strip() for d in fields.get("direct", [])}
        if alias in all_aliases:
            return f"/* {display} ({alias}) 存在但无直取字段（可能全是加工字段） */"
        return (f"/* 未找到 alias '{alias}'。*/\n"
                f"/* 规则的 source_tables 别名: {sorted(all_aliases)} */\n"
                f"/* 有直取字段的别名: {sorted(direct_aliases)} */")
    lines = [f"/* {display} ({alias}) 直取字段 {len(matched)} 个 */"]
    for d in matched:
        lines.append("    " + d + ",")
    return "\n".join(lines)


def query_field(sliced: dict, field_name: str) -> str:
    """查单字段详情（桶归属 + 口径/值/直取行）。"""
    fields = sliced.get("fields") or {}
    fl = field_name.lower()
    for p_ in fields.get("processed", []):
        if str(p_.get("target", "")).lower() == fl:
            lines = [f"[字段] {p_.get('target')}（加工）",
                     f"   口径: {p_.get('logic', '')}"]
            refs = p_.get("refs") or []
            if refs:
                lines.append(f"   引用: {', '.join(refs)}")
            return "\n".join(lines)
    for a in fields.get("assign", []):
        if str(a.get("target", "")).lower() == fl:
            return f"[字段] {a.get('target')}（赋值）\n   值: {a.get('value', '')}"
    for d in fields.get("direct", []):
        t = str(d).rsplit(" AS ", 1)[-1].strip() if " AS " in str(d) else _direct_col(str(d))
        if t.lower() == fl:
            return f"[字段] {t}（直取）\n   生成行: {d}"
    similar = sorted(t for t in _bucket_targets(fields) if fl in t)
    hint = f"\n[提示] 字段名含 '{field_name}' 的: {similar}" if similar else ""
    return f"[未找到] 字段 '{field_name}'。{hint}"


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
