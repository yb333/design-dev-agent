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


def _compact_cols(cols: dict, per_line: int = 6) -> str:
    """全表字段清单紧凑化（2026-09-15 内网实证：一列一行 300 字段=300 行，bash 输出
    截断看不全，designer 被迫绕路自想办法——一行 6 个逗号分隔，300 字段≈50 行内）。"""
    items = [f"{c}:{t}" for c, t in cols.items()]
    return "\n".join("  " + ", ".join(items[i:i + per_line])
                     for i in range(0, len(items), per_line))


def _similar_names(name: str, cols: dict, top: int = 5) -> list:
    """相近字段建议（不存在时帮定位拼写差）：前缀/包含优先，其次最长公共前缀长度。"""
    n = name.lower()
    hits = [c for c in cols if n in c or c in n]
    if not hits:
        hits = sorted(cols, key=lambda c: -len(_common_prefix(n, c)))[:top]
    return sorted(hits, key=lambda c: (0 if c.startswith(n) else 1, len(c)))[:top]


def _common_prefix(a: str, b: str) -> str:
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    return a[:i]


def query_fields(ts_path, schema: str, table: str, column: str = "",
                 like: str = "") -> str:
    """查 schema_cache 里某表的字段（列全部/模糊找/确认存在性）。

    返回提示文本（不抛异常不阻断，各分支都给下一步指引）：
    - cache 不存在 → [未连库]（凭设计写，标注待连库确认）
    - 表不在缓存 → [未缓存] + 已缓存表清单（未声明的表正路是补 mapping，不是绕过）
    - like 给了 → 含关键词的字段（模糊找："日期类"→like date）
    - column 给了 + 存在 → ✓ + 类型
    - column 给了 + 不存在 → ✗ + 相近字段建议（拼写差定位）+ 紧凑全表
    - column 没给 → 全表紧凑清单（一行 6 个，防 bash 截断）
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

    if like:
        lk = like.lower()
        hits = {c: ty for c, ty in cols.items() if lk in c}
        if not hits:
            return (f"[无匹配] {full} 里没有含 '{like}' 的字段（全 {len(cols)} 个——"
                    f"换个关键词，或去掉 --like 看紧凑全表清单）")
        return (f"/* {full} 含 '{like}' 的字段（{len(hits)}/{len(cols)}）*/\n"
                + _compact_cols(hits))

    if column:
        hit = cols.get(column.lower()) or cols.get(column)
        if hit:
            return f"✓ {full}.{column} 存在，类型 {hit}"
        sims = _similar_names(column, cols)
        sim_note = f"相近字段: {', '.join(sims)}" if sims else ""
        return (f"✗ {full}.{column} 不存在。{sim_note}\n"
                f"该表全部字段（{len(cols)} 个，紧凑）:\n" + _compact_cols(cols))

    return (f"/* {full} 字段清单（{len(cols)} 个，来自 schema_cache {cached_at}；"
            f"模糊查找加 --like 关键词）*/\n" + _compact_cols(cols))


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
