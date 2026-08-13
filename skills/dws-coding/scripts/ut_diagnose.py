#!/usr/bin/env python3
"""
UT 类型转换失败自动诊断（函数库 + CLI）。

定位"INSERT 报 invalid input syntax for type numeric/date"类错误的嫌疑字段：
报错现场连着库、上下文最全（知道哪条规则、哪步、什么报错），确定性探测无语义判断。
分析（源脏 / 设计缺 cast / 业务一对多）留给 designer/coder。

先例：run_ut_check 主键重复时 LIMIT 5 捕获重复键样例——同一模式扩展到 INSERT 报错。

核心：diagnose_type_error(executor, rule, ts, cache_path)
  读规则字段（ts.tables[target].fields）+ schema_cache（源表实际类型）→
  用 type_compat.parse_type_info 的 family 大类圈出跨类型字段（源 varchar→目标 numeric 等）→
  逐个对**源表**定向探测脏值（count + LIMIT 3 样例）。

边界：只覆盖高价值类型转换（字符→数值、字符→日期）；其他 family 不探测。
探测只读源表（etl 账号），单表 count/LIMIT 不会发散。
schema_cache 不存在 → 跳过诊断（提示"未连库无缓存"）。

CLI（服务型，designer/coder 回退分析可自行复跑）:
  python ut_diagnose.py --ts ts.json --rule R0001
"""

import sys
import json
import argparse
from pathlib import Path

# dws_db / type_compat 在 design-dev-shared + dws-design（与本 skill 平级）
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent.parent / "design-dev-shared" / "scripts"))
sys.path.insert(0, str(_HERE))  # run_ut 同目录（CLI 复用连库）
sys.path.insert(0, str(_HERE.parent.parent.parent / "dws-design" / "scripts"))
from type_compat import parse_type_info


# 跨类型探测的"合法值"正则（脏值 = 不匹配）。只覆盖字符→数值、字符→日期两类高价值场景。
# 数值：可选符号 + 整数或小数（1,000 这种带千分位的算脏——PG numeric 不接受）
_NUMERIC_OK = r"^[+-]?[0-9]+(\.[0-9]+)?$"
# 日期：YYYYMMDD / YYYY-MM-DD / YYYY/MM/DD（覆盖 RS 常见业务日期格式）
_DATE_OK = r"^[0-9]{4}[-/]?[0-9]{2}[-/]?[0-9]{2}"


def _dirty_pattern(target_family: str) -> str | None:
    """按目标 family 返回'合法值'正则（脏值=不匹配）。非高价值 family 返回 None（不探测）。"""
    if target_family in ("numeric", "integer"):
        return _NUMERIC_OK
    if target_family == "datetime":
        return _DATE_OK
    return None


def _load_schema_cache(cache_path: Path) -> dict:
    """读 schema_cache.json → {schema.table.lower: {col.lower: type}}。不存在返回空。"""
    if not cache_path.exists():
        return {}
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    tables = raw.get("tables", {}) if isinstance(raw, dict) else {}
    out = {}
    for key, cols in tables.items():
        if isinstance(cols, dict):
            out[key.lower()] = {k.lower(): (v or "") for k, v in cols.items()}
        elif isinstance(cols, list):
            out[key.lower()] = {c.lower(): "" for c in cols}
    return out


def _target_short(target_table: str) -> str:
    """dws.dwb_order_f → dwb_order_f。"""
    return target_table.rsplit(".", 1)[-1] if "." in target_table else target_table


def _collect_cross_type_fields(rule: dict, ts: dict, cache: dict) -> list[dict]:
    """圈出跨类型嫌疑字段（源 varchar→目标 numeric/date，从 ts+cache 已知类型）。

    返回 [{target_field, target_type, target_family, schema, table, source_column, source_type}]。
    只收 schema_cache 能查到源类型的字段（查不到无法判，跳过）。
    """
    target_table = rule.get("target_table", "")
    t_short = _target_short(target_table)
    fields = ts.get("tables", {}).get(t_short, {}).get("fields", []) or rule.get("fields", [])

    # 源表 table→schema 映射（rule.source_tables 有 schema）
    src_map = {}
    for st in rule.get("source_tables", []):
        tbl = (st.get("table") or "").strip()
        if tbl:
            src_map[tbl.lower()] = (st.get("schema") or "").strip()

    candidates = []
    for f in fields:
        target_field = f.get("target_field", "")
        target_type = f.get("field_type", "") or f.get("target_type", "")
        if not target_field or not target_type:
            continue
        tgt_family = parse_type_info(target_type).get("family", "unknown")
        pattern = _dirty_pattern(tgt_family)
        if pattern is None:
            continue  # 非高价值 family，不探测
        # 取第一个源字段（多源字段取主源即可，足够定位脏数据）
        src_fields = f.get("source_fields") or []
        if not src_fields:
            continue
        sf = src_fields[0]
        src_col = (sf.get("field") or "").strip()
        src_tbl = (sf.get("table") or "").strip()
        if not src_col or not src_tbl:
            continue
        schema = src_map.get(src_tbl.lower(), "")
        if not schema:
            continue
        cache_key = f"{schema.lower()}.{src_tbl.lower()}"
        cols = cache.get(cache_key)
        if not cols:
            continue  # 源表不在缓存，无法判源类型，跳过
        source_type = cols.get(src_col.lower(), "")
        if not source_type:
            continue
        src_family = parse_type_info(source_type).get("family", "unknown")
        # 跨大类才探测（同 family 不存在"脏值导致转换失败"，是长度问题，不归本工具）
        if src_family == tgt_family:
            continue
        candidates.append({
            "target_field": target_field,
            "target_type": target_type,
            "target_family": tgt_family,
            "schema": schema,
            "table": src_tbl,
            "source_column": src_col,
            "source_type": source_type,
        })
    return candidates


def _probe_dirty(executor, schema: str, table: str, column: str,
                 pattern: str) -> dict:
    """对源表单列探测脏值（不匹配 pattern 的非空值）：count + LIMIT 3 样例。

    探测只读源表，count/LIMIT 不发散。任何异常都兜底为"探测失败"（绝不抛出影响主流程）。
    """
    full = f"{schema}.{table}"
    # col::text 防 numeric 源列被当文本正则匹配出错（这里源已是 varchar-family，双保险）
    cond = f"{column} IS NOT NULL AND {column}::text !~ '{pattern}'"
    result = {"dirty_count": None, "samples": []}
    try:
        r1 = executor.execute(f"SELECT count(*) AS cnt FROM {full} WHERE {cond}")
        if r1.success and r1.rows:
            result["dirty_count"] = r1.rows[0].get("cnt")
        r2 = executor.execute(f"SELECT {column} AS val FROM {full} WHERE {cond} LIMIT 3")
        if r2.success and r2.rows:
            result["samples"] = [str(row.get("val", "")) for row in r2.rows]
    except Exception:
        pass
    return result


def diagnose_type_error(executor, rule: dict, ts: dict, cache_path: Path) -> list[dict]:
    """诊断类型转换失败的嫌疑字段（脏数据定位）。

    流程：ts.tables[target].fields + schema_cache 圈跨类型字段 → 逐个探测源表脏值。
    返回诊断条目列表，每条含：
      target_field / target_type / source(schema.table.column) / source_type /
      dirty_count / samples
    cache 不存在 → 返回空 + 置 __no_cache 标志（调用方据此提示"未连库无缓存"）。

    设计为增益不是依赖：探测异常/查不到一律跳过，绝不抛出。
    """
    cache_path = Path(cache_path)
    if not cache_path.exists():
        return [{"__no_cache": True}]

    cache = _load_schema_cache(cache_path)
    if not cache:
        return [{"__no_cache": True}]

    candidates = _collect_cross_type_fields(rule, ts, cache)
    entries = []
    for c in candidates:
        pattern = _dirty_pattern(c["target_family"])
        probe = _probe_dirty(executor, c["schema"], c["table"], c["source_column"], pattern)
        # 只有真有脏数据（count>0）或探测有样例时才报（避免"全干净"噪音）
        if probe["dirty_count"] and probe["dirty_count"] > 0:
            entries.append({
                "target_field": c["target_field"],
                "target_type": c["target_type"],
                "source": f"{c['schema']}.{c['table']}.{c['source_column']}",
                "source_type": c["source_type"],
                "dirty_count": probe["dirty_count"],
                "samples": probe["samples"],
            })
    return entries


def format_diagnosis(entries: list[dict]) -> str:
    """把诊断条目渲染成人读文本（贴进 UT 报告的 FAIL detail 下'诊断'段）。

    格式：字段 X 有 128 行脏数据，样例：'N/A'、'-'、'1,000'
    无诊断 / 无缓存 → 对应诚实提示。
    """
    # 无缓存（未连库）：诚实提示
    if entries and all(e.get("__no_cache") for e in entries):
        return "自动诊断：未连库无 schema_cache，无法定位嫌疑字段（附原始报错请人排查）"
    # 过滤掉诊断出但无脏数据的空结果
    real = [e for e in entries if not e.get("__no_cache")]
    if not real:
        return "自动诊断：未识别到嫌疑字段（schema_cache 无对应源类型，或无跨类型字段）"

    lines = ["自动诊断（类型转换类报错，圈定嫌疑字段+脏数据样例）："]
    for e in real:
        samples = "、".join(f"'{s}'" for s in e.get("samples", [])[:3]) or "（未抓到样例）"
        lines.append(
            f"- 字段 {e['target_field']}（目标 {e['target_type']}，"
            f"源 {e['source']} {e['source_type']}）"
            f"有 {e['dirty_count']} 行脏数据，样例：{samples}"
        )
    lines.append("（根因判断：源脏 → 清源；设计缺 cast → designer/coder 加转换；其他 → 人排查）")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="UT 类型转换失败诊断（服务型，designer/coder 回退分析可复跑）")
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--rule", required=True, help="规则号（如 R0001）")
    parser.add_argument("--db-config", default="", help="db-sources.json 路径")
    parser.add_argument("--source", default="", help="数据源名")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    # init 规则（INIT_ 前缀）在 ts.init.rules；否则 ts.rules
    rule_code = args.rule
    rules = ts.get("rules", {})
    rule = rules.get(rule_code)
    if rule is None:
        init_rules = (ts.get("init") or {}).get("rules") or {}
        rule = init_rules.get(rule_code)
    if rule is None:
        print(f"错误: 规则 {rule_code} 在 ts.json 中不存在", file=sys.stderr)
        sys.exit(2)

    # 连库（etl 只读源表）
    from dws_db import create_executor, resolve_source_by_schema
    from config_paths import db_sources_path
    target_schema = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", "")
    source = args.source
    if not source and target_schema:
        config_path = args.db_config or str(db_sources_path())
        source = resolve_source_by_schema(config_path, target_schema)
    executor = create_executor(args.db_config, source, role="etl")

    cache_path = ts_path.parent / "_internal" / "schema_cache.json"
    entries = diagnose_type_error(executor, rule, ts, cache_path)
    print(format_diagnosis(entries))
    executor.close()


if __name__ == "__main__":
    main()
