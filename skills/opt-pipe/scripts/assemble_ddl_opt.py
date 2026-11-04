"""assemble_ddl_opt —— 优化模式 DDL 生成（docs/specs/opt/05 §七 DDL 两形态）。

产出（--outdir，一般 {deliver}）：
  ddl/alter_table_{表名}.sql   ★变更单（交付物）：ALTER ADD COLUMN + COMMENT，一表一文件
  ddl_rollback/rollback_*.sql  回退脚本（2026-11-04 UT 幂等补环——变更的逆：
                               存量表 TRUNCATE+列级结构逆 / 新表 DROP；build 现场
                               件不进档案——adopt/advance 拷贝清单不含 ddl_rollback）
  ddl_full/create_table_*.sql  全量 DDL（档案推进用；复用 assemble_ddl.generate_ddl 从 ts_v2 生成，
                               json 路径无原 DDL 时即档案初始版）

差异校验（生成物也要被审计，v2.2）：全量 DDL 反映的字段增量必须**恰好等于**
change 段声明——多列=生成器带进了未声明的东西，少列=漏。fail loud。
"""
import argparse
import json
import sys
from pathlib import Path

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from typing import Dict, List, Optional

from assemble_ddl import generate_ddl


def build_alter_ddl(schema: str, table: str, additions: List[dict],
                    modifies: List[dict] | None = None) -> str:
    """一表一份 ALTER 变更单。additions: [{field, field_type, field_comment}]；
    modifies（场景 B·2026-10-22）: [{field, old_type, new_type}]——DWS 的 MODIFY
    语法自动转换存量值（跨大类/收窄已在 precheck_opt 人决策）。"""
    full = f"{schema}.{table}" if schema else table
    modifies = modifies or []
    head = f"新增 {len(additions)} 列"
    if modifies:
        head += f" + 类型修改 {len(modifies)} 列"
    lines = [f"-- ALTER 变更单：{full} {head}（add_field"
             + (" + modify_type" if modifies else "") + "）",
             "-- 由 assemble_ddl_opt 生成；执行时机与顺序由人/平台决定（推生产不自主）"]
    for f in additions:
        ftype = f.get("field_type") or "VARCHAR(200)"
        lines.append(f"ALTER TABLE {full} ADD COLUMN {f['field']} {ftype};")
        if f.get("field_comment"):
            lines.append(f"COMMENT ON COLUMN {full}.{f['field']} IS '{f['field_comment']}';")
    for m in modifies:
        lines.append(f"ALTER TABLE {full} MODIFY ({m['field']} {m.get('new_type', '')});")
    return "\n".join(lines) + "\n"


def build_rollback_ddl(schema: str, table: str, additions: List[dict],
                       modifies: List[dict] | None = None,
                       is_new_table: bool = False) -> str:
    """一表一份回退脚本（UT 重跑幂等——2026-11-04 用户定调：回退=**变更的逆**，
    不是整表回退；TRUNCATE 空表起步=与新建 UT 统一语义——merge 两分支由幂等
    第二遍覆盖，dev 库不复现生产历史从来不是 UT 承诺）。

    - 存量表：TRUNCATE（数据回退）+ 结构逆（add_field/审计缺口列 DROP COLUMN、
      modify_type 还原旧类型——old_type 照抄 change 声明）
    - 新表（baseline 没有的中间表）：DROP TABLE
    ★ 位置：build/ddl_rollback/ 现场件——adopt/advance 拷贝清单不含它，
    资产档案零回退（与 new-pipe 同构：回退属变更生命周期不属资产）。"""
    full = f"{schema}.{table}" if schema else table
    if is_new_table:
        return (f"-- 回退脚本（UT 重跑幂等）：DROP 新表 {full}\n"
                f"DROP TABLE IF EXISTS {full};\n")
    lines = [f"-- 回退脚本（UT 重跑幂等）：{full} 回到变更前状态（列级逆——不整表回退）",
             "-- UT 语义=空表起步全量装载（与新建一致）；由 assemble_ddl_opt 生成",
             f"TRUNCATE TABLE {full};"]
    for f in additions:
        lines.append(f"ALTER TABLE {full} DROP COLUMN {f['field']};")
    for m in modifies or []:
        lines.append(f"ALTER TABLE {full} MODIFY ({m['field']} {m.get('old_type', '')});")
    return "\n".join(lines) + "\n"


def declared_modifies_by_table(ts_v2: dict) -> Dict[str, List[dict]]:
    """change.modify_types 段 → {表: 类型修改清单}（场景 B·2026-10-22——变更单锚）。"""
    out: Dict[str, List[dict]] = {}
    for m in (ts_v2.get("change") or {}).get("modify_types", []):
        out.setdefault(m.get("target_table", ""), []).append(
            {"field": m.get("field", ""), "old_type": m.get("old_type", ""),
             "new_type": m.get("new_type", "")})
    return out


def audit_additions_by_table(raw_baseline: dict, ts_v2: dict) -> Dict[str, List[dict]]:
    """物理审计缺口：原始 baseline（不 normalize——物理事实）tables 缺的标准审计列。

    2026-09-15 审计定调：存量表物理上补齐审计列=底层标准化不是资产变更——
    自动进 ALTER 变更单（不占 change 声明、不算围栏越界）。幂等：物理已有则零缺口。
    """
    from dws_standards import STANDARD_AUDIT_TEMPLATE
    out: Dict[str, List[dict]] = {}
    for t, tcfg in (raw_baseline.get("tables") or {}).items():
        if not isinstance(tcfg, dict):
            continue
        have = {str(x.get("target_field", "")).lower()
                for x in (tcfg.get("fields") or []) if isinstance(x, dict)}
        for aname, spec in STANDARD_AUDIT_TEMPLATE.items():
            if aname not in have and t in (ts_v2.get("tables") or {}):
                out.setdefault(t, []).append({
                    "field": aname,
                    "field_type": spec.get("type", ""),
                    "field_comment": spec.get("comment", ""),
                })
    return out


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
    """差异校验：ts_v2 相对 ts_baseline 的字段增量必须恰好等于 change 声明。

    两侧先 normalize（2026-09-15 审计定调）：审计补齐=每表强制标准列（底层标准
    非资产变更）——对称补齐后审计差为零，diff 只剩业务增量；物理列的审计补齐
    由 audit_additions 单独进变更单（以原始 baseline 为物理基准）。"""
    from ts_compat import normalize_ts
    ts_baseline = normalize_ts(ts_baseline)
    ts_v2 = normalize_ts(ts_v2)
    problems = []
    declared = {t: {a["field"] for a in adds}
                for t, adds in declared_additions_by_table(ts_v2).items()}
    for t in set(ts_baseline.get("tables", {})) | set(ts_v2.get("tables", {})):
        bf = {x["target_field"] for x in ts_baseline.get("tables", {}).get(t, {}).get("fields", [])}
        vf = {x["target_field"] for x in ts_v2.get("tables", {}).get(t, {}).get("fields", [])}
        added, removed = vf - bf, bf - vf
        d = declared.get(t, set())
        # 审计列豁免（2026-11-04 对齐 2026-09-15 定调：审计补齐=底层标准非资产变更，
        # 永不算"未声明新列"——不依赖 normalize 路径[标准形态快速路径不补审计]；
        # 物理补齐仍由 audit_additions 进变更单，以原始 baseline 为基准）
        from dws_standards import STANDARD_AUDIT_NAMES
        if added - d - set(STANDARD_AUDIT_NAMES):
            problems.append(f"[DDL审计] {t} 出现未声明的新列 {sorted(added - d - set(STANDARD_AUDIT_NAMES))}")
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

    # 1. ALTER 变更单（目标表 + 中间表，一表一文件；DDL 交付物只有变更单——
    #    全量建表 DDL 是 ts 的可再生投影不入交付不入档案，2026-09-04 裁决）
    schema = v2["meta"]["target"]["f_table"]["schema"]
    n_alters = 0
    # 变更单 = change 声明增量 ∪ 物理审计缺口（存量表补齐标准审计列——底层标准）
    _adds_by_table = declared_additions_by_table(v2)
    for t, audit_adds in audit_additions_by_table(baseline, v2).items():
        _adds_by_table.setdefault(t, []).extend(audit_adds)
    _mods_by_table = declared_modifies_by_table(v2)
    for t in sorted(set(_adds_by_table) | set(_mods_by_table)):
        (out / "ddl" / f"alter_table_{t}.sql").write_text(
            build_alter_ddl(schema, t, _adds_by_table.get(t, []),
                            _mods_by_table.get(t, [])), encoding="utf-8")
        n_alters += len(_adds_by_table.get(t, [])) + len(_mods_by_table.get(t, []))

    # 2. I 视图重建 DDL（F 表加列后镜像须同步——CREATE OR REPLACE 全量重建是语法
    #    结构决定的真交付物；复用 generate_i_view 单源，ts_v2.tables 已含新列）
    f_table = v2["meta"]["target"]["f_table"]
    i_view = v2["meta"]["target"].get("i_view") or {}
    n_view = 0
    if (i_view.get("table") or "").strip():
        from assemble_ddl import generate_i_view
        f_short = f_table["table"]
        view_sql = generate_i_view(f_table["schema"], f_short, f_table.get("cn", ""),
                                   v2["tables"][f_short]["fields"])
        (out / "ddl" / f"create_or_replace_view_{i_view['table']}.sql").write_text(
            view_sql, encoding="utf-8")
        n_view = 1

    print(f"alter 变更单: {out / 'ddl'}（{n_alters} 列）")
    if n_view:
        print(f"I 视图重建: {out / 'ddl'}/create_or_replace_view_{i_view['table']}.sql")

    # 3. 回退脚本（2026-11-04 UT 幂等补环）：变更的逆——存量表 TRUNCATE+列级结构逆，
    #    新表 DROP。覆盖面=alter 表 ∪ 全部规则目标表（UT 写路径全量装载——TRUNCATE
    #    保证重跑不累积；纯 truncate_table 规则的写前清理与回退幂等重合无害）
    rb_dir = out / "ddl_rollback"
    rb_dir.mkdir(parents=True, exist_ok=True)
    _baseline_tables = set((baseline.get("tables") or {}).keys())
    _rb_tables = set(_adds_by_table) | set(_mods_by_table) | {
        str(r.get("target_table", "")).rsplit(".", 1)[-1]
        for r in (v2.get("rules") or {}).values() if r.get("target_table")}
    _rb_tables &= set((v2.get("tables") or {}).keys())   # 只物理表（视图不可 TRUNCATE）
    n_rb = 0
    for t in sorted(_rb_tables):
        is_new = t not in _baseline_tables
        (rb_dir / f"rollback_create_table_{t}.sql" if is_new
         else rb_dir / f"rollback_alter_{t}.sql").write_text(
            build_rollback_ddl(schema, t, _adds_by_table.get(t, []),
                               _mods_by_table.get(t, []), is_new_table=is_new),
            encoding="utf-8")
        n_rb += 1
    print(f"rollback 回退脚本: {rb_dir}（{n_rb} 表——build 现场件，档案零回退）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
