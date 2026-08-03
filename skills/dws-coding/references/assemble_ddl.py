#!/usr/bin/env python3
"""
DDL 生成器: ts.json → DDL SQL 文件

从 ts.json 的结构化信息自动生成 DDL（CREATE TABLE + COMMENT）。
确定性生成，不需要 AI。

生成内容：
- 每个规则产出一张表（中间表 / 目标F表）→ 一个 DDL 文件
- 视图步骤（is_view_step=true）→ 生成 CREATE VIEW（F表镜像）
- 审计字段自动加（从 design.audit_fields）
- 分布键（design.distribution_key）
- 存储配置（列存 + LOW 压缩，固定标准）
- TO GROUP（schema 含 drt → gtoup_version1，否则 LC_DW1）

用法:
  python assemble_ddl.py --ts ts.json --outdir ddl/

预留增量扩展：未来可加 --alter 模式，对比现有表结构生成 ALTER。
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime


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


def generate_create_table(rule_code: str, rule: dict, design: dict, meta: dict) -> str:
    """生成 CREATE TABLE DDL"""
    target = rule.get("target_table", "")
    schema, table = split_table_ref(target)

    if not schema:
        schema = meta.get("target", {}).get("f_table", {}).get("schema", "")

    cn = meta.get("target", {}).get("f_table", {}).get("cn", "")
    logical_group = infer_logical_group(schema)
    dist_key = ", ".join(design.get("distribution_key", []))
    audit_fields = design.get("audit_fields", {})

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

    # 业务字段
    field_lines = []
    max_field_len = 0
    for f in rule.get("fields", []):
        fname = f.get("target_field", "")
        ftype = f.get("field_type", "")
        fcomment = f.get("field_comment", "")
        max_field_len = max(max_field_len, len(fname))
        field_lines.append((fname, ftype, fcomment))

    # 审计字段（去重：若审计字段已出现在 rule.fields 中则不重复追加，
    # 否则会生成重复列名导致 DDL 语法错误）
    business_field_names = {fname for fname, _, _ in field_lines}
    audit_lines = []
    for aname, aspec in audit_fields.items():
        if aname in business_field_names:
            continue
        atype = aspec.get("type", "") if isinstance(aspec, dict) else str(aspec)
        audit_lines.append((aname, atype, ""))

    # 输出字段
    all_fields = field_lines + audit_lines
    for i, (fname, ftype, fcomment) in enumerate(all_fields):
        comma = "," if i < len(all_fields) - 1 else ""
        comment = f"  /* {fcomment} */" if fcomment else ""
        if i == len(field_lines):
            lines.append(f"    /* 审计字段 */")
        lines.append(f"    {fname:<{max_field_len}} {type_or_empty(ftype)}{comma}{comment}")

    lines.append(")")

    # 存储配置
    lines.append(f"WITH (")
    lines.append(f"    ORIENTATION = COLUMN,")
    lines.append(f"    COMPRESSION = LOW")
    lines.append(f")")

    # 分布键
    if dist_key:
        lines.append(f"DISTRIBUTE BY HASH({dist_key})")

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

    # 审计字段注释
    audit_comments = {
        "del_flag": "删除标识: Y-已删除, N-正常",
        "crt_cycle_id": "创建批次ID",
        "last_upd_cycle_id": "最后更新批次ID",
        "dw_last_update_date": "数仓最后更新时间",
    }
    for aname, _, _ in audit_lines:
        cmt = audit_comments.get(aname, "")
        if cmt:
            lines.append(f"COMMENT ON COLUMN {schema}.{table}.{aname} IS '{cmt}';")

    lines.append("")
    return "\n".join(lines)


def generate_create_view(rule_code: str, rule: dict, meta: dict) -> str:
    """生成 CREATE VIEW DDL（F表镜像 I视图）"""
    target = rule.get("target_table", "")
    schema, table = split_table_ref(target)
    f_table = table.rstrip("i").rstrip("_") if table.endswith("_i") else table
    if not f_table.endswith("_f"):
        f_table = table[:-2] + "_f" if table.endswith("_i") else table

    cn = meta.get("target", {}).get("f_table", {}).get("cn", "")

    lines = []
    lines.append(f"/* =====================================================")
    lines.append(f"   视图: {schema}.{table}")
    lines.append(f"   规则: {rule_code} - {rule.get('rule_name', '')}")
    lines.append(f"   说明: F表镜像，对外消费接口")
    lines.append(f"   ===================================================== */")
    lines.append("")
    lines.append(f"CREATE OR REPLACE VIEW {schema}.{table} AS")
    lines.append(f"SELECT * FROM {schema}.{f_table};")
    lines.append("")
    lines.append(f"COMMENT ON TABLE {schema}.{table} IS '{cn}（视图）';")
    lines.append("")
    return "\n".join(lines)


def type_or_empty(t: str) -> str:
    """字段类型，空则返回空"""
    return t if t else ""


def generate_rollback(schema: str, table: str, is_view: bool = False) -> str:
    """生成回退脚本（DROP）"""
    obj_type = "VIEW" if is_view else "TABLE"
    cn = ""
    lines = []
    lines.append(f"/* 回退脚本: DROP {obj_type} {schema}.{table} */")
    lines.append(f"DROP {obj_type} IF EXISTS {schema}.{table};")
    lines.append("")
    return "\n".join(lines)


def generate_i_view(schema: str, f_table: str, cn: str) -> str:
    """生成 I视图 DDL（F表镜像：SELECT * FROM ..._f）"""
    i_table = f_table[:-2] + "_i" if f_table.endswith("_f") else f_table + "_i"
    lines = []
    lines.append(f"/* I视图: {schema}.{i_table}（{cn}，F表镜像，对外消费接口） */")
    lines.append(f"CREATE OR REPLACE VIEW {schema}.{i_table} AS")
    lines.append(f"SELECT * FROM {schema}.{f_table};")
    lines.append("")
    lines.append(f"COMMENT ON TABLE {schema}.{i_table} IS '{cn}（视图）';")
    lines.append("")
    return "\n".join(lines)


def generate_ddl(ts: dict) -> tuple[dict[str, str], dict[str, str]]:
    """从 ts.json 生成所有 DDL + 回退脚本。

    返回 (ddl_dict, rollback_dict)。
    ddl_dict: {文件名: 内容}，写到 ddl/
    rollback_dict: {文件名: 内容}，写到 ddl_rollback/
    """
    rules = ts.get("rules", {})
    design = ts.get("design", {})
    meta = ts.get("meta", {})
    target_meta = meta.get("target", {})
    f_table_name = target_meta.get("f_table", {}).get("table", "")
    f_schema = target_meta.get("f_table", {}).get("schema", "")
    f_cn = target_meta.get("f_table", {}).get("cn", "")

    ddl_result = {}
    rollback_result = {}
    generated_i_views = set()  # 避免重复生成 I视图

    for code, rule in rules.items():
        target = rule.get("target_table", "")
        schema, table = split_table_ref(target)
        if not schema:
            schema = f_schema

        if rule.get("is_view_step", False):
            # 显式视图步骤
            filename = f"create_view_{table}.sql"
            ddl_result[filename] = generate_create_view(code, rule, meta)
            rollback_result[f"rollback_create_view_{table}.sql"] = generate_rollback(schema, table, is_view=True)
        else:
            # 表
            filename = f"create_table_{table}.sql"
            ddl_result[filename] = generate_create_table(code, rule, design, meta)
            rollback_result[f"rollback_create_table_{table}.sql"] = generate_rollback(schema, table)

            # 如果是目标F表，自动配套生成 I视图（F+I成对）
            if table == f_table_name and f_table_name:
                i_table = f_table_name[:-2] + "_i" if f_table_name.endswith("_f") else f_table_name + "_i"
                if i_table not in generated_i_views:
                    generated_i_views.add(i_table)
                    i_filename = f"create_view_{i_table}.sql"
                    ddl_result[i_filename] = generate_i_view(schema, f_table_name, f_cn)
                    rollback_result[f"rollback_create_view_{i_table}.sql"] = generate_rollback(schema, i_table, is_view=True)

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
