#!/usr/bin/env python3
"""
输入预检: 校验 rs_input.json 的完整性。

独立于 preprocess.py（只做转换），本脚本只做校验。
用户修改 mapping.xlsx 或 RS.md 后，重新跑 preprocess 转换，再跑本脚本校验。

用法:
    python precheck.py --input rs_input.json
    python precheck.py --input rs_input.json --output precheck_report.md
"""

import sys
import argparse
from typing import Any
from pathlib import Path


class PrecheckResult:
    def __init__(self):
        self.passed: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []

    @property
    def return_code(self) -> int:
        if self.errors:
            return 2  # INCOMPLETE
        if self.warnings:
            return 1  # WARNING
        return 0  # PASS

    def add_pass(self, msg: str):
        self.passed.append(msg)

    def add_warn(self, msg: str):
        self.warnings.append(msg)

    def add_error(self, msg: str):
        self.errors.append(msg)

    def summary(self) -> str:
        lines = [
            f"预检结果: {'PASS' if self.return_code == 0 else 'WARNING' if self.return_code == 1 else 'INCOMPLETE'}",
            f"  通过: {len(self.passed)}  警告: {len(self.warnings)}  错误: {len(self.errors)}",
        ]
        if self.warnings:
            lines.append("警告:")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
        if self.errors:
            lines.append("错误:")
            for e in self.errors:
                lines.append(f"  ✗ {e}")
        return "\n".join(lines)


# 合法的映射规则类型
VALID_RULES = {"直接复制", "数据加工", "赋值", "序列"}


def precheck(
    rs_input: dict[str, Any],
    cache_path: Path | None = None,
    refresh_schema: bool = False,
) -> PrecheckResult:
    """预检 rs_input.json 完整性。

    Args:
        rs_input: rs_input.json 的 dict。
        cache_path: 表结构缓存路径（schema_cache.json），None 则不缓存。
        refresh_schema: 强制连库刷新缓存（忽略过期判断）。
    """
    result = PrecheckResult()

    # 1. 目标表基本信息
    target = rs_input.get("meta", {}).get("target", {})
    # rs_input 的 target 结构是 {f_table: {schema, table, cn}, i_view: {schema, table, cn}}
    f_table = target.get("f_table", {})
    target_schema = f_table.get("schema", "")
    target_table = f_table.get("table", "")
    if not target_schema or not target_table:
        result.add_error("目标表 schema/table 缺失")
    else:
        result.add_pass(f"目标表: {target_schema}.{target_table}")

    # 2. 源表
    source_tables = rs_input.get("source_tables", [])
    if not source_tables:
        result.add_error("无源表 (source_tables 为空)")
    else:
        result.add_pass(f"源表数: {len(source_tables)}")
        for st in source_tables:
            if not st.get("source_alias"):
                result.add_warn(f"源表 {st.get('source_table', '?')} 缺少别名 (source_alias)")

    # 3. 字段映射 (含映射规则交叉校验)
    field_mappings = rs_input.get("field_mappings", [])
    if not field_mappings:
        result.add_error("无字段映射 (field_mappings 为空)")
    else:
        result.add_pass(f"字段映射数: {len(field_mappings)}")

        for fm in field_mappings:
            target_field = fm.get("target_column", "")
            if not target_field:
                result.add_error("存在无目标字段名的映射行")
                continue

            rule = (fm.get("transform_rule") or fm.get("mapping_rule") or "").strip()
            expr = (fm.get("transform_detail") or fm.get("mapping_expression") or "").strip()
            source_field = (fm.get("source_column") or "").strip()

            # 3a. 映射规则必须有值且合法
            if not rule:
                result.add_error(f"字段 {target_field} 缺少映射规则")
                continue
            if rule not in VALID_RULES:
                result.add_error(f"字段 {target_field} 的映射规则 '{rule}' 不合法 (应为: 直接复制/数据加工/赋值/序列)")
                continue

            # 3b. 交叉校验
            if rule == "直接复制":
                if expr and expr != "-":
                    result.add_warn(f"字段 {target_field} 是'直接复制'但填了映射表达式 '{expr[:30]}', 若有加工逻辑应改为'数据加工'")
                if not source_field:
                    result.add_error(f"字段 {target_field} 是'直接复制'但缺少来源字段 (source_column)")
            elif rule == "数据加工":
                if not expr or expr == "-":
                    result.add_error(f"字段 {target_field} 是'数据加工'但映射表达式为空 (必须描述加工逻辑)")
                if not source_field:
                    result.add_warn(f"字段 {target_field} 是'数据加工'但没有来源字段, 确认是否为纯派生字段")
            elif rule == "赋值":
                if not expr or expr == "-":
                    result.add_error(f"字段 {target_field} 是'赋值'但映射表达式为空 (必须说明赋什么值)")
            elif rule == "序列":
                result.add_pass(f"字段 {target_field} 是'序列'类型 (自增序列, 特殊处理)")

    # 4. 目标字段重复检查
    seen_fields: dict[str, int] = {}
    for fm in field_mappings:
        tf = fm.get("target_column", "")
        if tf:
            seen_fields[tf] = seen_fields.get(tf, 0) + 1
    for field, count in seen_fields.items():
        if count > 1:
            result.add_error(f"目标字段 '{field}' 重复出现 {count} 次")

    # 5. 调度信息 (来自 RS)
    schedule = rs_input.get("schedule", {})
    if not schedule.get("frequency"):
        result.add_warn("调度频率缺失 (RS L07 调度频率)")
    if not schedule.get("upstream"):
        result.add_warn("上游调度任务缺失 (RS L07 湖表调度信息)")

    # 6. 别名一致性
    entity_aliases = {st.get("source_alias") for st in source_tables if st.get("source_alias")}
    for fm in field_mappings:
        fm_alias = fm.get("source_alias", "")
        if fm_alias and fm_alias not in entity_aliases:
            result.add_error(f"字段 {fm.get('target_column', '?')} 的来源别名 '{fm_alias}' 在实体级 mapping 中不存在")

    # 7. 映射表达式模糊术语检查
    biz_terms = ["等等", "之类", "相关", "之类的", "等等等"]
    for fm in field_mappings:
        expr = fm.get("transform_detail") or fm.get("mapping_expression") or ""
        for term in biz_terms:
            if term in str(expr):
                result.add_warn(f"字段 {fm.get('target_column', '?')} 的映射表达式含模糊术语: '{term}'")

    # 8. 审计字段校验
    _check_audit_fields(field_mappings, result)

    # 9. DB 校验：连得上库或缓存可用时，校验来源表/字段真实性（连不上则静默跳过）
    # ★ 短路：静态检查已有 error 就不进 DB 校验（schema/字段都没了，查库白费几百毫秒建连）
    # 缓存命中时不需要连库，不受"连库白费"影响，但仍遵守短路（静态错了先解决静态）
    if not result.errors:
        _check_db_schema(rs_input, result, cache_path, refresh_schema)

    return result


# 标准审计字段（4个固定字段）
STANDARD_AUDIT_FIELDS = ["del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"]


def _is_audit_field(fm: dict) -> bool:
    """判断一个字段是否审计字段：备注优先（含'审计字段'），字段名兜底（匹配标准名）。"""
    remark = (fm.get("remark") or "").strip()
    if "审计字段" in remark:
        return True
    target = (fm.get("target_column") or "").strip().lower()
    return target in STANDARD_AUDIT_FIELDS


def _check_audit_fields(field_mappings: list, result: PrecheckResult):
    """审计字段校验：来源提供了则校验规范性，没提供则警告。"""
    audit_fields = [fm for fm in field_mappings if _is_audit_field(fm)]

    if not audit_fields:
        result.add_warn(
            "RS/mapping 未提供审计字段，将由 assemble_ts.py 自动补充 4 个标准审计字段"
            f"（{'、'.join(STANDARD_AUDIT_FIELDS)}）"
        )
        return

    result.add_pass(f"审计字段: mapping 提供了 {len(audit_fields)} 个")

    # 校验数量（标准是 4 个）
    if len(audit_fields) < 4:
        missing = set(STANDARD_AUDIT_FIELDS) - {
            (fm.get("target_column") or "").lower() for fm in audit_fields
        }
        result.add_warn(
            f"审计字段数量不足 ({len(audit_fields)}/4)，缺少: {'、'.join(sorted(missing))}"
            f"，缺失的将由 assemble 自动补充"
        )

    # 逐个校验规范性
    for fm in audit_fields:
        target = fm.get("target_column", "")
        target_lower = target.lower()
        rule = (fm.get("transform_rule") or fm.get("mapping_rule") or "").strip()
        expr = (fm.get("transform_detail") or fm.get("mapping_expression") or "").strip()
        target_type = (fm.get("target_type") or "").strip().lower()

        if target_lower == "del_flag":
            # del_flag 可以有逻辑：赋值（固定值）、直接复制（取源字段）、
            # 数据加工（多表整合判断，如 IF(status='已作废','Y','N')）—— 都是合理的
            pass  # 不限制映射规则类型
        else:
            # 其他三个审计字段应是标准赋值
            if rule and rule not in ("赋值", "直接复制"):
                result.add_warn(
                    f"审计字段 {target} 的映射规则是 '{rule}'，"
                    f"标准审计字段应是赋值（固定值），请确认"
                )


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


def _fetch_table_schema(executor, schema: str, table: str) -> set[str]:
    """连库查单张表的全部列名（pg_catalog，走索引，逐表查不做 OR 拼接）。

    返回 {column_name_lower}，表不存在/无权限返回空集。
    """
    sql = (
        "SELECT a.attname AS column_name "
        "FROM pg_attribute a "
        "JOIN pg_class c ON a.attrelid = c.oid "
        "JOIN pg_namespace n ON c.relnamespace = n.oid "
        f"WHERE n.nspname = '{schema.lower()}' AND c.relname = '{table.lower()}' "
        "AND a.attnum > 0 AND NOT a.attisdropped"
    )
    r = executor.execute(sql)
    if not r.success or not r.rows:
        return set()
    return {row["column_name"].lower() for row in r.rows}


def _check_db_schema(
    rs_input: dict[str, Any],
    result: PrecheckResult,
    cache_path: Path | None = None,
    refresh_schema: bool = False,
):
    """DB 校验：连得上库时，校验来源表/字段在库里的真实性。

    表结构本地缓存优先（schema_cache.json）：命中且未过期 → 纯本地对比秒级；
    缺失/过期/强制刷新 → 只连库捞缺失的表，逐表查（走索引），追加缓存。

    能连上库或缓存可用 → 表/字段不存在报 error（阻断设计）。
    连不上库且无缓存 → 静默跳过（不阻断）。

    账号选用逻辑与 UT 一致：按目标 schema 查 schema_mapping 选源。
    """
    # 从 field_mappings 收集"要用到的来源字段"：{(schema, table): {column: target_field}}
    # 跳过纯派生行（赋值/序列、source_column 空）和审计字段——这些不查源表
    field_mappings = rs_input.get("field_mappings", [])
    # {(schema, table): {source_column_lower: (原source_column, target_field)}}
    needed: dict[tuple[str, str], dict[str, tuple[str, str]]] = {}
    for fm in field_mappings:
        source_column = (fm.get("source_column") or "").strip()
        if not source_column:
            continue
        if _is_audit_field(fm):
            continue
        schema = (fm.get("source_schema") or "").strip()
        table = (fm.get("source_table") or "").strip()
        if not schema or not table:
            continue
        needed.setdefault((schema, table), {})[source_column.lower()] = (
            source_column, fm.get("target_column", "?")
        )

    if not needed:
        return

    total_fields = sum(len(cols) for cols in needed.values())

    # ── 读缓存 ──
    cache: dict = {"cached_at": "", "tables": {}}
    cache_tables: dict[str, set[str]] = {}  # {"schema.table": {cols}}
    if cache_path and not refresh_schema:
        cache = _load_schema_cache(cache_path)
        expired = _is_cache_expired(cache.get("cached_at", ""))
        raw_tables = cache.get("tables", {})
        for full_name, cols in raw_tables.items():
            cache_tables[full_name] = {c.lower() for c in cols}
        # 缓存全量过期则视为空（全都要重捞）
        if expired:
            cache_tables = {}

    # 区分缓存命中 vs 需连库捞的
    tables_to_fetch: list[tuple[str, str]] = []
    found: dict[tuple[str, str], set[str]] = {}
    for (sch, tbl) in needed:
        key = f"{sch.lower()}.{tbl.lower()}"
        if key in cache_tables:
            found[(sch.lower(), tbl.lower())] = cache_tables[key]
        else:
            tables_to_fetch.append((sch, tbl))

    cache_hits = len(needed) - len(tables_to_fetch)

    # ── 缓存未命中的表才连库 ──
    if tables_to_fetch:
        target = rs_input.get("meta", {}).get("target", {})
        target_schema = target.get("f_table", {}).get("schema", "") or target.get("schema", "")
        try:
            sys.path.insert(
                0,
                str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "references"),
            )
            from dws_db import create_executor_for_schema

            executor = create_executor_for_schema(target_schema)
            if not executor.test_connection():
                # 连不上但有缓存命中 → 用缓存结果；无缓存命中 → 跳过
                if cache_hits == 0:
                    return
            else:
                # 逐表查（每表一条 SQL，走精确索引，不做 OR 拼接）
                for (sch, tbl) in tables_to_fetch:
                    cols = _fetch_table_schema(executor, sch, tbl)
                    found[(sch.lower(), tbl.lower())] = cols
                    # 追加到缓存
                    cache.setdefault("tables", {})[f"{sch.lower()}.{tbl.lower()}"] = sorted(cols)
                executor.close()
                # 写回缓存
                if cache_path:
                    _save_schema_cache(cache_path, cache)
        except Exception:
            # 连不上库：有缓存命中就用缓存，无则跳过
            if cache_hits == 0:
                return

    # ── 比对（纯本地，秒级）──
    fetch_n = len(tables_to_fetch)
    hit_n = cache_hits
    result.add_pass(
        f"DB 校验: 校验 {len(needed)} 张表 / {total_fields} 个字段"
        f"（缓存命中 {hit_n}，连库刷新 {fetch_n}）"
    )

    for (sch, tbl), cols_map in needed.items():
        found_cols = found.get((sch.lower(), tbl.lower()), set())
        for col_lower, (orig_col, target_field) in cols_map.items():
            if col_lower not in found_cols:
                result.add_error(
                    f"DB 校验: 字段 {target_field} 的来源字段 '{orig_col}' "
                    f"在表 {sch}.{tbl} 中不存在（或表/字段名错误）"
                )


def main():
    parser = argparse.ArgumentParser(description="输入预检: 校验 rs_input.json 完整性")
    parser.add_argument("--input", required=True, help="rs_input.json 路径")
    parser.add_argument(
        "--refresh-schema",
        action="store_true",
        help="强制连库刷新表结构缓存（忽略过期判断）",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 文件不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    import json
    rs_input = json.loads(input_path.read_text(encoding="utf-8"))

    # 缓存放 rs_input.json 同目录（_internal/schema_cache.json）
    cache_path = input_path.parent / "schema_cache.json"

    result = precheck(rs_input, cache_path, args.refresh_schema)
    print(result.summary())
    sys.exit(result.return_code)


if __name__ == "__main__":
    main()
