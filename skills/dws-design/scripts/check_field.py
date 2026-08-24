#!/usr/bin/env python3
"""
designer 的字段查证工具——写 design_logic / 关联条件引用 mapping 外字段前，先查实。

抄你正要写的引用（别名.字段）直接查，别名自动解析成表：

  python skills/dws-design/scripts/check_field.py \
      --rs 10_project_deliver/{资产}/ddlc_design_dev/_internal/rs_input.json \
      --field ht.start_date        # 查证单字段（写假设字段前先跑这个）

  ... --field ht                  # 只给别名 = 列该表全部字段

内核调 design-dev-shared 的 schema_query（读 precheck 产的 schema_cache，只读缓存
不连库，秒级）。字段不存在时给相似字段建议（前缀/包含模糊匹配）——SCD2 惯例假设的
start_date 这类，先查再写，别让组装校验拦你。
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from schema_query import lookup_table


def _similar_fields(name: str, cols: dict, limit: int = 5) -> list[str]:
    """相似字段建议：前缀 / 包含 / 共享长片段（start_date → start_dt / eff_date）。"""
    n = name.lower()
    scored = []
    for c in cols:
        cl = c.lower()
        if cl.startswith(n[:4]) or n[:4] in cl or cl in n or n in cl:
            scored.append(c)
    return sorted(scored)[:limit]


def check_field(rs_path: Path, ref: str) -> str:
    """查证 别名.字段 引用（或 别名=列全表）。返回提示文本。"""
    try:
        rs = json.loads(Path(rs_path).read_text(encoding="utf-8"))
    except Exception as e:
        return f"[错误] rs_input 读取失败（{rs_path}）: {e}"

    alias, _, col = ref.partition(".")
    alias_l = alias.strip().lower()
    st = next((s for s in rs.get("source_tables") or []
               if (s.get("source_alias") or "").strip().lower() == alias_l), None)
    if not st:
        available = sorted({(s.get("source_alias") or "?") for s in rs.get("source_tables") or []})
        return (f"[别名未识别] rs_input 里没有别名 '{alias}'。可用别名: {available}\n"
                f"——引用的表没进 mapping？正路是补 mapping（闸口①确认），不是绕过")
    schema = (st.get("source_schema") or "").strip()
    table = (st.get("source_table") or "").strip()
    status, cols = lookup_table(rs_path, schema, table)
    full = f"{schema}.{table}"
    if status == "no_cache":
        return (f"[未连库] schema_cache 不存在——无法查证 {full}，凭设计写并标注待连库确认；"
                f"或让 precheck 连库后再查")
    if status == "not_cached":
        return (f"[未缓存] {full} 不在 schema_cache（连库时没查到这张表——检查表名/权限）")
    if not col.strip():
        lines = [f"  {c:32s} {t}" for c, t in list(cols.items())[:30]]
        return f"{full}（别名 {alias}）共 {len(cols)} 字段:\n" + "\n".join(lines) + \
               ("\n  ..." if len(cols) > 30 else "")
    hit = cols.get(col.strip().lower()) or cols.get(col.strip())
    if hit:
        return f"✓ {alias}.{col} 存在（{full}.{col}，类型 {hit}）——放心引用"
    sug = _similar_fields(col, cols)
    sug_txt = f"相似字段: {sug}（是不是要这个？）" if sug else ""
    return (f"✗ {alias}.{col} 不存在（{full} 里没有）。{sug_txt}\n"
            f"——别按惯例猜字段名：查 mapping 原文/问源端；确认该字段真有 → 补 mapping，"
            f"是逻辑字段 → design_logic 写清产生逻辑")


def main():
    parser = argparse.ArgumentParser(
        description="designer 字段查证：抄正要写的 别名.字段 引用直接查 schema_cache")
    parser.add_argument("--rs", required=True, help="rs_input.json 路径（定位 schema_cache）")
    parser.add_argument("--field", required=True,
                        help='要查证的引用："别名.字段"（如 ht.start_date）或只 "别名"（列全表）')
    args = parser.parse_args()
    print(check_field(Path(args.rs), args.field))


if __name__ == "__main__":
    main()
