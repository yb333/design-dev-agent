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
    no_rs = rs_input.get("_no_rs_mode", False)
    if no_rs:
        # 无RS模式：调度信息是默认值兜底的，提示 designer/export 阶段需注意
        result.add_warn(
            "无RS模式：调度/增量/DQ 信息用默认值兜底（全量调度/T+1/无DQ）。"
            "export 阶段的调度配置和上游依赖可能不完整，建议后续补 RS 再重跑"
        )
    else:
        if not schedule.get("frequency"):
            result.add_warn("调度频率缺失 (RS L07 调度频率)")
        if not schedule.get("upstream"):
            result.add_warn("上游调度任务缺失 (RS L07 湖表调度信息)")

    # 5b. 增量校验：标了增量必须有驱动表+增量字段，驱动表须在 source_tables 里
    incremental_key = (schedule.get("incremental_key") or "").strip()
    incremental_tables = schedule.get("incremental_tables", [])
    is_incremental = bool(incremental_key) and incremental_key not in ("不涉及", "无", "")

    if is_incremental:
        # 增量场景：必须有驱动表信息
        if not incremental_tables:
            result.add_error(
                f"调度方案标了增量（增量识别方式={incremental_key}），"
                f"但 RS 的'增量表及增量字段'段为空——必须有驱动表+增量字段"
            )
        else:
            result.add_pass(f"增量场景: {len(incremental_tables)} 张驱动表")
            # 校验每张驱动表：须有增量字段、表名须在 source_tables 里
            src_table_names = {
                (st.get("source_table") or "").strip().lower() for st in source_tables
            }
            for it in incremental_tables:
                drv_table = (it.get("source_table") or "").strip()
                drv_key = (it.get("incremental_key") or "").strip()
                if not drv_table:
                    result.add_error("增量驱动表的来源表名为空")
                elif not drv_key:
                    result.add_error(f"增量驱动表 '{drv_table}' 没填增量字段")
                else:
                    # 驱动表名可能是 schema.table 或纯表名，取表名部分比对
                    drv_table_short = drv_table.split(".")[-1].lower()
                    if (drv_table_short not in src_table_names
                            and drv_table.lower() not in src_table_names):
                        result.add_error(
                            f"增量驱动表 '{drv_table}' 不在 mapping 的 source_tables 里"
                            f"（检查表名拼写或补充源表）"
                        )
    else:
        # 全量场景：不应有增量驱动表（RS 增量识别=不涉及，但填了驱动表→矛盾）
        if incremental_tables:
            result.add_warn(
                f"增量识别方式='{incremental_key}'（全量），但 RS 填了 "
                f"{len(incremental_tables)} 张增量驱动表——确认是否应为增量"
            )

    # 6. 别名一致性 + 表别名重复 + 字段级/表级一致性
    entity_aliases = {st.get("source_alias") for st in source_tables if st.get("source_alias")}
    for fm in field_mappings:
        fm_alias = fm.get("source_alias", "")
        if fm_alias and fm_alias not in entity_aliases:
            result.add_error(f"字段 {fm.get('target_column', '?')} 的来源别名 '{fm_alias}' 在实体级 mapping 中不存在")

    # 6a. 表别名重复检查（实体级同别名出现多次 → JOIN 时歧义）
    alias_count: dict[str, int] = {}
    for st in source_tables:
        al = (st.get("source_alias") or "").strip()
        if al:
            alias_count[al] = alias_count.get(al, 0) + 1
    for al, cnt in alias_count.items():
        if cnt > 1:
            result.add_error(f"实体级表别名 '{al}' 重复出现 {cnt} 次（JOIN 时会歧义）")

    # 6b. 字段级与表级一致性：字段级的 source_schema/source_table 应在实体级定义范围内
    entity_tables = {
        ((st.get("source_schema") or "").strip(), (st.get("source_table") or "").strip())
        for st in source_tables
    }
    for fm in field_mappings:
        fm_sch = (fm.get("source_schema") or "").strip()
        fm_tbl = (fm.get("source_table") or "").strip()
        if fm_sch and fm_tbl and (fm_sch, fm_tbl) not in entity_tables:
            result.add_error(
                f"字段 {fm.get('target_column', '?')} 的来源表 {fm_sch}.{fm_tbl} "
                f"在实体级 mapping 中未定义"
            )

    # 6c. source_column 不能是中文（应是英文物理列名，中文是另一个字段"源表字段中文名"）
    import re as _re
    for fm in field_mappings:
        sc = (fm.get("source_column") or "").strip()
        if sc and _re.search(r"[\u4e00-\u9fff]", sc):
            result.add_error(
                f"字段 {fm.get('target_column', '?')} 的 source_column '{sc}' 含中文"
                f"（应为英文物理列名，中文列名应在'源表字段中文名'列）"
            )

    # 7. 映射表达式模糊术语检查
    biz_terms = ["等等", "之类", "相关", "之类的", "等等等"]
    for fm in field_mappings:
        expr = fm.get("transform_detail") or fm.get("mapping_expression") or ""
        for term in biz_terms:
            if term in str(expr):
                result.add_warn(f"字段 {fm.get('target_column', '?')} 的映射表达式含模糊术语: '{term}'")

    # 8. 审计字段校验
    _check_audit_fields(field_mappings, result)

    # 8b. 命名规范校验（字典型内容下沉：表名前缀/后缀、字段后缀类型一致性）
    _check_naming_conventions(target_table, source_tables, field_mappings, result)

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


# DWS 分层前缀（接入/明细/连接）
LAYER_PREFIXES = ("DWD", "DWB", "DWL")
# 表后缀：F（物理表）/I（视图）/tmp（临时表，后跟数字）
TABLE_SUFFIX_F = "_f"
TABLE_SUFFIX_I = "_i"
# 字段后缀 → 期望类型关键词（用于校验 target_type 与命名后缀一致性）
FIELD_SUFFIX_TYPE_MAP = {
    "_id": ("bigint", "int"),
    "_code": ("varchar", "char", "text", "nvarchar"),
    "_name": ("varchar", "char", "text", "nvarchar"),
    "_amt": ("decimal", "numeric", "number"),
    "_rate": ("decimal", "numeric", "number"),
    "_qty": ("decimal", "numeric", "number"),
    "_num": ("bigint", "int"),
    "_dt": ("date",),
    "_time": ("timestamp", "datetime"),
    "_flag": ("nvarchar", "varchar", "char"),
    "_type": ("varchar", "char", "text"),
    "_desc": ("varchar", "char", "text"),
}


def _check_naming_conventions(
    target_table: str,
    source_tables: list,
    field_mappings: list,
    result: PrecheckResult,
):
    """命名规范校验（字典型内容下沉，designer 不背字典）。

    - 目标表名分层前缀（DWD/DWB/DWL）+ 后缀（F/I）校验
    - 字段后缀与 target_type 一致性（warn，不阻断——类型映射可能合法地偏离）
    """
    import re as _re

    # 目标表命名：前缀 + 后缀
    if target_table:
        tbl_upper = target_table.upper()
        has_prefix = any(tbl_upper.startswith(p + "_") for p in LAYER_PREFIXES)
        if not has_prefix:
            result.add_warn(
                f"目标表名 '{target_table}' 未以分层前缀开头（DWD/DWB/DWL），"
                f"不符合 DWS 命名规范"
            )
        # 后缀：_f / _i / _tmp{n}（临时表后缀在校验 design_decisions 的中间表时才出现，这里只看目标表）
        if not (tbl_upper.endswith(TABLE_SUFFIX_F) or tbl_upper.endswith(TABLE_SUFFIX_I)):
            # 临时表 tmp{n} 后缀不在目标表场景，这里不报
            result.add_warn(
                f"目标表名 '{target_table}' 未以 F 或 I 后缀结尾（物理表/视图），"
                f"不符合 DWS 命名规范"
            )

    # 字段后缀 → 类型一致性（warn）
    for fm in field_mappings:
        tf = (fm.get("target_column") or "").strip().lower()
        tt = (fm.get("target_type") or "").strip().lower()
        if not tf or not tt:
            continue
        for suffix, expected_types in FIELD_SUFFIX_TYPE_MAP.items():
            if tf.endswith(suffix):
                if not any(et in tt for et in expected_types):
                    result.add_warn(
                        f"字段 '{tf}' 后缀 '{suffix}' 暗示类型应为 "
                        f"{'/'.join(expected_types)}，但 target_type='{tt}'，"
                        f"确认是否命名与类型不一致"
                    )
                break  # 匹配到一个后缀即可，不重复判


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
    # {(schema, table): {source_column_lower: (原source_column, [target_fields], source_type)}}
    # 同一来源字段映射多个目标时，target_fields 累积成列表（避免覆盖丢失）
    needed: dict[tuple[str, str], dict[str, list]] = {}
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
        col_key = source_column.lower()
        tbl_map = needed.setdefault((schema, table), {})
        if col_key not in tbl_map:
            source_type = (fm.get("source_type") or "").strip()
            tbl_map[col_key] = [source_column, [], source_type]
        # 累积目标字段（同一来源字段可能映射到多个目标）
        tbl_map[col_key][1].append(fm.get("target_column", "?"))

    if not needed:
        return

    total_fields = sum(len(cols) for cols in needed.values())
    all_tables = list(needed.keys())

    # ── 缓存有效就用（整体），无效就连库整体查所有表 ──
    # 缓存粒度 = 本次用到的全部来源表；不做按表补缺（同用例来源表固定，整体刷新更简单）
    # found: {(sch, tbl): {col_lower: type_lower}}
    found: dict[tuple[str, str], dict[str, str]] = {}
    cache_used = False

    if cache_path and not refresh_schema:
        cache = _load_schema_cache(cache_path)
        if not _is_cache_expired(cache.get("cached_at", ""), ttl_hours=72):
            # 缓存未过期：用缓存里的表结构（本次用到的表都应在缓存里）
            raw_tables = cache.get("tables", {})
            for (sch, tbl) in all_tables:
                key = f"{sch.lower()}.{tbl.lower()}"
                if key in raw_tables:
                    # 缓存里是 {col: type}，兼容旧格式（list 时转无类型 dict）
                    raw = raw_tables[key]
                    if isinstance(raw, dict):
                        found[(sch.lower(), tbl.lower())] = {k.lower(): v.lower() for k, v in raw.items()}
                    elif isinstance(raw, list):
                        found[(sch.lower(), tbl.lower())] = {c.lower(): "" for c in raw}
            cache_used = True

    # ── 缓存无效（过期/不存在/强制刷新）→ 连库整体查所有表 ──
    if not cache_used:
        target = rs_input.get("meta", {}).get("target", {})
        target_schema = target.get("f_table", {}).get("schema", "") or target.get("schema", "")
        try:
            sys.path.insert(
                0,
                str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"),
            )
            from dws_db import create_executor_for_schema

            executor = create_executor_for_schema(target_schema)
            if not executor.test_connection():
                return  # 连不上库，静默跳过
            # UNION ALL 一条 SQL 查全部表
            fetched = _fetch_tables_schema_batch(executor, all_tables)
            executor.close()
            found = fetched
            # 写缓存（存 {col: type}）
            if cache_path:
                cache_new = {"cached_at": "", "tables": {}}
                for (sch, tbl), cols in fetched.items():
                    cache_new["tables"][f"{sch}.{tbl}"] = cols  # 已是 {col: type}
                _save_schema_cache(cache_path, cache_new)
        except Exception:
            return  # 连不上库，静默跳过

    # ── 比对（纯本地）──
    result.add_pass(
        f"DB 校验: 校验 {len(all_tables)} 张表 / {total_fields} 个字段"
        f"（{'缓存命中' if cache_used else '连库刷新'}）"
    )

    for (sch, tbl), cols_map in needed.items():
        found_cols = found.get((sch.lower(), tbl.lower()), {})
        for col_lower, entry in cols_map.items():
            orig_col, target_fields, source_type = entry
            # 报错归属以"来源字段"为主语（存在性/类型是来源字段的属性，与目标无关）
            # 顺带显示受影响的目标字段：单个直接显示，多个显示数量
            targets_str = target_fields[0] if len(target_fields) == 1 else f"{len(target_fields)}个目标字段"

            if col_lower not in found_cols:
                result.add_error(
                    f"DB 校验: 来源字段 '{orig_col}'（{sch}.{tbl}，→{targets_str}）"
                    f"在库中不存在（或表/字段名错误）"
                )
                continue
            # 类型严格匹配（mapping 的 source_type vs 库里实际类型）
            actual_type = found_cols.get(col_lower, "")
            if source_type and actual_type:
                expected_norm = _normalize_type(source_type)
                actual_norm = _normalize_type(actual_type)
                if expected_norm != actual_norm:
                    result.add_error(
                        f"DB 校验: 来源字段 '{orig_col}'（{sch}.{tbl}，→{targets_str}）"
                        f"类型不符（mapping={source_type}，库里={actual_type}）"
                    )


def _normalize_type(raw: str) -> str:
    """类型名归一化（便于严格比较）。

    处理常见的同义异名：
    - varchar → character varying
    - int → integer（PG 标准名）
    - 去多余空白、括号内空白

    时间类型家族（with/without time zone 底层存储不同，分开归一）：
    - timestamp / timestamp(n) / without time zone → 统一 ts_notz（忽略精度）
    - timestamptz / timestamp(n) with time zone     → 统一 ts_tz（忽略精度）
    with 和 without 不互通（底层不同：一个带时区偏移一个不带）。
    """
    t = raw.strip().lower().replace(" ", "")

    # 时间类型族：先判 with/without time zone（底层不同，不归一），再忽略精度
    if "timestamp" in t:
        is_tz = "withtimezone" in t or t.startswith("timestamptz")
        return "ts_tz" if is_tz else "ts_notz"

    aliases = {
        "varchar": "charactervarying",
        "int": "integer",
        "int4": "integer",
        "int8": "bigint",
        "int2": "smallint",
        "bool": "boolean",
        "decimal": "numeric",
    }
    # 只替换类型前缀部分（保留长度，如 charactervarying(64)）
    base = t.split("(")[0]
    rest = "(" + t.split("(", 1)[1] if "(" in t else ""
    return aliases.get(base, base) + rest


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
