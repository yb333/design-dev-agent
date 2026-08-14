#!/usr/bin/env python3
"""golden seeding：从一次跑通的结果抽取事实，生成 checks.yaml 草稿。

用法:
    python eval-suite/v2/seed.py --case 002              # 输出草稿到 stdout
    python eval-suite/v2/seed.py --case 002 --review     # 写到 cases/002/checks.seeded.yaml

抽取规则（只抽取"事实明确"的，对错判断留给人）：
可自动 seed：
- business_key（design 层，从 ts.json）
- field_targets 覆盖（来自 rs_input，必然完整）
- JOIN 表集合（SQL 里实际关联的）
- GROUP BY 粒度（SQL 里有）
- source_tables（rs_input 里有）
- SELECT 输出字段（SQL 里有）

不能自动 seed（需人判断，草稿里留空带注释）：
- 是否该增量的判断
- 分段数是否最优
- distribution_key 是否最优
- join_safety 策略是否正确

风险对策：生成的草稿全部标 [AUTO-SEEDED]，需人工 review 后才固化。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_EVAL_SUITE = Path(__file__).resolve().parent.parent
_V2_DIR = Path(__file__).resolve().parent
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

ROOT = _EVAL_SUITE.parent
CASES_DIR = _EVAL_SUITE / "cases"
CASES_REAL_DIR = _EVAL_SUITE / "cases_real"
DELIVER_BASE = ROOT / "10_project_deliver"
UNCATEGORIZED = "未分类"  # deliver_only 案例的默认分类（后续可 mv 到合适分类）

# 复用 assert_sql 的提取函数（已兼容裸 SELECT）
import assert_sql  # noqa: E402
from _paths import find_select_file, find_deliver  # noqa: E402


def seed_case(case_dir: Path) -> str:
    """从案例产出抽取事实，返回 checks.yaml 草稿字符串。"""
    case_name = case_dir.name
    # 产出目录：平铺或 {appid}/{schema} 三层，find_deliver 统一定位
    deliver = find_deliver(DELIVER_BASE, case_name) or (DELIVER_BASE / case_name / "ddlc_design_dev")
    ts_path = deliver / "ts.json"
    rs_input_path = deliver / "_internal" / "rs_input.json"

    if not ts_path.exists():
        return f"# 错误: {ts_path} 不存在，请先跑流水线再 seed"

    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    rs_input = {}
    if rs_input_path.exists():
        rs_input = json.loads(rs_input_path.read_text(encoding="utf-8"))

    lines: list[str] = []
    lines.append(f"# [AUTO-SEEDED] {case_name} 断言草稿")
    lines.append(f"# 从产出 {deliver} 自动抽取，需人工 review 后固化到 checks.yaml")
    lines.append(f"# 带 [AUTO-SEEDED] 的条目未经确认，评测时只 WARN 不 FAIL")
    lines.append("")

    # case 段
    meta = ts.get("meta", {}).get("target", {})
    f_table = meta.get("f_table", {}).get("table", "")
    rules = list(ts.get("rules", {}).keys())
    lines.append("case:")
    lines.append(f'  name: "{case_name}"')
    lines.append(f'  target_table: "{f_table}"')
    lines.append(f"  rules_expected: {rules}")
    lines.append("")

    # artifacts 段（默认结构）
    lines.append("artifacts:")
    lines.append("  ts_json_top_keys: [version, meta, design, rules, data_flow]")
    lines.append("  audit_fields_count: 4")
    lines.append(
        "  audit_field_names: [del_flag, crt_cycle_id, last_upd_cycle_id, dw_last_update_date]"
    )
    lines.append("  each_rule_has_load_mode: true")
    lines.append("  ddl_rollback_paired: true")
    lines.append("  no_select_star_in_view: true")
    lines.append("")

    # design 段
    lines.append("design:")
    # business_key [AUTO-SEEDED]
    bk = ts.get("design", {}).get("business_key", [])
    if bk:
        lines.append(f"  business_key: {bk}  # [AUTO-SEEDED] 确认业务主键是否正确")
    else:
        lines.append("  business_key: []  # [AUTO-SEEDED] ts.json 无 business_key，需人工填")
    lines.append("  field_targets_cover_rs_input: true")
    lines.append("  field_targets_no_cross_rule_dup: true")
    lines.append("  load_mode_valid: true")
    lines.append("  join_safety_strategy_when_not_unique: true")
    lines.append("  segmentation_reason_when_segmented: true")

    # source_tables [AUTO-SEEDED]（来自 rs_input）
    sources = rs_input.get("source_tables", [])
    src_tables = []
    for st in sources:
        sch = st.get("source_schema", "")
        tbl = st.get("source_table", "")
        if sch and tbl:
            src_tables.append(f"{sch}.{tbl}")
    if src_tables:
        lines.append(f"  source_tables_required: {src_tables}  # [AUTO-SEEDED] 来自 rs_input")
    # 增量/分段/distribution_key 需人判断，留注释
    lines.append("  # 以下需人工判断（不自动 seed）：")
    lines.append("  # - 是否该增量（看 RS 增量识别字段）")
    lines.append("  # - 分段数是否最优")
    lines.append("  # - distribution_key 是否最优")
    lines.append("")

    # code 段（按规则，从 SELECT 抽取）
    lines.append("code:")
    for code in rules:
        select_file = find_select_file(deliver, code)
        if not select_file:
            lines.append(f"  {code}:  # [AUTO-SEEDED] SELECT 文件不存在，跳过")
            lines.append("    fields_required: []")
            continue

        sql_text = select_file.read_text(encoding="utf-8")
        fields = sorted(assert_sql._extract_select_columns(sql_text))
        join_tables = assert_sql._extract_join_tables(sql_text)
        groupby = sorted(assert_sql._extract_groupby_columns(sql_text))

        lines.append(f"  {code}:  # [AUTO-SEEDED] 从 {select_file.name} 抽取")
        lines.append(f"    fields_required: {fields}")
        if join_tables:
            lines.append(f"    join_tables: {join_tables}")
        if groupby:
            lines.append(f"    group_by_granularity: {groupby}  # 注意：提取的是源列名")
        lines.append("    case_when_must_have_else: true")
        lines.append("    no_select_star: true")
        lines.append("    audit_fields_in_select: true")

    return "\n".join(lines)


def _resolve_case_dir(case_arg: str, cases_dir: Path) -> Path | None:
    """解析用例目录：cases_dir 精确/前缀/二级分类匹配 → 回退 10_project_deliver 有产出。

    支持三种结构：
    - cases/{资产}/（假设案例，一级）
    - cases_real/{分类}/{资产}/（真实案例，二级分类）
    - 回退：10_project_deliver 有产出 → 建 cases_real/未分类/{资产}/ 占位
    """
    import re

    # 1. 一级精确匹配（目录存在即可，含占位目录）
    exact = cases_dir / case_arg
    if exact.is_dir():
        return exact
    # 2. 数字前缀（002 → 002_xxx）
    if re.match(r"^\d+$", case_arg) and cases_dir.exists():
        for d in sorted(cases_dir.iterdir()):
            if d.is_dir() and d.name.startswith(f"{case_arg}_"):
                return d
    # 3. 二级分类匹配（cases_real/{分类}/{case_arg}）
    if cases_dir.exists():
        for cat_dir in sorted(cases_dir.iterdir()):
            if not cat_dir.is_dir():
                continue
            candidate = cat_dir / case_arg
            if candidate.is_dir():
                return candidate
    # 4. 回退：10_project_deliver 有产出（平铺/三层）→ 建 cases_real/未分类/{case} 占位
    if find_deliver(DELIVER_BASE, case_arg):
        placeholder = CASES_REAL_DIR / UNCATEGORIZED / case_arg
        placeholder.mkdir(parents=True, exist_ok=True)
        print(f"  ℹ️ 用例 {case_arg} 无输入目录，已建占位 {placeholder}")
        print(f"     后续可补 mapping.xlsx + RS.md，并 mv 到合适分类")
        return placeholder
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="golden seeding：生成 checks.yaml 草稿")
    parser.add_argument("--case", required=True, help="用例（如 002）")
    parser.add_argument("--review", action="store_true", help="写到 cases/{case}/checks.seeded.yaml")
    parser.add_argument(
        "--cases-dir",
        default="",
        help="用例目录（默认 eval-suite/cases/；真实用例用 eval-suite/cases_real/）",
    )
    args = parser.parse_args()

    # 用例目录（默认 cases/，可指向 cases_real/）
    cases_dir = Path(args.cases_dir) if args.cases_dir else CASES_DIR

    case_dir = _resolve_case_dir(args.case, cases_dir)
    if not case_dir:
        print(f"用例不存在: {args.case}（在 {cases_dir} 和 {DELIVER_BASE} 都没找到）", file=sys.stderr)
        return 1

    draft = seed_case(case_dir)

    if args.review:
        out = case_dir / "checks.seeded.yaml"
        out.write_text(draft, encoding="utf-8")
        print(f"草稿已写到 {out}")
        print("请人工 review 后：1) 确认/修改各条目 2) 去掉 [AUTO-SEEDED] 标记")
        print("3) 覆盖 checks.yaml 固化为标准答案")
    else:
        print(draft)
    return 0


if __name__ == "__main__":
    sys.exit(main())
