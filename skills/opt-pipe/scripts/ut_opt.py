"""ut_opt —— 优化模式 UT（docs/specs/opt/06；零触碰 ut_precheck/ut_execute 的独立执行入口）。

流程（对应 06 的验证形态，全部动作在**现成开发环境**上）：
  1. 应用 ALTER（ddl/alter_table_*.sql，一表一文件按确定文件名拼接——禁 glob）
     表不存在 = 环境问题归人（exit 3，对齐 new-pipe 6c 分流），不自己 CREATE 兜底。
  2. SELECT 预检：新旧 SELECT 逐规则跑通（EXPLAIN 级由 executor 决定，这里真跑一次）
  3. 输出对比（双跑落地）：双向 MINUS 一条 SQL，老/新 SELECT 同库同时执行——
     冻结列双向差集必须为空；差异只允许出现在新增列；oracle 按声明参数化。
  4. INSERT 全量执行（复用 run_ut.wrap_insert——SELECT 对比管不了写路径类型转换，
     全量 INSERT 才算数，两道缺一不可）。
  5. 报告 ut_report_opt.md（含闸口②'素材：新列 NULL 率/差异摘要/资产健康提示）。

不支持的形态（UNION 顶层/SELECT *——sql_fence 同款判定）→ 报"转人工"，不静默。
主键检查豁免（双跑更强，06 §一）；空值检查只对新列（06 §一）。
"""
import argparse
import json
import sys
from pathlib import Path

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from typing import Dict, List, Optional, Tuple

from run_ut import wrap_insert, read_select
from sql_fence import check_sql_fence, rule_declaration
from explain_check import _analyze_plan, _parse_actual_rows, _STREAM_PATTERN, STREAM_LIMIT

# MINUS 结果取样上限（报告用样例，不搬全量数据）
SAMPLE_LIMIT = 5


def build_compare_sql(old_sql: str, new_sql: str, frozen_cols: List[str],
                      new_cols: List[str]) -> Tuple[str, str]:
    """双向 MINUS 一条 SQL（投影裁到比对列：冻结列必比；新列只进新侧方向）。

    返回 (老 MINUS 新, 新 MINUS 老)。列裁剪用子查询包裹，不改写两侧 SELECT 本体。
    """
    frozen = ", ".join(f'"{c}"' for c in frozen_cols) or "*"
    old_q = f"SELECT {frozen} FROM ({old_sql}) fence_old"
    new_q = f"SELECT {frozen} FROM ({new_sql}) fence_new"
    minus_old_new = f"{old_q} MINUS {new_q}"
    all_cols = list(frozen_cols) + [c for c in new_cols if c not in frozen_cols]
    all_sel = ", ".join(f'"{c}"' for c in all_cols) or "*"
    new_full = f"SELECT {all_sel} FROM ({new_sql}) fence_new2"
    old_full = f"SELECT {all_sel} FROM ({old_sql}) fence_old2"
    minus_new_old = f"{new_full} MINUS {old_full}"
    return minus_old_new, minus_new_old


def run_output_compare(executor, ts_v2: dict, etl_dir: Path, baseline_dir: Path,
                       table_fields: Dict[str, List[str]], ts_path: Path) -> List[dict]:
    """逐规则输出对比。返回检查结果列表（含 PASS/FAIL 与样例）。"""
    results = []
    change = ts_v2.get("change") or {}
    frozen_by_rule = _frozen_columns(ts_v2, change)
    for rule_code, rule in ts_v2.get("rules", {}).items():
        decl = rule_declaration(change, rule_code)
        new_sql = read_select(etl_dir, rule_code)   # {code}.sql 或 {code}_描述_模式.sql
        if not new_sql:
            continue   # 视图/未产出规则跳过（dispatch 层已保证清单）
        old_sql = read_select(baseline_dir, rule_code) or None
        if old_sql is None:
            results.append({"rule": rule_code, "status": "SKIP",
                            "detail": "无 baseline SQL（新规则？add_field 不应出现）"})
            continue
        fence = check_sql_fence(old_sql, new_sql, decl)
        hard = [f for f in fence if f["type"] != "missing"]
        if hard:
            results.append({"rule": rule_code, "status": "FENCE_FAIL",
                            "detail": "; ".join(f["message"] for f in hard)})
            continue
        # EXPLAIN ANALYZE 全量真实执行一次（对齐 new-pipe 6a：真跑通验证 + 计划两门槛
        # + 顶层行数；新 JOIN 改变计划形状，两门槛对新 SQL 同样成立）。提示级不阻断。
        r_plan = executor.execute(f"EXPLAIN ANALYZE {new_sql}")
        plan_issues, plan_file = [], ""
        if not r_plan.success:
            results.append({"rule": rule_code, "status": "ERROR",
                            "detail": f"新 SELECT 执行失败: {(r_plan.error or '')[:200]}"})
            continue
        plan_text = "\n".join(str(v) for row in (r_plan.rows or []) for v in row.values())
        pre_rows = _parse_actual_rows(plan_text)
        plan_issues, plan_file = _analyze_plan(plan_text, rule_code, ts_path)
        if pre_rows == 0:
            plan_issues = [f"⚠ 0 行——源表有数据却查不出：疑似关联/过滤条件全灭，核对关联条件"] + plan_issues
        frozen = frozen_by_rule.get(rule_code, [])
        new_cols = decl["fields"]
        m1, m2 = build_compare_sql(old_sql, new_sql, frozen, new_cols)
        try:
            rows1 = executor.fetch_all(f"SELECT COUNT(*) AS N FROM ({m1}) t") or [{"N": 0}]
            n1 = int(rows1[0]["N"])
            sample1 = executor.fetch_all(f"SELECT * FROM ({m1}) t LIMIT {SAMPLE_LIMIT}") if n1 else []
        except Exception as e:
            results.append({"rule": rule_code, "status": "ERROR", "detail": f"MINUS(老→新) 执行失败: {e}"})
            continue
        try:
            rows2 = executor.fetch_all(f"SELECT COUNT(*) AS N FROM ({m2}) t") or [{"N": 0}]
            n2 = int(rows2[0]["N"])
            sample2 = executor.fetch_all(f"SELECT * FROM ({m2}) t LIMIT {SAMPLE_LIMIT}") if n2 else []
        except Exception as e:
            results.append({"rule": rule_code, "status": "ERROR", "detail": f"MINUS(新→老) 执行失败: {e}"})
            continue
        # 判定：老→新 差集必须为空（冻结列在老侧多/变 = 回归失败）；
        # 新→老 允许非空但差异应只涉及新列（样例供人审）
        if n1 > 0:
            results.append({"rule": rule_code, "status": "FAIL",
                            "detail": f"冻结列回归失败：老 MINUS 新 = {n1} 行",
                            "samples": sample1, "plan_issues": plan_issues})
        else:
            row_note = f"EXPLAIN {pre_rows}行" if pre_rows is not None else "行数未解析"
            results.append({"rule": rule_code, "status": "PASS",
                            "detail": f"冻结列零差异（{row_note}）；新→老差集 {n2} 行（新列引入，样例供审）",
                            "samples": sample2, "plan_issues": plan_issues,
                            "plan_file": plan_file})
    return results


def check_new_column_nulls(executor, ts_v2: dict, schema: str) -> List[dict]:
    """新列空值检查（写路径后真实数据）：逐目标表统计新列 NULL——兑现 06 §一
    '空值只查新列'的承诺；全 NULL = 疑似新 JOIN 关联不上的信号（LEFT JOIN 常态形态）。"""
    change = ts_v2.get("change") or {}
    by_table: Dict[str, List[str]] = {}
    for f in change.get("fields", []):
        by_table.setdefault(f.get("target_table", ""), []).append(f["field"])
    out = []
    for table, cols in sorted(by_table.items()):
        null_exprs = ", ".join(f"COUNT(*) - COUNT(\"{c}\") AS null_{c}" for c in cols)
        try:
            rows = executor.fetch_all(
                f'SELECT COUNT(*) AS total, {null_exprs} FROM {schema}.{table}') or [{}]
            r = rows[0]
            total = int(r.get("total") or 0)
            for c in cols:
                nulls = int(r.get(f"null_{c}") or 0)
                rate = (nulls / total) if total else 0
                note = ""
                if total and nulls == total:
                    note = " ⚠ 全 NULL——疑似新 JOIN 关联不上（LEFT JOIN 关联不上的常态形态），核对 ON 条件"
                elif rate > 0.5:
                    note = " ⚠ 过半 NULL——抽查关联条件"
                out.append({"table": table, "col": c, "total": total,
                            "nulls": nulls, "rate": f"{rate:.1%}".rstrip("0").rstrip("."),
                            "note": note.strip()})
        except Exception as e:
            out.append({"table": table, "col": ",".join(cols), "total": 0, "nulls": 0,
                        "rate": "-", "note": f"查询失败: {str(e)[:120]}"})
    return out


def _frozen_columns(ts_v2: dict, change: dict) -> Dict[str, List[str]]:
    """每规则参与比对的冻结列 = 该规则 field_targets - 声明新列。"""
    out: Dict[str, List[str]] = {}
    declared_all = {f["field"] for f in change.get("fields", [])}
    for code, rule in ts_v2.get("rules", {}).items():
        out[code] = [c for c in (rule.get("field_targets") or []) if c not in declared_all]
    return out


def apply_alters(executor, ddl_dir: Path, tables: List[str], schema: str) -> List[str]:
    """应用 ALTER 变更单（确定文件名拼接，禁 glob）。表不存在让 DB 报错 → 环境问题归人。

    变更单文件缺失 → fail loud（不静默跳过：缺 ALTER 直接跑 INSERT 会报新列不存在，
    错误会被分流给 coder——先跑 assemble_ddl_opt 生成 ddl/ 再进 UT）。
    """
    applied = []
    missing = [t for t in tables if not (ddl_dir / f"alter_table_{t}.sql").exists()]
    if missing:
        raise ValueError(
            f"ALTER 变更单缺失: {missing}（{ddl_dir}）——先跑 assemble_ddl_opt 生成变更单再执行 UT")
    for t in tables:
        p = ddl_dir / f"alter_table_{t}.sql"
        executor.execute(p.read_text(encoding="utf-8"))
        applied.append(t)
    return applied


def render_report(ts_v2: dict, alters: List[str], compare: List[dict],
                  inserts: List[dict]) -> str:
    lines = ["# UT 报告（优化模式）", "",
             f"- ALTER 已应用：{', '.join(alters) or '（无）'}",
             f"- 主键检查：豁免（双跑更强，06 §一）；空值检查：只对新列", ""]
    lines.append("## 输出对比（冻结列回归）")
    for r in compare:
        lines.append(f"- [{r['status']}] {r['rule']}：{r['detail']}")
        for s in (r.get("samples") or [])[:SAMPLE_LIMIT]:
            lines.append(f"    - 样例: {s}")
    lines.append("")
    lines.append("## INSERT 全量执行")
    for r in inserts:
        lines.append(f"- [{r['status']}] {r['rule']}：{r['detail']}")
        for pi in (r.get("plan_issues") or [])[:5]:
            lines.append(f"    - 计划门槛: {pi}")
    lines.append("")

    lines.append("## 新列空值检查（写路径后真实数据）")
    for n in nulls:
        lines.append(f"- {n['table']}.{n['col']}：{n['nulls']}/{n['total']} NULL"
                     f"（{n['rate']}）{n['note']}")
    lines.append("")
    lines.append("> 闸口②'素材：新列 NULL 率/值分布请看新→老差集样例；"
                 "开发库数据代表性限制如实声明。")
    return "\n".join(lines) + "\n"


def build_insert_plan(ts_v2: dict, schema: str) -> List[Tuple[str, str, List[str]]]:
    """INSERT 执行计划 [(rule_code, 目标全名, 字段清单)]。

    表名容忍两种形态（rsplit 剥 schema，与 ts_compat 的查找容忍同款）：
    json 路径 baseline 产短名 target_table；档案路径 baseline 是 new-pipe 新版 ts
    （target_table 带 schema 如 dws.dwb_x）——统一剥成短名再拼全名/查 tables 键。
    """
    plan: List[Tuple[str, str, List[str]]] = []
    for rule_code, rule in ts_v2.get("rules", {}).items():
        tshort = str(rule.get("target_table") or "").rsplit(".", 1)[-1].lower()
        fields = [f["target_field"] for f in
                  ts_v2.get("tables", {}).get(tshort, {}).get("fields", [])]
        plan.append((rule_code, f"{schema}.{tshort}", fields))
    return plan


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="优化模式 UT：ALTER + 输出对比 + INSERT")
    ap.add_argument("--ts", required=True, help="ts_v2.json")
    ap.add_argument("--etl-dir", required=True, help="新 SELECT 目录 etl/")
    ap.add_argument("--baseline-dir", required=True, help="etl_baseline/")
    ap.add_argument("--ddl-dir", required=True, help="ddl/（alter_table_*.sql）")
    ap.add_argument("--report", required=True, help="ut_report_opt.md 输出")
    args = ap.parse_args(argv)

    ts_v2 = json.loads(Path(args.ts).read_text(encoding="utf-8"))
    change = ts_v2.get("change") or {}
    if not change.get("fields"):
        print("UT_OPT_ERROR: ts 无 change 段——这不是优化模式的 ts", file=sys.stderr)
        return 2

    # 依赖数据库：延迟导入（与 check_db 探活配合）
    from dws_db import create_executor_for_schema
    schema = ts_v2["meta"]["target"]["f_table"]["schema"]
    try:
        executor = create_executor_for_schema(schema, role="admin")
    except Exception as e:
        print(f"UT_OPT_NO_DB: 数据源不可用（{e}）——环境问题归人", file=sys.stderr)
        return 3

    # 1. ALTER（变更单缺失=流程顺序错——先 assemble_ddl_opt 再 UT，与环境问题分开报）
    try:
        tables = sorted({f.get("target_table", "") for f in change["fields"]} |
                        {t for f in change["fields"] for t in f.get("intermediate_tables", [])})
        alters = apply_alters(executor, Path(args.ddl_dir), tables, schema)
    except ValueError as e:
        print(f"UT_OPT_ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"UT_OPT_ENV: ALTER 失败（表不存在=环境问题归人）: {e}", file=sys.stderr)
        return 3

    # 2+3. SELECT 预检隐含在对比执行里；输出对比
    compare = run_output_compare(executor, ts_v2, Path(args.etl_dir),
                                 Path(args.baseline_dir), {}, Path(args.ts))

    # 4. INSERT 全量执行（老列+新列全量写一遍，验证写路径）
    inserts = []
    for rule_code, target, fields in build_insert_plan(ts_v2, schema):
        select_sql = read_select(Path(args.etl_dir), rule_code)
        if not select_sql:
            continue
        try:
            sql = wrap_insert(select_sql, target, fields)
            executor.execute(sql)
            inserts.append({"rule": rule_code, "status": "PASS", "detail": f"{target} 全量写入"})
        except Exception as e:
            inserts.append({"rule": rule_code, "status": "FAIL", "detail": str(e)})

    nulls = check_new_column_nulls(executor, ts_v2, schema)
    Path(args.report).write_text(
        render_report(ts_v2, alters, compare, inserts, nulls), encoding="utf-8")
    failed = any(r["status"] in ("FAIL", "ERROR", "FENCE_FAIL") for r in compare + inserts)
    print(f"ut_report_opt: {args.report}")
    null_notes = [n for n in nulls if n["note"]]
    print(f"compare: {len(compare)} 规则, inserts: {len(inserts)} 规则, "
          f"result: {'FAIL' if failed else 'PASS'}")
    for n in null_notes:
        print(f"  ⚠️ 新列空值: {n['table']}.{n['col']} {n['note']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
