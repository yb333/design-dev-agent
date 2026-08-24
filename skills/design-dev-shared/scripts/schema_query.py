#!/usr/bin/env python3
"""schema_cache 字段查询器：查"表里有没有某字段"（只读缓存，不连库）。

★ 定位：公共能力（designer 设计 / coder 编码都要确认"mapping 外字段"的存在性）。
  数据源是 precheck 连库时产出的 schema_cache.json（rs_input 声明过的源表全字段缓存）。
  与 explore.py 互补：explore 连库试算（JOIN 键唯一性），本工具只查缓存（字段存在性）。

用法（designer 写 design_logic 引用 mapping 未列的字段前 / coder 不确定时兜底）:
  python schema_query.py --ts {deliver}/_internal/rs_input.json --table ods.ods_b                # 设计阶段（ts 未产出，锚点传 rs_input）
  python schema_query.py --ts {deliver}/ts.json --table ods.ods_b --column col2                  # 编码阶段兜底

--ts 是定位锚点：只用于推算同级 _internal/schema_cache.json（precheck 连库时产出），
锚点文件本身不要求存在（设计阶段 ts.json 还没产出是常态）。

退出码: 0=总是（查询结果在 stdout，查不到也是提示不阻断）；2=参数错误
"""

import sys
import json
import argparse
from pathlib import Path


def query_fields(ts_path, schema: str, table: str, column: str = "") -> str:
    """查 schema_cache 里某表的字段（列全部，或确认某字段存在性）。

    返回提示文本（不抛异常不阻断，各分支都给下一步指引）：
    - cache 不存在 → [未连库]（凭设计写，标注待连库确认）
    - 表不在缓存 → [未缓存] + 已缓存表清单（未声明的表正路是补 mapping，不是绕过）
    - column 给了 + 存在 → ✓ + 类型
    - column 给了 + 不存在 → ✗ + 全表字段帮对照
    - column 没给 → 全表字段清单（名 + 类型）
    """
    ts_path = Path(ts_path)
    # cache 两个候选位置：锚点在 deliver 根（ts.json / rs_input 在根的形态）→ 同级 _internal/；
    # 锚点在 _internal/ 里（rs_input.json）→ cache 与它同级，直接找
    cache_path = ts_path.parent / "_internal" / "schema_cache.json"
    if not cache_path.exists() and (ts_path.parent / "schema_cache.json").exists():
        cache_path = ts_path.parent / "schema_cache.json"
    full = f"{schema}.{table}"
    if not cache_path.exists():
        return (f"[未连库] schema_cache.json 不存在（{cache_path}）。\n"
                f"无法确认 {full} 的字段存在性，凭设计写，标注待连库确认。")
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"[错误] schema_cache.json 读取失败: {e}"

    tables_map = cache.get("tables", {})
    cached_at = cache.get("cached_at", "")
    cols = tables_map.get(full.lower())
    if not cols:
        return (f"[未缓存] {full} 不在 schema_cache 里（连库时没查这张表，"
                f"可能是 rs_input 未声明的来源——正路是补 mapping，不是绕过校验）。\n"
                f"已缓存的表: {', '.join(sorted(tables_map.keys())[:10])}")

    if column:
        hit = cols.get(column.lower()) or cols.get(column)
        if hit:
            return f"✓ {full}.{column} 存在，类型 {hit}"
        fld_preview = "\n".join(f"  {c:30s} {t}" for c, t in list(cols.items())[:20])
        return (f"✗ {full}.{column} 不存在。该表字段（帮对照）:\n{fld_preview}"
                + ("\n  ..." if len(cols) > 20 else ""))

    lines = [f"/* {full} 字段清单（来自 schema_cache，连库时间: {cached_at}）*/"]
    for col, ctype in cols.items():
        lines.append(f"  {col:30s} {ctype}")
    lines.append("")
    lines.append(f"/* 共 {len(cols)} 个字段 */")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="schema_cache 字段查询器（只读缓存不连库；designer/coder 公共）")
    parser.add_argument("--ts", required=True,
                        help="定位锚点：rs_input.json（设计阶段）或 ts.json（编码阶段）路径，"
                             "用于推算同级 _internal/schema_cache.json（锚点本身不要求存在）")
    parser.add_argument("--table", required=True, help="表名（schema.table，如 ods.ods_b）")
    parser.add_argument("--column", default="", help="可选：确认某字段存在性（不给则列全表字段）")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    # 锚点文件不要求存在（设计阶段 ts.json 未产出是常态），query_fields 里
    # 会按锚点定位 cache 并对"cache 不存在"给出提示
    if "." not in args.table:
        print("错误: --table 需 schema.table 形式（如 ods.ods_b）", file=sys.stderr)
        sys.exit(2)
    schema, table = args.table.split(".", 1)
    print(query_fields(ts_path, schema, table, args.column))


if __name__ == "__main__":
    main()


def lookup_table(ts_path, schema: str, table: str):
    """结构化查询：返回 (status, cols)。

    status: "ok"（cols={字段:类型}）/ "no_cache" / "not_cached"（cols=None）。
    给 check_field / pick_fields 这类角色定制入口组合自己的文案用（query_fields
    是整段文案的便捷版，本函数是裸数据版）。
    """
    ts_path = Path(ts_path)
    cache_path = ts_path.parent / "_internal" / "schema_cache.json"
    if not cache_path.exists() and (ts_path.parent / "schema_cache.json").exists():
        cache_path = ts_path.parent / "schema_cache.json"
    if not cache_path.exists():
        return "no_cache", None
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return "no_cache", None
    cols = (cache.get("tables") or {}).get(f"{schema}.{table}".lower())
    if not cols:
        return "not_cached", None
    return "ok", cols
