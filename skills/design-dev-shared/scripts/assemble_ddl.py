#!/usr/bin/env python3
"""
DDL 生成器: ts.json → DDL SQL 文件

从 ts.json 的结构化信息自动生成 DDL（CREATE TABLE + COMMENT）。
确定性生成，不需要 AI。

生成内容：
- 每个规则产出一张表（中间表 / 目标F表）→ 一个 DDL 文件
- 视图只有一种：I 视图（F 表配套镜像），由 meta.target.i_view 配套生成
- 审计列纯来自 tables（装配处每表补齐，DDL 零补全）
- 分布键（design.distribution_key）
- 存储配置（列存 + LOW 压缩，固定标准）
- TO GROUP（schema 含 drt → gtoup_version1，否则 LC_DW1）

用法:
  python assemble_ddl.py --ts ts.json --outdir ddl/

预留增量扩展：未来可加 --alter 模式，对比现有表结构生成 ALTER。
"""

import sys
import json
import re
import argparse
from pathlib import Path
from datetime import datetime

from dws_standards import STANDARD_AUDIT_NAMES, STANDARD_AUDIT_TEMPLATE
from ts_compat import normalize_ts


def infer_logical_group(schema: str) -> str:
    """推断逻辑集群：schema 含 drt → gtoup_version1，否则 LC_DW1"""
    if "drt" in schema.lower():
        return "gtoup_version1"
    return "LC_DW1"


def split_table_ref(table_ref: str) -> tuple[str, str]:
    """拆分 schema.table 或 table → (schema, table)"""
    if "." in table_ref:
        parts = table_ref.split(".", 1)
        return parts[0], parts[1]
    return "", table_ref


def generate_create_table(rule_code: str, rule: dict, design: dict, meta: dict, tables: dict = None) -> str:
    """生成 CREATE TABLE DDL。

    字段来源优先级：tables[target_table].fields → rule.fields（旧格式兼容）
    分布键来源优先级：tables[target].distribution_key → design.distribution_key（旧格式兼容）
    """
    target = rule.get("target_table", "")
    schema, table = split_table_ref(target)

    if not schema:
        schema = meta.get("target", {}).get("f_table", {}).get("schema", "")

    cn = meta.get("target", {}).get("f_table", {}).get("cn", "")

    # 字段来源：优先 tables 段，fallback rule.fields（旧格式）
    table_short = table
    if tables and table_short in tables:
        tbl_info = tables[table_short]
        fields = tbl_info.get("fields", [])
        dist_key = ", ".join(tbl_info.get("distribution_key", []))
        distribute_type = tbl_info.get("distribute_type", "HASH" if dist_key else "ROUNDROBIN")
        logical_group = tbl_info.get("logical_group", "") or infer_logical_group(schema)
        storage = tbl_info.get("storage", "column")
    else:
        # 旧格式兼容（normalize 后三桶形态：从桶条目提取字段元数据；远古 dict 列表原样）
        fields = _flatten_rule_fields(rule.get("fields", []))
        dist_key = ", ".join(design.get("distribution_key", []))
        distribute_type = "HASH" if dist_key else "ROUNDROBIN"
        logical_group = infer_logical_group(schema)
        storage = "column"

    lines = []

    # 文件头注释
    lines.append(f"/* =====================================================")
    lines.append(f"   表名: {schema}.{table}")
    lines.append(f"   规则: {rule_code} - {rule.get('rule_name', '')}")
    lines.append(f"   分布键: {dist_key or '未指定'}")
    lines.append(f"   逻辑集群: {logical_group}")
    lines.append(f"   生成时间: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"   说明: {rule.get('design_intent', '')}")
    lines.append(f"   ===================================================== */")
    lines.append("")

    # CREATE TABLE
    lines.append(f"CREATE TABLE IF NOT EXISTS {schema}.{table} (")

    # 业务字段（用已从 tables/rule 取好的 fields 变量，不再重复从 rule 取）
    field_lines = []
    max_field_len = 0
    for f in fields:
        fname = f.get("target_field", "")
        ftype = f.get("field_type", "")
        fcomment = f.get("field_comment", "")
        max_field_len = max(max_field_len, len(fname))
        field_lines.append((fname, ftype, fcomment))

    # 列集纯来自 tables（DDL 唯一源——2026-09-15 定调：审计补齐只在装配处
    # build_tables 每表补齐，此处零补全逻辑；旧版自带"从 design.audit_fields
    # 去重追加"曾致中间表 DDL 12 列 vs ts 7 列/SELECT 11 列的三处分裂）
    for i, (fname, ftype, fcomment) in enumerate(field_lines):
        comma = "," if i < len(field_lines) - 1 else ""
        lines.append(f"    {fname:<{max_field_len}} {type_or_empty(ftype)}{comma}")

    lines.append(")")

    # 存储配置
    lines.append(f"WITH (")
    lines.append(f"    ORIENTATION = COLUMN,")
    lines.append(f"    COMPRESSION = LOW")
    lines.append(f")")

    # 分布方式（HASH / ROUNDROBIN / REPLICATION）
    if distribute_type == "HASH" and dist_key:
        lines.append(f"DISTRIBUTE BY HASH({dist_key})")
    elif distribute_type == "REPLICATION":
        lines.append(f"DISTRIBUTE BY REPLICATION")
    else:
        lines.append(f"DISTRIBUTE BY ROUNDROBIN")

    # TO GROUP
    lines.append(f'TO GROUP "{logical_group}";')
    lines.append("")

    # 表注释
    lines.append(f"COMMENT ON TABLE {schema}.{table} IS '{cn or rule.get('rule_name', '')}';")
    lines.append("")

    # 字段注释
    for fname, ftype, fcomment in field_lines:
        if fcomment:
            lines.append(f"COMMENT ON COLUMN {schema}.{table}.{fname} IS '{fcomment}';")

    # 审计字段注释：标准名匹配 field_lines（tables 补全已带 comment，无注释的按标准补）
    for fname, _, fcomment in field_lines:
        if fname.lower() in STANDARD_AUDIT_NAMES and not fcomment:
            cmt = STANDARD_AUDIT_TEMPLATE.get(fname, {}).get("comment", "")
            if cmt:
                lines.append(f"COMMENT ON COLUMN {schema}.{table}.{fname} IS '{cmt}';")

    lines.append("")
    return "\n".join(lines)


def normalize_type(t: str) -> str:
    """归一化字段类型：只处理「带精度后缀的 int 家族」这类 mapping 合法但 Gauss 非法的写法，其余原样透传。"""
    if not t:
        return ""
    t = t.strip()
    for pat, repl in _TYPE_NORMALIZE:
        if pat.match(t):
            return pat.sub(repl, t)
    return t


def type_or_empty(t: str) -> str:
    """字段类型（带精度 int 家族归一，其余原样），空则返回空"""
    return normalize_type(t) if t else ""


# 类型归一化分两类（规则不混）：
# 1) 非法写法修正：int 家族带精度后缀（int4(32) 是 Oracle 合法写法，Gauss 拒绝）。
#    类型本身 Gauss 认的（nvarchar2/varchar2/number/tinyint/裸 int8 等）一律原样透传：
#    mapping 是目标类型的 source of truth，写错了改 mapping（precheck 源头提示），DDL 不代改。
# 2) 时间类型标准化书写：与容量陷阱的字符类型不同，datetime/裸 timestamp → 标准写法
#    timestamp(0) without time zone 是**等价转换**（秒级口径与审计标准一致，库里都执行）；
#    显式精度的只补全写法（timestamp(6) → timestamp(6) without time zone）；
#    with time zone 不动（存储语义不同，precheck 同名比对也视为不同类型）；date/time 不动。
_TYPE_NORMALIZE = [
    (re.compile(r"^int8\(\d+\)$", re.I), "bigint"),       # int8(64) → bigint（裸 int8 Gauss 认，不动）
    (re.compile(r"^int4\(\d+\)$", re.I), "integer"),      # int4(32) → integer
    (re.compile(r"^int2\(\d+\)$", re.I), "smallint"),     # int2(16) → smallint
    (re.compile(r"^int\(\d+\)$", re.I), "integer"),       # int(11) → integer
    # 时间类型标准化（等价转换，不涉容量/语义变化）
    (re.compile(r"^datetime$", re.I), "timestamp(0) without time zone"),
    (re.compile(r"^timestamp(\(\d+\))?( without time zone)?$", re.I),
     lambda m: f"timestamp{m.group(1) or '(0)'} without time zone"),  # 裸/无后缀 → 补 (0) + 标准后缀
]


def generate_rollback(schema: str, table: str, is_view: bool = False) -> str:
    """生成回退脚本（DROP）"""
    obj_type = "VIEW" if is_view else "TABLE"
    cn = ""
    lines = []
    lines.append(f"/* 回退脚本: DROP {obj_type} {schema}.{table} */")
    lines.append(f"DROP {obj_type} IF EXISTS {schema}.{table};")
    lines.append("")
    return "\n".join(lines)


def _flatten_rule_fields(fields) -> list:
    """rule.fields 三桶形态 → 字段元数据列表（远古 dict 列表原样；DDL/i_view fallback 用）。"""
    if isinstance(fields, dict):
        _flat = []
        for _kind in ("processed", "assign", "direct"):
            for _e in (fields.get(_kind) or []):
                if isinstance(_e, dict):
                    _flat.append({"target_field": _e.get("target") or _e.get("target_field") or str(_e),
                                  "field_type": _e.get("type", "") or _e.get("field_type", ""),
                                  "field_comment": _e.get("comment", "")})
                else:
                    _flat.append({"target_field": str(_e), "field_type": "", "field_comment": ""})
        return _flat
    return fields or []


def generate_i_view(schema: str, f_table: str, cn: str, fields: list) -> str:
    """生成 I视图 DDL（F表镜像，列出全部字段 + 注释，不用 SELECT *）"""
    i_table = f_table[:-2] + "_i" if f_table.endswith("_f") else f_table + "_i"

    # rule.fields 已包含审计字段（assemble_ts 组装时已加入），直接用（三桶形态先摊平）
    fields = _flatten_rule_fields(fields)
    all_fields = [(f.get("target_field", ""), f.get("field_comment", "")) for f in fields]

    lines = []
    lines.append(f"/* I视图: {schema}.{i_table}（{cn}，F表镜像，对外消费接口） */")
    lines.append(f"CREATE OR REPLACE VIEW {schema}.{i_table} AS")
    lines.append(f"SELECT")

    # 源表带别名（团队 SQL 规范：列引用带别名前缀，与 ETL SQL 风格一致）
    alias = "t"
    for i, (fname, _) in enumerate(all_fields):
        comma = "," if i < len(all_fields) - 1 else ""
        lines.append(f"    {alias}.{fname}{comma}")

    lines.append(f"FROM {schema}.{f_table} {alias};")
    lines.append("")
    lines.append(f"COMMENT ON VIEW {schema}.{i_table} IS '{cn}（视图）';")
    lines.append("")

    for fname, fcomment in all_fields:
        if fcomment:
            lines.append(f"COMMENT ON COLUMN {schema}.{i_table}.{fname} IS '{fcomment}';")

    lines.append("")
    return "\n".join(lines)


def generate_ddl(ts: dict) -> tuple[dict[str, str], dict[str, str]]:
    """从 ts.json 生成所有 DDL + 回退脚本。

    核心逻辑（不加戏——照 ts.json 做）：
    - 最终目标 F 表（== meta.target.f_table.table）→ 建表 + 如果 meta.target.i_view 非空则建 I 视图
    - 中间表/其他表 → 只建表，不建视图（即使 meta.target.i_view 非空）
    - I 视图是否建，取决于 meta.target.i_view 在不在（ts.json 如实表达，assemble_ddl 不自动配套）

    返回 (ddl_dict, rollback_dict)。
    """
    # 读入即标准态（2026-09-15 审计定调）：旧档 tables 缺审计列 → normalize 补齐，
    # DDL 纯投影零补全（新档 build_tables 已每表补齐，normalize 幂等无变化）
    ts = normalize_ts(ts)
    rules = ts.get("rules", {})
    design = ts.get("design", {})
    tables = ts.get("tables", {})
    meta = ts.get("meta", {})
    target_meta = meta.get("target", {})
    f_table_meta = target_meta.get("f_table", {})
    i_view_meta = target_meta.get("i_view", {})
    f_schema = f_table_meta.get("schema", "")
    f_cn = f_table_meta.get("cn", "")
    f_table_short = f_table_meta.get("table", "")  # 最终目标 F 表短名
    i_view_short = i_view_meta.get("table", "")    # I 视图短名（空则不建视图）

    ddl_result = {}
    rollback_result = {}
    generated_views = set()  # 避免重复生成视图

    for code, rule in rules.items():
        target = rule.get("target_table", "")
        schema, table = split_table_ref(target)
        if not schema:
            schema = f_schema

        # 判断是否最终目标 F 表（按 meta.target.f_table，不按后缀猜）
        # F 表短名必须以 _f 结尾（设计约定：目标表都是 _f）；_d/tmp 即使等于 f_table_short 也不是 F 表
        is_final_f = bool(f_table_short) and table == f_table_short and f_table_short.endswith("_f")

        # 向后兼容：如果 target 还是 _i（assemble_ts 没转），转 _f 建表
        if table.endswith("_i"):
            f_table_from_i = table[:-2] + "_f"
            f_rule = {**rule, "target_table": f"{schema}.{f_table_from_i}"}
            filename = f"create_table_{f_table_from_i}.sql"
            ddl_result[filename] = generate_create_table(code, f_rule, design, meta, tables)
            rollback_result[f"rollback_create_table_{f_table_from_i}.sql"] = generate_rollback(schema, f_table_from_i)
            # 字段用 tables[f_table_from_i]，fallback rule
            view_fields_table_key = f_table_from_i
            is_final_f = True
        else:
            filename = f"create_table_{table}.sql"
            ddl_result[filename] = generate_create_table(code, rule, design, meta, tables)
            rollback_result[f"rollback_create_table_{table}.sql"] = generate_rollback(schema, table)
            view_fields_table_key = table

        # ★ I 视图：只有最终目标 F 表 + meta.target.i_view 非空才建（不加戏）
        if is_final_f and i_view_short and i_view_short not in generated_views:
            generated_views.add(i_view_short)
            i_filename = f"create_view_{i_view_short}.sql"
            view_fields = tables.get(view_fields_table_key, {}).get("fields", rule.get("fields", []))
            ddl_result[i_filename] = generate_i_view(schema, view_fields_table_key,
                                                     f_cn or rule.get("rule_name", ""),
                                                     view_fields)
            rollback_result[f"rollback_create_view_{i_view_short}.sql"] = generate_rollback(schema, i_view_short, is_view=True)

    return ddl_result, rollback_result


def main():
    parser = argparse.ArgumentParser(
        description="DDL 生成器: 从 ts.json 自动生成 CREATE TABLE/VIEW DDL + 回退脚本"
    )
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--outdir", required=True, help="DDL 输出根目录（ddl/ 和 ddl_rollback/ 在下面）")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    if not ts_path.exists():
        print(f"错误: ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(2)
    ts = json.loads(ts_path.read_text(encoding="utf-8"))

    ddls, rollbacks = generate_ddl(ts)

    ddl_dir = Path(args.outdir) / "ddl"
    rollback_dir = Path(args.outdir) / "ddl_rollback"
    ddl_dir.mkdir(parents=True, exist_ok=True)
    rollback_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in ddls.items():
        (ddl_dir / filename).write_text(content, encoding="utf-8")
        print(f"  ✓ ddl/{filename}")

    for filename, content in rollbacks.items():
        (rollback_dir / filename).write_text(content, encoding="utf-8")
        print(f"  ✓ ddl_rollback/{filename}")

    print(f"\n[完成] {len(ddls)} 个 DDL + {len(rollbacks)} 个回退脚本")


if __name__ == "__main__":
    main()
