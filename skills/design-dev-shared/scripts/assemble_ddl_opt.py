"""assemble_ddl_opt —— 优化模式 DDL 生成（docs/specs/opt/05 §七 DDL 两形态）。

产出（--outdir，一般 {deliver}）：
  ddl/alter_table_{表名}.sql   ★变更单（交付物）：ALTER ADD COLUMN + COMMENT，一表一文件
  ddl_full/create_table_*.sql  全量 DDL（档案推进用；复用 assemble_ddl.generate_ddl 从 ts_v2 生成，
                               json 路径无原 DDL 时即档案初始版）

差异校验（生成物也要被审计，v2.2）：全量 DDL 反映的字段增量必须**恰好等于**
change 段声明——多列=生成器带进了未声明的东西，少列=漏。fail loud。
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from assemble_ddl import generate_ddl


def build_alter_ddl(schema: str, table: str, additions: List[dict]) -> str:
    """一表一份 ALTER 变更单。additions: [{field, field_type, field_comment}]。"""
    full = f"{schema}.{table}" if schema else table
    lines = [f"-- ALTER 变更单：{full} 新增 {len(additions)} 列（add_field）",
             "-- 由 assemble_ddl_opt 生成；执行时机与顺序由人/平台决定（推生产不自主）"]
    for f in additions:
        ftype = f.get("field_type") or "VARCHAR(200)"
        lines.append(f"ALTER TABLE {full} ADD COLUMN {f['field']} {ftype};")
        if f.get("field_comment"):
            lines.append(f"COMMENT ON COLUMN {full}.{f['field']} IS '{f['field_comment']}';")
    return "\n".join(lines) + "\n"


def declared_additions_by_table(ts_v2: dict) -> Dict[str, List[dict]]:
    """change 段 → {表: 新增列清单}（目标表 + 中间表）。字段定义取 ts_v2 的 tables。"""
    out: Dict[str, List[dict]] = {}
    for f in (ts_v2.get("change") or {}).get("fields", []):
        for t in [f.get("target_table", "")] + list(f.get("intermediate_tables", [])):
            out.setdefault(t, []).append({
                "field": f["field"],
                "field_type": next((x.get("field_type", "") for x in
                                    ts_v2.get("tables", {}).get(t, {}).get("fields", [])
                                    if x.get("target_field") == f["field"]), ""),
                "field_comment": next((x.get("field_comment", "") for x in
                                       ts_v2.get("tables", {}).get(t, {}).get("fields", [])
                                       if x.get("target_field") == f["field"]), ""),
            })
    return out


def audit_full_ddl(ts_baseline: dict, ts_v2: dict) -> List[str]:
    """差异校验：ts_v2 相对 ts_baseline 的字段增量必须恰好等于 change 声明。"""
    problems = []
    declared = {t: {a["field"] for a in adds}
                for t, adds in declared_additions_by_table(ts_v2).items()}
    for t in set(ts_baseline.get("tables", {})) | set(ts_v2.get("tables", {})):
        bf = {x["target_field"] for x in ts_baseline.get("tables", {}).get(t, {}).get("fields", [])}
        vf = {x["target_field"] for x in ts_v2.get("tables", {}).get(t, {}).get("fields", [])}
        added, removed = vf - bf, bf - vf
        d = declared.get(t, set())
        if added - d:
            problems.append(f"[DDL审计] {t} 出现未声明的新列 {sorted(added - d)}")
        if d - added:
            problems.append(f"[DDL审计] {t} 声明的列未在全量 DDL 落地 {sorted(d - added)}")
        if removed:
            problems.append(f"[DDL审计] {t} 丢了列 {sorted(removed)}——add_field 不许删列")
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="优化模式 DDL：ALTER 变更单 + 全量 DDL 推进")
    ap.add_argument("--ts-v2", required=True)
    ap.add_argument("--ts-baseline", required=True)
    ap.add_argument("--outdir", required=True, help="交付目录（产出 ddl/ 与 ddl_full/）")
    args = ap.parse_args(argv)

    v2 = json.loads(Path(args.ts_v2).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.ts_baseline).read_text(encoding="utf-8"))

    problems = audit_full_ddl(baseline, v2)
    if problems:
        print("DDL_OPT_BLOCKED：差异校验不通过", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 2

    out = Path(args.outdir)
    (out / "ddl").mkdir(parents=True, exist_ok=True)
    (out / "ddl_full").mkdir(parents=True, exist_ok=True)

    # 1. ALTER 变更单（目标表 + 中间表，一表一文件）
    schema = v2["meta"]["target"]["f_table"]["schema"]
    n_alters = 0
    for t, adds in sorted(declared_additions_by_table(v2).items()):
        (out / "ddl" / f"alter_table_{t}.sql").write_text(
            build_alter_ddl(schema, t, adds), encoding="utf-8")
        n_alters += len(adds)

    # 2. 全量 DDL（档案推进用；复用 generate_ddl——ts_v2 是完整 ts）
    ddl_files, _ = generate_ddl(v2)
    for name, content in ddl_files.items():
        (out / "ddl_full" / name).write_text(content, encoding="utf-8")

    print(f"alter 变更单: {out / 'ddl'}（{n_alters} 列）")
    print(f"全量 DDL（档案）: {out / 'ddl_full'}（{len(ddl_files)} 文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
