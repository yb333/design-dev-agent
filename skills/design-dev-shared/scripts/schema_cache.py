"""schema_cache —— 表结构缓存设施（pg_catalog 批量查 + 24h 缓存）。

2026-09-04 从 new-pipe/precheck.py 搬体留名下沉（函数体零改动、原名保留——precheck
re-export 同名）。new-pipe precheck（步骤1b）与 opt-pipe precheck_opt 共用。
"""
from pathlib import Path

def _load_schema_cache(cache_path: Path) -> dict:
    """读表结构缓存。返回 {cached_at, tables: {schema.table: {col: type}}}。"""
    if not cache_path.exists():
        return {"cached_at": "", "tables": {}}
    try:
        import json

        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {"cached_at": "", "tables": {}}


def _save_schema_cache(cache_path: Path, cache: dict):
    """写表结构缓存。"""
    try:
        import json
        from datetime import datetime

        cache["cached_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # 缓存写失败不影响校验


def _is_cache_expired(cached_at: str, ttl_hours: int = 24) -> bool:
    """缓存是否过期。"""
    if not cached_at:
        return True
    try:
        from datetime import datetime, timedelta

        cached_time = datetime.strptime(cached_at, "%Y-%m-%dT%H:%M:%S")
        return datetime.now() - cached_time > timedelta(hours=ttl_hours)
    except Exception:
        return True


def _fetch_tables_schema_batch(
    executor, tables: list[tuple[str, str]]
) -> dict[tuple[str, str], dict[str, str]]:
    """连库批量查多张表的列名+类型（UNION ALL，实测 DWS 上最快）。

    每张表一个 UNION ALL 分支，每个分支走精确等值（n.nspname= AND c.relname=），
    优化器不用处理 OR，执行计划稳定。一次往返查完全部表。

    Args:
        executor: DB executor。
        tables: [(schema, table), ...] 待查的表。

    Returns:
        {(schema_lower, table_lower): {column_name_lower: type}}。
        表不存在/无权限 → 该表对应空 dict。
    """
    if not tables:
        return {}

    # 构造 UNION ALL：每个分支带 schema/table 标记列 + 列名 + 类型
    # format_type 输出归一化类型（如 "character varying(64)"、"bigint"）
    branches = []
    for (sch, tbl) in tables:
        branches.append(
            f"SELECT '{sch.lower()}' AS nsp, '{tbl.lower()}' AS rel, "
            "a.attname AS col, format_type(a.atttypid, a.atttypmod) AS col_type "
            "FROM pg_attribute a "
            "JOIN pg_class c ON a.attrelid = c.oid "
            "JOIN pg_namespace n ON c.relnamespace = n.oid "
            f"WHERE n.nspname = '{sch.lower()}' AND c.relname = '{tbl.lower()}' "
            "AND a.attnum > 0 AND NOT a.attisdropped"
        )
    sql = "\nUNION ALL\n".join(branches)

    r = executor.execute(sql)
    result: dict[tuple[str, str], dict[str, str]] = {}
    # 初始化所有表为空 dict（表不存在/查询失败时保留空 dict）
    for (sch, tbl) in tables:
        result[(sch.lower(), tbl.lower())] = {}

    if r.success and r.rows:
        for row in r.rows:
            key = (row["nsp"].lower(), row["rel"].lower())
            result.setdefault(key, {})[row["col"].lower()] = (row["col_type"] or "").lower()
    return result


def _normalize_type(raw: str) -> str:
    """类型名归一化（识别同义异名，用于严格对比）。

    目的：把"同一类型的不同写法"归一到相同名字，避免方言/别名差异导致误报。

    整数类型（(n) 位宽优先）：
    - int8(64) / bigint / int(64) 都归一 "bigint"（64bit=8字节）
    - int4(32) / integer / int / int(32) 都归一 "integer"（32bit=4字节）
    - int2(16) / smallint 都归一 "smallint"（16bit=2字节）
    - 有 (n) 时 n（bit 数）决定精度；无 (n) 时 base name 决定

    其他类型：varchar/character varying 归一（PG 官方别名，确定同义，都字符语义）；
    char/character、numeric/decimal、bool/boolean 同理。
    varchar2/nvarchar2 不归一（字节/字符语义不同，归一会漏判长度超长）。

    与 type_compat.is_type_compatible 不同：那个判"兼容"（源能否被目标兜底），
    这个判"同名"（mapping 标的 source_type 和库 actual_type 该是同一类型）。

    时间类型家族（with/without time zone 底层存储不同，分开归一）：
    - timestamp / timestamp(n) / without time zone → 统一 ts_notz（忽略精度）
    - timestamptz / timestamp(n) with time zone     → 统一 ts_tz（忽略精度）
    """
    import re
    t = raw.strip().lower().replace(" ", "")
    if not t:
        return ""

    # 时间类型族：先判 with/without time zone（底层不同，不归一），再忽略精度
    if "timestamp" in t:
        is_tz = "withtimezone" in t or t.startswith("timestamptz")
        return "ts_tz" if is_tz else "ts_notz"

    base = t.split("(")[0]
    # 提取 (n) 第一个数字（整数类是 bit 数，字符/数值类是长度/精度）
    m = re.search(r"\((\d+)", t)
    n_first = int(m.group(1)) if m else None

    # 整数类：(n) bit 数优先决定精度等级，其次 base name
    # int8/int4/int2 是 PG 内部名（pg_type），bigint/integer/smallint 是 SQL 标准名，二者等价
    INT_BASE_TO_NAME = {
        "bigint": "bigint", "int8": "bigint", "bigserial": "bigint",
        "integer": "integer", "int": "integer", "int4": "integer", "serial": "integer",
        "smallint": "smallint", "int2": "smallint", "smallserial": "smallint",
        "tinyint": "tinyint", "int1": "tinyint",
    }
    INT_BIT_TO_NAME = {64: "bigint", 32: "integer", 16: "smallint", 8: "tinyint"}
    if base in INT_BASE_TO_NAME:
        if n_first is not None and n_first in INT_BIT_TO_NAME:
            return INT_BIT_TO_NAME[n_first]  # (n) 位宽优先
        return INT_BASE_TO_NAME[base]  # 无 (n) 或 n 非标准位宽 → base name 决定

    # 其他类型：归一别名 + 保留长度/精度后缀
    # 注意：varchar2/nvarchar2 不归一到 varchar——长度语义不同（varchar2 按字节，
    # varchar 在 PG 模式按字符；nvarchar2 按字符但是国家字符集），归一会漏判长度超长
    rest = "(" + t.split("(", 1)[1] if "(" in t else ""
    aliases = {
        "varchar": "charactervarying",
        "char": "character",
        "string": "text",
        "bool": "boolean",
        "decimal": "numeric",
    }
    return aliases.get(base, base) + rest

