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

# shared 库（ts_compat 等）自洽引用：相对路径推算 design-dev-shared（与 check_sql 同款）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))

from run_ut import dq_filename

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

    # fields = rule 级三桶（coder 唯一消费源；normalize_ts 把旧结构 ts 升级成同形态）
    from ts_compat import normalize_ts
    ts = normalize_ts(ts)
    fields = rule.get("fields") or {"processed": [], "assign": [], "direct": []}
    target_tbl = rule.get("target_table", "")
    target_short = target_tbl.rsplit(".", 1)[-1] if "." in target_tbl else target_tbl

    # 分布键从 tables 取，fallback design.distribution_key
    tbl_dist = tables.get(target_short, {}).get("distribution_key", [])
    dist_key = tbl_dist if tbl_dist else design.get("distribution_key", [])

    # 组装切片
    sliced = {
        # 规则基本信息
        "rule_code": rule_code,
        "rule_name": rule.get("rule_name", ""),
        "target_table": rule.get("target_table", ""),
        "scenario": rule.get("scenario", ""),
        "exec_sequence": rule.get("exec_sequence", 1),
        "design_intent": rule.get("design_intent", ""),

        # 写入方式（coder 参考：merge_into 需要 ON 条件，truncate 不需要）
        "load_mode": rule.get("load_mode", "truncate_table"),

        # 增量设计（如有：coder 要在 SELECT 里加增量 WHERE 过滤）
        "incremental": rule.get("incremental", {}),

        # 规则级行过滤（WHERE，如 del_flag='N'；与 join 级限定 joins.filter 分工）
        "filter": rule.get("filter", ""),

        # 排重策略（累积共建场景：designer 定策略 coder 翻译成 LEFT JOIN / NOT EXISTS）
        "dedup_strategy": rule.get("dedup_strategy", {}),

        # 关联策略（coder 写 FROM/JOIN 用）
        "source_tables": rule.get("source_tables", []),
        "joins": rule.get("joins", []),
        "join_safety": rule.get("join_safety", []),

        # 粒度变化
        "grain": rule.get("grain", {}),

        # ★ 字段三桶（coder 写 SELECT 的核心依据）：processed 优先看 / assign 固定值 / direct 一把贴
        "fields": fields,
        "field_count": rule.get("field_count")
        or sum(len(v) for v in fields.values()),

        # 全局信息（coder 需要参考的；审计赋值已在 fields.assign 桶里，不再单列）
        "_global": {
            # 业务主键（coder 写 GROUP BY 时参考，确保不发散）
            "business_key": design.get("business_key", []),
            # 分布键（本表的，从 tables 段取）
            "distribution_key": dist_key,
            # 目标表 schema（从 meta 取）
            "target_schema": ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", ""),
            # 可用参数（coder 在 SELECT 里用 ${PARAM} 引用）
            "exec_params": ts.get("meta", {}).get("schedule", {}).get("exec_params", {}),
            # 数据量级（写法参考：亿级慎用行函数/跨键操作）
            "data_volume": (ts.get("design", {}).get("complexity_analysis") or {}).get("data_volume", ""),
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


def _compact_direct_field(f: dict, source_refs: dict = None) -> str:
    """把 direct 字段压成单行字符串。

    格式: target_field | field_type | direct | alias.src_field
    例: user_name | varchar(100) | direct | oub.user_name

    引用优先取 rule 级 source_refs（accumulate 同表多规则各归各的来源），
    缺失时退 source_fields[0]。都缺失 → placeholder（codegen 会标 TODO，不瞎生成）。
    """
    target = f.get("target_field", "")
    ftype = f.get("field_type", "")
    src_ref = (source_refs or {}).get(target, "")
    if not src_ref:
        sf_list = f.get("source_fields", [])
        if sf_list:
            sf = sf_list[0]
            alias = sf.get("alias", "")
            src = sf.get("field", "")
            src_ref = f"{alias}.{src}" if alias and src else "?"
        else:
            src_ref = "?"
    return f"{target} | {ftype} | direct | {src_ref}"


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



def slice_dq(ts: dict) -> dict:
    """切 DQ 规则段（dws-dq 流程用）——不整读 ts.json。

    内容：契约 + 目标表全名（检查对象）+ business_key（输出业务键列）
    + source_tables（资产级源表并集，跨表检查用）+ dq_rules 全量。
    dq_rules 为空时报错（执行计划 dq=true 才发起 DQ 任务，空=上游错位）。
    """
    dq_rules = ts.get("dq_rules") or []
    if not dq_rules:
        raise ValueError("ts.dq_rules 为空——DQ 切片无内容（执行计划 dq=true 才发起 DQ 任务，空=上游错位）")
    # 每条附 _file（UT 侧 dq_filename 同源派生的确定文件名）——coder 直接用它落盘，
    # 不自拼文件名（check_type 是检查类型不是规则身份会重名，自由文本清洗两侧难一致）
    dq_rules = [{**d, "_file": dq_filename(i, (d.get("check_type") or "").strip())}
                for i, d in enumerate(dq_rules, 1)]
    f_table = ts.get("meta", {}).get("target", {}).get("f_table", {}) or {}
    target = f"{f_table.get('schema', '')}.{f_table.get('table', '')}".strip(".")
    # 资产级源表并集（全规则 source_tables 按 schema+table+alias 去重）——
    # 跨表/源表级检查时 coder 要 schema 全名，切片不给就得回头读 ts.json
    seen: set = set()
    source_tables = []
    for r in (ts.get("rules") or {}).values():
        for st in (r.get("source_tables") or []):
            key = (st.get("schema", ""), st.get("table", ""), st.get("alias", ""))
            if key[1] and key not in seen:
                seen.add(key)
                source_tables.append({"schema": key[0], "table": key[1], "alias": key[2]})
    return {
        "contract": "DQ SELECT = 违规行探测器：0 行=通过，非 0 行=告警",
        "target_table": target,
        "business_key": ts.get("design", {}).get("business_key", []),
        "source_tables": source_tables,
        "dq_rules": dq_rules,
    }


def main():
    parser = argparse.ArgumentParser(
        description="TS 规则切片: 从 ts.json 切出单个规则的 YAML（给 coder 读）"
    )
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--rule", default="", help="规则编号，如 R0001（与 --dq 二选一）")
    parser.add_argument("--dq", action="store_true", help="切 DQ 规则段（dws-dq 流程用）")
    parser.add_argument("--output", default="", help="输出 YAML 路径（默认打印到 stdout）")
    parser.add_argument("--baseline-sql", default="",
                        help="优化模式：baseline SQL 文件路径（etl_baseline/{rule}.sql）——给定时切优化模式")
    args = parser.parse_args()

    if args.dq and args.rule:
        parser.error("--dq 与 --rule 互斥（DQ 任务不带规则号）")
    if not args.dq and not args.rule.strip():
        parser.error("--rule 与 --dq 必须给一个（规则编码或 DQ 切片）")
    if args.dq and args.baseline_sql:
        parser.error("--dq 与 --baseline-sql 互斥")

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
        if args.dq:
            sliced = slice_dq(ts)
        elif args.baseline_sql:
            bsql = Path(args.baseline_sql).read_text(encoding="utf-8")
            sliced = slice_rule_opt(ts, args.rule, baseline_sql=bsql)
        else:
            sliced = slice_rule(ts, args.rule, etl_dir=etl_dir)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 三桶即原生 compact 形态（direct 本就是一行一串），无需再压
    output_data = sliced

    # 输出
    yaml_text = yaml.dump(output_data, allow_unicode=True, default_flow_style=False, sort_keys=False)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml_text, encoding="utf-8")
        print(f"切片产出: {out}" + (" [DQ]" if args.dq else ""), file=sys.stderr)
        if args.dq:
            print(f"DQ 规则数: {len(sliced['dq_rules'])}", file=sys.stderr)
        else:
            print(f"规则: {args.rule}, 字段数: {sliced['field_count']}", file=sys.stderr)
    else:
        print(yaml_text)


if __name__ == "__main__":
    main()
