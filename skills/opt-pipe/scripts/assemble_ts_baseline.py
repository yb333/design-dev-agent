"""assemble_ts_baseline —— ts 草稿建档（v2 契约=最终形态；v1 facts 路径已退役）。

2026-11-04 一波换彻底：契约 v2.1 双侧落地，v1 全路径（facts→build_ts_baseline
组装/kind 词表/拓扑推导/v1 渲染）同提交删除——建档唯一职责=**ts 草稿复制**
（audit_ingest 审核过后的动作）：契约进门验（我方权威 schema v2.1）+ 资产对账
+ 守门 + 逐字 copy（ts.json=草稿原样/etl=query_sql 逐字/export=provenance 拷贝/
MANIFEST 首条）。产物必须是 ts 草稿（facts --format ts_draft）；交 asset_facts
json 一律 fail loud 指引。
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# shared 公共库自洽引用：相对路径推算 design-dev-shared（首档 ts.md 渲染器 render_md）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))







# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def copy_artifacts_from_provenance(data: dict, archive_dir: Path) -> List[str]:
    """按产物 provenance[] 拷原始制品入 archive/export/（patch 底本，保原文件名）。

    facts 模式（无 manifest 文件）的拷贝通道：provenance 逐条 {type, path[, sheets]}——
    拷 execution_tasks / lts / dq（excel 制品；.sql DDL 不拷=档案 ddl/ 由 ts 投影）。
    缺 path/文件不存在 → 报告行披露（不阻断）。"""
    import shutil as _sh
    report: List[str] = []
    export = archive_dir / "export"
    export.mkdir(parents=True, exist_ok=True)
    for pv in (data.get("provenance") or []):
        ptype = str(pv.get("type") or "")
        path = str(pv.get("path") or "")
        if ptype not in ("execution_tasks", "lts", "dq") or not path:
            continue
        src = Path(path)
        if not src.exists():
            report.append(f"export/ 跳过 {ptype}: 源文件不存在 {path}（披露——patch 时问人）")
            continue
        _sh.copy2(src, export / src.name)
        report.append(f"export/ <- {ptype}: {src.name}")
    return report


def copy_artifacts_to_export(manifest_path: Path, archive_dir: Path) -> List[str]:
    """按 manifest 的 artifacts 清单拷原始制品入 archive/export/（patch 底本，保留原文件名）。

    2026-10-14 编排合入补全：首优制品经手一次入档（幂等全图）；DDL 原始文件不拷
    （档案 ddl/ 由 ts 投影生成）。返回拷贝报告行（stdout 披露）；manifest 缺失/无
    artifacts 段 → 空报告（直交通道场景，跳过不阻断）。
    """
    report: List[str] = []
    if not manifest_path or not manifest_path.exists():
        return report
    mf = json.loads(manifest_path.read_text(encoding="utf-8"))
    arts = mf.get("artifacts") or {}
    export = archive_dir / "export"
    export.mkdir(parents=True, exist_ok=True)
    for key in ("execution_tasks", "lts"):
        p = arts.get(key)
        if p and Path(p).exists():
            shutil.copy2(p, export / Path(p).name)
            report.append(f"export/ <- {key}: {Path(p).name}")
    dq = arts.get("dq") or {}
    if dq.get("status") == "provided":
        p = dq.get("path")
        if p and Path(p).exists():
            shutil.copy2(p, export / Path(p).name)
            report.append(f"export/ <- dq: {Path(p).name}")
    # declared_absent / 缺省：无文件可拷（"无 DQ"声明已由 baseline_v1.dq_rules=[] 携带）
    return report


def _archive_ts_draft(draft: dict, args) -> int:
    """v2 ts 草稿建档：契约进门验（我方权威 schema v2.1）+ 资产对账 + 守门 + **copy**。

    - ts.json = 草稿**逐字落档**（_reverse 段随档——档案单文件自足；消费端围栏/UT/
      切片天然忽略下划线段）；etl/{rule}.sql = rules[].query_sql 逐字（coder 底稿/
      SQL 围栏基准）；export/ = _baseline.provenance 拷制品（同 v1 通道）；MANIFEST
      首条 v2。无 exemptions/build_ts_baseline——草稿即档形态，装配北移逆向侧。
    """
    import jsonschema
    schema = json.loads((Path(__file__).resolve().parent.parent / "schemas"
                         / "ts_draft_v2.schema.json").read_text(encoding="utf-8"))
    errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(draft),
                  key=lambda e: list(e.path))
    if errs:
        print("[TS_DRAFT_CONTRACT_VIOLATION] v2 契约进门验不通过，拒绝建档：", file=sys.stderr)
        for e in errs:
            print(f"  {'/'.join(map(str, e.path)) or '<root>'}: {e.message[:160]}", file=sys.stderr)
        return 2
    f_table = (draft.get("meta", {}).get("target", {}) or {}).get("f_table", {}) or {}
    if args.asset:
        from baseline_contract import norm_asset
        _got = f"{f_table.get('schema', '')}.{f_table.get('table', '')}"
        if norm_asset(_got) != norm_asset(args.asset):
            print(f"[TS_DRAFT_CONTRACT_VIOLATION] 资产对账不通过：产物 {_got!r} ≠ 本次 {args.asset!r}",
                  file=sys.stderr)
            return 2
    archive, internal = Path(args.archive_dir), Path(args.internal_dir)
    if (archive / "ts.json").exists():
        print(f"[BASELINE_CONTRACT_VIOLATION] 拒绝建档：{archive} 已是确认档案——覆盖重入料=线上被外力"
              "改过/推倒重来（人发起的重建），本脚本不自动覆盖", file=sys.stderr)
        return 2
    (archive / "etl").mkdir(parents=True, exist_ok=True)
    internal.mkdir(parents=True, exist_ok=True)
    prov = (draft.get("_baseline") or {}).get("provenance") or []
    if prov:
        for line in copy_artifacts_from_provenance({"provenance": prov}, archive):
            print(line)
    (archive / "MANIFEST.md").write_text(
        f"# 资产演进索引 · {f_table.get('schema','')}.{f_table.get('table','')}\n\n"
        "（当前态 = archive/ 本体；此文件为版本史一眼索引，完整历史在 git）\n\n"
        "| 版本 | 内容 |\n|------|------|\n"
        "| v1 | 逆向入料建档（ts 草稿 v2 契约 → 审核确认后逐字落档，经 audit_ingest）|\n",
        encoding="utf-8")
    # DQ 明细剥出独立 dq.json（2026-11-11 R2 契约接通）：草稿 dq 段=传输容器（平台制品
    # 零翻译投影），建档剥出对齐正向「dq.json 唯一源」形态——ts 本体不带 DQ；dq_impact
    # 由此接通（rule_number=平台编码=条目身份键，锚定无声明时从 sql 粗提兜底）。
    # ★文件成对落盘（2026-11-11 UT 缺环补齐）：sql 逐字落 archive/dq/{rule_number}.sql
    # +条目注入 sql_file——UT 的 run_dq_checks 按 sql_file 找文件（读侧零适配），
    # 对齐正向档案形态（dq.json+dq/ 成对，adopt 同款）；UT DQ 段跑全部条目
    # （空表起步全量重算后验证「变更后数据仍满足全部约束」——含存量约束，
    # dq_impact 锚定粗提的兜底）。剥段在 ts.json 落盘前（分拣非改写——ts 核心段仍逐字）。
    dq_rules = draft.pop("dq", None) or []
    (archive / "ts.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if dq_rules:
        (archive / "dq").mkdir(exist_ok=True)
        for r in dq_rules:
            rn = str(r.get("rule_number") or "").strip()
            if rn:
                (archive / "dq" / f"{rn}.sql").write_text(
                    (r.get("sql") or "").rstrip() + "\n", encoding="utf-8")
                r["sql_file"] = f"{rn}.sql"
        (archive / "dq.json").write_text(
            json.dumps({"meta": {"source": "reverse_draft",
                                 "note": "平台制品零翻译投影；rule_number=身份键永不重编"},
                        "rules": dq_rules},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"建档 DQ: {archive / 'dq.json'}（{len(dq_rules)} 条——平台形态，SQL 文件成对落 dq/）")
    for code, r in sorted((draft.get("rules") or {}).items()):
        (archive / "etl" / f"{code}.sql").write_text(str(r.get("query_sql") or ""),
                                                     encoding="utf-8")
    # 首档 ts.md（2026-11-04 档案成对契约：ts.json/ts.md 不留空窗）——渲染器
    # shared/render_md 对逆向形态降级容错（design 段渲染占位「待首轮优化还原」，
    # 结构/规则段完整呈现）；首轮 opt designer 还原 baseline_design 后随 advance 变实
    from render_md import render_md
    _short = f_table.get("table") or "ts"
    (archive / f"{_short}_ts.md").write_text(render_md(draft), encoding="utf-8")
    from preprocess_opt import render_baseline_view_from_ts
    (internal / "baseline_view.md").write_text(
        render_baseline_view_from_ts(draft), encoding="utf-8")
    sc = (draft.get("_reverse") or {}).get("self_check") or {}
    print(f"archive ts: {archive / 'ts.json'}（v2 草稿逐字落档，零解析）")
    print(f"rules: {len(draft.get('rules') or {})}，etl 逐字落盘；"
          f"self_check={sc.get('verdict', '?')}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="ts 草稿建档（契约 v2=最终形态；审核后复制，零解析）")
    ap.add_argument("--baseline", required=True, help="ts 草稿 json 路径（facts 产物——ts 草稿=唯一契约形态）")
    ap.add_argument("--archive-dir", required=True, help="档案目录（ddlc_design_dev/archive/）")
    ap.add_argument("--internal-dir", required=True, help="过程目录（ddlc_design_dev/opt/_internal/）")
    ap.add_argument("--manifest", default=None, help="逆向侧的制品清单文件（可选：给则按清单拷原始制品入 archive/export/）")
    ap.add_argument("--asset", default="", help="资产对账（schema.table，probe 推出——与产物 asset 段比对，不一致=串包拒收；缺省跳过）")
    args = ap.parse_args(argv)

    data = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    if not (data.get("spec_type") == "ts" and str(data.get("version", "")).startswith("2.")):
        print("[TS_DRAFT_CONTRACT_VIOLATION] v1 facts 产物已退役（2026-11-04 一波换彻底——"
              "契约 v2.1 双侧落地，v1 入料路径删除）：产物必须是 ts 草稿"
              "（`run.py facts --dir <制品目录> --output <路径>`——参数只有"
              " --dir/--output），不接受 asset_facts json。", file=sys.stderr)
        return 2
    return _archive_ts_draft(data, args)


if __name__ == "__main__":
    sys.exit(main())
