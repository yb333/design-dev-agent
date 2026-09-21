"""reorder_select —— SELECT 顶层投影按 INSERT 列清单序重排（coder 写完的收尾动作）。

2026-09-21 内网实证：coder 写完 SELECT 要按目标表序重排字段，没有工具只能手排
（LLM 手排长清单=确定性工作交给模型必漂，排一轮查一轮烧轮次）。本工具=纯
permutation：期望序与 INSERT 列清单**同函数同源**（run_ut._resolve_insert_columns：
结构源序 ∩ 规则产出列——SELECT 排到与 INSERT 清单完全一致，按位对齐零错位）；
各项表达式**原文保持不动只换顺序**（括号感知切分，case when 多行/函数嵌套随项走）。
幂等：已按序=零改动。opt 场景**不适用**（baseline 老列序受 fence 锁定，重排=动老列）。

用法：
  python reorder_select.py --sql {etl/R0001.sql} --ts {ts.json} --rule R0001 [--dry-run]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from sql_parse import split_top_projection_items, split_cte_main  # noqa: E402
from run_ut import _resolve_insert_columns, rule_output_fields  # noqa: E402


def reorder(sql: str, expect: list[str]) -> tuple[str, list[str]]:
    """重排主查询顶层投影到 expect 序。返回 (新 SQL, 披露行)。

    规则：expect 命中的项按 expect 序在前；未命中项（多列/无名/重名后续）保持
    原相对序在后（对错归 check_sql/6a 对账，本工具只管序）；拒改形态原样返回+披露。
    """
    items = split_top_projection_items(sql)
    if items is None:
        return sql, ["无可解析的顶层 SELECT..FROM——不动（宁放过不误报）"]
    if items and items[0][0] == "*":
        return sql, ["SELECT * ——不重排（check_sql 会拦）"]
    # UNION 场景拒改：两支按位对齐，只重排第一支会破坏对齐（切分只取第一支）
    _cte, main = split_cte_main(sql)
    if re.search(r'\bUNION\b', main if main else sql, re.IGNORECASE):
        return sql, ["含 UNION（多支按位对齐）——不重排（各支单独写对齐，或拆规则）"]
    notes = []
    by_name: dict[str, str] = {}
    for name, text in items:
        if name is None:
            notes.append("存在无 AS 的函数表达式项——该项保持原位（建议补 AS 别名）")
        elif name in by_name:
            notes.append(f"投影重名列 {name}——首个参与重排，后续保持原位（重名是错）")
        else:
            by_name[name] = text
    ordered = [(f, by_name.pop(f)) for f in expect if f in by_name]
    placed_texts = {t for _, t in ordered}
    leftovers = [(n, t) for n, t in items if t not in placed_texts]   # 原相对序收尾
    new_items = ordered + leftovers
    old_texts = [t for _, t in items]
    new_texts = [t for _, t in new_items]
    if new_texts == old_texts:
        return sql, ["已按 INSERT 列清单序——零改动（幂等）"]
    # 写回：body 为原文后缀（split_cte_main 语义）——前缀（WITH 段/头注释）保持不动
    _cte, main = split_cte_main(sql)
    body = main if main else sql
    if not sql.endswith(body):
        return sql, ["主查询体定位失败（非原文后缀）——不动（宁放过）"]
    m = re.search(r'\bSELECT\b(.*?)\bFROM\b', body, re.IGNORECASE | re.DOTALL)
    if not m:
        return sql, ["无可解析的顶层 SELECT..FROM——不动"]
    new_body = (body[:m.start(1)] + "\n    " + ",\n    ".join(new_texts) + "\n"
                + body[m.end(1):])
    new_sql = sql[:len(sql) - len(body)] + new_body
    return new_sql, notes or []


def main() -> int:
    ap = argparse.ArgumentParser(
        description="SELECT 顶层投影按 INSERT 列清单序重排（幂等；只换序不改表达式）",
        epilog="期望序=结构源序∩规则产出列（与 INSERT 列清单同源）——按位对齐零错位。"
               "opt 场景不适用（baseline 老列序受 fence 锁定）。")
    ap.add_argument("--sql", required=True, help="coder 的 SELECT 文件路径")
    ap.add_argument("--ts", required=True, help="ts.json 路径")
    ap.add_argument("--rule", required=True, help="规则编码（rules 或 init.rules）")
    ap.add_argument("--dry-run", action="store_true", help="只打印前后序不改文件")
    args = ap.parse_args()

    ts = json.loads(Path(args.ts).read_text(encoding="utf-8"))
    rule = (ts.get("rules") or {}).get(args.rule) \
        or ((ts.get("init") or {}).get("rules") or {}).get(args.rule)
    if not rule:
        print(f"错误: ts 里没有规则 {args.rule}", file=sys.stderr)
        return 2
    target = str(rule.get("target_table") or "")
    short = target.rsplit(".", 1)[-1]
    table_fields = ((ts.get("tables") or {}).get(short) or {}).get("fields") or []
    produced = rule_output_fields(rule) or None   # 空集→None=全列（与 INSERT 清单同语义）
    try:
        expect = _resolve_insert_columns(table_fields, produced)
    except ValueError as e:
        print(f"错误: 期望清单不可解析——{e}", file=sys.stderr)
        return 2

    sql_path = Path(args.sql)
    sql = sql_path.read_text(encoding="utf-8")
    new_sql, notes = reorder(sql, expect)
    old_names = [n or "（无名）" for n, _ in split_top_projection_items(sql) or []]
    new_names = [n or "（无名）" for n, _ in split_top_projection_items(new_sql) or []]
    print(f"期望序（INSERT 列清单）: {expect}")
    print(f"重排前: {old_names}")
    print(f"重排后: {new_names}")
    for n in notes:
        print(f"  ｜{n}")
    if new_sql != sql:
        if args.dry_run:
            print("dry-run：未写回")
        else:
            sql_path.write_text(new_sql, encoding="utf-8")
            print(f"已写回 {sql_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
