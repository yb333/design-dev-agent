#!/usr/bin/env python3
"""
TS 规则切片: ts.json --rule R0001 → 单个规则的 YAML

coder agent 不读整个 ts.json（大表 300+字段会上下文爆炸），
而是调本脚本拿自己那个规则的切片。

切片内容（coder 写 SELECT 需要的全部信息）：
- 规则基本信息（rule_code/name/target_table/design_intent）
- 字段列表（target_field/field_type/transform_type/source_fields/design_logic）
- 关联策略（joins/join_safety）
- 粒度（grain）
- CTE（如有）
- 审计字段模板（全局，固定4个）
- 业务主键（全局，供参考）

用法:
  python slice_ts.py --ts ts.json --rule R0001
  python slice_ts.py --ts ts.json --rule R0001 --output R0001_slice.yaml
"""

import sys
import json
import argparse
from pathlib import Path

try:
    import yaml
except ImportError:
    print("错误: 需要 PyYAML。请运行 pip install pyyaml", file=sys.stderr)
    sys.exit(2)


def slice_rule(ts: dict, rule_code: str, etl_dir=None) -> dict:
    """从 ts.json 切出单个规则的信息 + 需要的全局信息。

    rule_code 先查 ts.rules（增量管道），找不到查 ts.init.rules（初始化管道）。
    etl_dir 给定时，对 derive 的 init 规则额外带 core_from 的源 .sql + filter/init_filter
    （coder 适配用：读源 SQL，把 filter 换成 init_filter）。pick_fields 不传 etl_dir，不触发此增强。
    """
    rules = ts.get("rules", {})
    init_section = ts.get("init") or {}
    init_rules = (init_section.get("rules") or {}) if isinstance(init_section, dict) else {}

    in_init = False
    if rule_code in rules:
        rule = rules[rule_code]
    elif rule_code in init_rules:
        rule = init_rules[rule_code]
        in_init = True
    else:
        available = list(rules.keys()) + list(init_rules.keys())
        raise ValueError(
            f"规则 '{rule_code}' 不存在。可用规则: {available}"
        )

    design = ts.get("design", {})
    tables = ts.get("tables", {})

    # 字段来源：tables[target_table].fields，按 field_targets 过滤，合并 field_logics 口径
    target_tbl = rule.get("target_table", "")
    target_short = target_tbl.rsplit(".", 1)[-1] if "." in target_tbl else target_tbl
    tbl_fields = tables.get(target_short, {}).get("fields", [])
    field_targets = set(rule.get("field_targets", []))
    field_logics = rule.get("field_logics", {})

    # 旧格式兼容：如果没有 tables，fallback 到 rule.fields
    if not tbl_fields and "fields" in rule:
        slice_fields = rule.get("fields", [])
    else:
        # 按该规则的 field_targets 过滤，把 field_logics 口径覆盖进去
        slice_fields = []
        for f in tbl_fields:
            fname = f.get("target_field", "")
            if fname in field_targets:
                # 合并口径：field_logics 优先（rule 级口径），其次 field 自带的 design_logic
                merged = dict(f)
                if fname in field_logics:
                    merged["design_logic"] = field_logics[fname]
                slice_fields.append(merged)

    # 分布键从 tables 取，fallback design.distribution_key
    tbl_dist = tables.get(target_short, {}).get("distribution_key", [])
    dist_key = tbl_dist if tbl_dist else design.get("distribution_key", [])

    # 组装切片
    sliced = {
        # 规则基本信息
        "rule_code": rule_code,
        "rule_name": rule.get("rule_name", ""),
        "target_table": rule.get("target_table", ""),
        "is_view_step": rule.get("is_view_step", False),
        "scenario": rule.get("scenario", ""),
        "exec_sequence": rule.get("exec_sequence", 1),
        "design_intent": rule.get("design_intent", ""),

        # 写入方式（coder 参考：merge_into 需要 ON 条件，truncate 不需要）
        "load_mode": rule.get("load_mode", "truncate_table"),

        # 增量设计（如有：coder 要在 SELECT 里加增量 WHERE 过滤）
        "incremental": rule.get("incremental", {}),

        # 关联策略（coder 写 FROM/JOIN 用）
        "source_tables": rule.get("source_tables", []),
        "joins": rule.get("joins", []),
        "join_safety": rule.get("join_safety", []),

        # 粒度变化
        "grain": rule.get("grain", {}),

        # CTE
        "ctes": rule.get("ctes", []),

        # ★ 字段列表（coder 写 SELECT 的核心依据）
        # 从 tables 段取字段定义，合并 rule 的 field_logics 口径
        "fields": slice_fields,
        "field_count": len(slice_fields),

        # 全局信息（coder 需要参考的）
        "_global": {
            # 审计字段模板（固定4个，coder 写 SELECT 时要带上审计字段赋值）
            "audit_fields": design.get("audit_fields", {}),
            # 业务主键（coder 写 GROUP BY 时参考，确保不发散）
            "business_key": design.get("business_key", []),
            # 分布键（本表的，从 tables 段取）
            "distribution_key": dist_key,
            # 目标表 schema（从 meta 取）
            "target_schema": ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", ""),
            # 可用参数（coder 在 SELECT 里用 ${PARAM} 引用）
            "exec_params": ts.get("meta", {}).get("schedule", {}).get("exec_params", {}),
        },
    }

    # derive 的 init 规则：带 core_from 的源 .sql + filter/init_filter，给 coder 适配
    # （init = 增量去 filter；coder 读源 SQL，把 filter 换成 init_filter，写 INIT.sql）
    if in_init and (init_section.get("mode") or "") == "derive":
        core_from = rule.get("core_from") or ""
        inc = rule.get("incremental") or {}
        clone_source = {
            "core_from": core_from,
            "filter": inc.get("filter", ""),          # 源 SQL 里的增量 filter（要被换掉）
            "init_filter": inc.get("init_filter", ""),  # init 用的 WHERE（换成的）
        }
        if core_from and etl_dir:
            src_sql_path = Path(etl_dir) / f"{core_from}.sql"
            if src_sql_path.exists():
                clone_source["source_sql"] = src_sql_path.read_text(encoding="utf-8").strip()
            else:
                clone_source["source_sql"] = ""
                clone_source["note"] = f"源 {core_from}.sql 未找到（等增量 coder 跑完再切片）"
        sliced["clone_source"] = clone_source

    return sliced


def _compact_direct_field(f: dict) -> str:
    """把 direct 字段压成单行字符串。

    格式: target_field | field_type | direct | alias.src_field
    例: user_name | varchar(100) | direct | oub.user_name

    source_fields 缺失或 alias/field 为空 → 用 placeholder 标记
    （codegen 消费 compact 行时会把这些标 TODO，不瞎生成）
    """
    target = f.get("target_field", "")
    ftype = f.get("field_type", "")
    sf_list = f.get("source_fields", [])
    if sf_list:
        sf = sf_list[0]
        alias = sf.get("alias", "")
        src = sf.get("field", "")
        src_ref = f"{alias}.{src}" if alias and src else "?"
    else:
        src_ref = "?"
    return f"{target} | {ftype} | direct | {src_ref}"


def to_compact_view(sliced: dict) -> dict:
    """生成 compact 视图（给 coder 读，大规则场景省 70%+ 体积）。

    - direct 字段压成单行字符串，放进 fields_direct 列表（一行一个）
    - 非 direct 字段（aggregate/assign/其他）完整保留在 fields_detail
    - 其余规则信息（joins/join_safety/ctes/grain 等）原样保留

    注意：assign 审计字段既不在 fields_direct 也不在 fields_detail
    （它们固定4个，codegen 自动处理，coder 不需要看）。
    若 assign 字段非审计类，保留在 fields_detail。
    """
    fields = sliced.get("fields", [])
    direct_compact = []
    detail = []
    for f in fields:
        ttype = f.get("transform_type", "")
        if ttype == "direct":
            direct_compact.append(_compact_direct_field(f))
        else:
            detail.append(f)

    # 拷贝切片，替换 fields 段
    view = dict(sliced)
    view["fields_direct"] = direct_compact
    view["fields_detail"] = detail
    view.pop("fields", None)
    return view


def slice_rule_opt(ts: dict, rule_code: str, baseline_sql: str) -> dict:
    """优化模式切片（docs/specs/opt/05 §一）：常规切片 + baseline SQL 原文 + 落位声明 + 硬约束。

    coder 在优化场景的输入——以 baseline SQL 为底稿加列，不从零写 SELECT。
    硬约束即 SQL 围栏的判定标准（sql_fence 机器执行，此处给人读）。
    """
    sliced = slice_rule(ts, rule_code)
    change = ts.get("change") or {}
    fields, joins = [], []
    for f in change.get("fields", []):
        if rule_code in f.get("placed_rules", []):
            fields.append({
                "field": f["field"], "target_table": f.get("target_table", ""),
                "backfill": f.get("backfill", "pending"),
            })
            joins.extend([{k: j[k] for k in ("table", "alias", "on") if k in j}
                          for j in f.get("new_joins", []) if j.get("rule") == rule_code])
    sliced["opt"] = {
        "mode": "optimization",
        "change_type": change.get("change_type", "add_field"),
        "declared_new_fields": fields,
        "declared_new_joins": joins,
        "baseline_sql": baseline_sql,
        "hard_constraints": [
            "老列投影一个字符都不许动（AST 级结构等价比对；格式差异可，等价改写如 ='N' 改 <>'Y' 也算越界）",
            "只许追加 change 段声明的新列；声明的新列必须出现",
            "FROM/JOIN/WHERE/GROUP BY/CTE 冻结；新 JOIN 只允许声明过的（别名+表名）",
            "改法：以 baseline_sql 为底稿加列，不从零重写；产出走 pipe 的 SQL 围栏闸门",
        ],
    }
    return sliced


def main():
    parser = argparse.ArgumentParser(
        description="TS 规则切片: 从 ts.json 切出单个规则的 YAML（给 coder 读）"
    )
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--rule", required=True, help="规则编号，如 R0001")
    parser.add_argument("--output", default="", help="输出 YAML 路径（默认打印到 stdout）")
    parser.add_argument("--verbose", action="store_true",
                        help="完整模式：direct 字段逐个展开（默认 compact 压一行省 70% 体积；需逐字段细节时用）")
    parser.add_argument("--baseline-sql", default="",
                        help="优化模式：baseline SQL 文件路径（etl_baseline/{rule}.sql）——给定时切优化模式")
    args = parser.parse_args()

    # 读 ts.json
    ts_path = Path(args.ts)
    if not ts_path.exists():
        print(f"错误: ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(2)
    ts = json.loads(ts_path.read_text(encoding="utf-8"))

    # etl 目录（ts.json 同级 etl/）：给 derive init 规则切片时读源 .sql 用
    etl_dir = ts_path.parent / "etl"

    # 切片
    try:
        if args.baseline_sql:
            bsql = Path(args.baseline_sql).read_text(encoding="utf-8")
            sliced = slice_rule_opt(ts, args.rule, baseline_sql=bsql)
        else:
            sliced = slice_rule(ts, args.rule, etl_dir=etl_dir)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 默认 compact（direct 压行）；--verbose 展开完整字段
    output_data = sliced if args.verbose else to_compact_view(sliced)

    # 输出
    yaml_text = yaml.dump(output_data, allow_unicode=True, default_flow_style=False, sort_keys=False)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml_text, encoding="utf-8")
        mode = "" if args.verbose else " [compact]"
        print(f"切片产出: {out}{mode}", file=sys.stderr)
        print(f"规则: {args.rule}, 字段数: {sliced['field_count']}", file=sys.stderr)
    else:
        print(yaml_text)


if __name__ == "__main__":
    main()
