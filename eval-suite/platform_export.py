#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内网评测平台导入集/评估集一键构造器（2026-09-22）。

平台两种形态，同一份原料：

  quick   快速评估导入：行级带 metric_name（评估器随行走）——8 列模板
  dataset 评估集构建：无 metric_name（评估器在评估任务层选）+ retrieval_context

本地试点 → 平台口径确认 → 内网真实案例，同一条命令：

  # 本地试点·快速评估导入（quick）
  python3 platform_export.py --source archive --root ../10_project_deliver
  # 评估集（dataset，后续主形态：评估任务固定，资产=评估集）
  python3 platform_export.py --source archive --root ../10_project_deliver --mode dataset
  # 内网真实案例：--root 换内网 10_project_deliver（兼容老式平铺与 build/ 新布局）

产物一件（平台只收 Excel）：
  out/platform_[import|dataset][_intranet].xlsx   平台导入文件

数据语义：input / expected_output = 案例设计侧构造（任务指令 + 完成标准清单）；
actual_output = 真实运行档案摘录（ts.md §1 概述 + 产物文件原文）；
retrieval_context（dataset 模式）= rs_input 映射清单摘要——对 agent 而言"检索到的上下文"
就是 RS/mapping 输入材料，语义同源。不编造输出。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ── 平台口径（唯一调整点：平台确认表头全集/指标合法值后只改这里）─────────
# quick=快速评估导入模板（行级带 metric_name）
QUICK_COLUMNS = [
    "metric_name",
    "input",
    "actual_output",
    "expected_output",
    "trace",
    "turns",
    "tools_called",
    "expected_tools",
]
# dataset=评估集（无 metric_name——评估器在评估任务层选；多 retrieval_context）
DATASET_COLUMNS = [
    "input",
    "actual_output",
    "expected_output",
    "retrieval_context",
    "trace",
    "turns",
    "tools_called",
    "expected_tools",
]
DEFAULT_METRIC_NAME = "任务成功率"  # ← quick 模式专用，换成平台评估器的准确名称

CAP_INPUT = 1200
CAP_ACTUAL = 26000  # 平台只认 Excel 这一格——产物原文全量嵌入（实测最大案例 raw 21845；Excel 单格硬限 32767 留裕量）
CAP_PER_FILE = 12000  # 单个产物文件内容上限（超长 SQL 截断封顶）
CAP_EXPECTED = 4500  # 完成标准含目标字段/来源表清单（judge 逐项核验的枚举依据；实测最大案例 raw 4117）
CAP_UT = 2000        # UT 报告摘要上限（任务成功率系 judge 要流程证据——ut_report.md 是对外报告）
CAP_RETRIEVAL = 5000  # rs_input 映射清单摘要（廉价上下文，放全量免截断）
CAP_RS_DIGEST = 500


def clip(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + "…（截断）"


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── 档案取料（老式平铺 / build 新布局 / opt 现场，确定性候选路径）─────────

def find_ts_md(art_root: Path):
    """ts.md 定位：ts.md 或新代命名 {资产名}_ts.md（确定性：精确名优先，后缀名单目录取一）。"""
    for exact in ("ts.md", f"{art_root.name}_ts.md"):
        p = art_root / exact
        if p.is_file():
            return p
    hits = [f for f in art_root.iterdir() if f.name.endswith("_ts.md") and f.is_file()] if art_root.is_dir() else []
    return hits[0] if len(hits) == 1 else None


def find_artifact_root(case_dir: Path):
    """case_dir/ddlc_design_dev → 产物根（build/ 优先，ts.md 在位才算数）。"""
    dd = case_dir / "ddlc_design_dev"
    if not dd.is_dir():
        return None
    build = dd / "build"
    for base in (build, dd):
        if find_ts_md(base) is not None:
            return base
    return None


def find_rs_input(case_dir: Path):
    dd = case_dir / "ddlc_design_dev"
    candidates = [
        dd / "_internal" / "rs_input.json",
        dd / "build" / "_internal" / "rs_input.json",
    ]
    if dd.is_dir():
        for child in sorted(dd.iterdir()):
            if child.name.startswith("opt_") and child.is_dir():
                candidates.append(child / "rs_input.json")
    for c in candidates:
        if c.is_file():
            return c
    return None


def ts_md_overview(art_root: Path) -> str:
    """ts.md §1 概述段切片（各版本 ts.md 都有，确定性摘要源）。"""
    p = find_ts_md(art_root)
    if p is None:
        return ""
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return ""
    start = text.find("\n## 1.")
    if start < 0:
        return clip(text[:800], 800)
    end = text.find("\n## ", start + 5)
    seg = text[start + 1 : end if end > 0 else start + 1600]
    return seg.strip()


def list_artifacts(art_root: Path) -> list[str]:
    """产物清单：ddl/ + etl/（老档案 select/ 兜底）+ dq/，规则文件名有序。"""
    out = []
    for sub in ("ddl", "etl", "select", "dq"):
        d = art_root / sub
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix == ".sql":
                    out.append(f"{sub}/{f.name}")
    return out


def ut_report_digest(art_root: Path) -> str:
    """UT 报告摘要（对外报告 ut_report.md，任务成功率的流程证据；无则空串）。"""
    p = art_root / "ut_report.md"
    if not p.is_file():
        return ""
    try:
        return clip(p.read_text(encoding="utf-8").strip(), CAP_UT)
    except Exception:
        return ""


# ── 取料 → payload（模式无关的核心四元组）──────────────────

def build_actual(art_root: Path, provenance: str) -> str:
    """actual_output = 设计概述 + 产物文件原文（DDL/ETL SQL 全文嵌入，平台只见 Excel 这格）。"""
    overview = ts_md_overview(art_root)
    parts = [
        "产物内容（真实运行档案，文件原文）：",
        "——设计概述（ts.md §1 概述）——",
        overview,
    ]
    for rel in list_artifacts(art_root):
        try:
            content = (art_root / rel).read_text(encoding="utf-8").strip()
        except Exception:
            content = "（读取失败）"
        parts += ["", f"——{rel}——", clip(content, CAP_PER_FILE)]
    ut = ut_report_digest(art_root)
    if ut:
        parts += ["", "——UT 报告（ut_report.md 摘要，测试环节证据）——", ut]
    parts += ["", f"档案来源：{provenance}"]
    return "\n".join(parts)


def mapping_digest(rs: dict, only_fields=None) -> str:
    """retrieval_context 素材：mapping 字段映射清单（源→规则→目标），可按字段子集过滤（规则行用）。"""
    lines = []
    for m in rs.get("field_mappings", []) or []:
        if only_fields is not None and m.get("target_column") not in only_fields:
            continue
        src_table, src_col = m.get("source_table") or "", m.get("source_column") or ""
        src = f"{src_table}.{src_col}" if (src_table or src_col) else "（无源声明）"
        lines.append(
            f"{src} --[{m.get('transform_rule', '')}]--> "
            f"{m.get('target_column', '')}({m.get('target_column_cn', '')})"
        )
    if not lines:
        return ""
    scope = f"（本规则 {len(lines)} 项）" if only_fields is not None else f" {len(lines)} 项"
    return f"输入材料：mapping 字段映射{scope}（源→规则→目标）：\n" + "\n".join(lines)


def normalize_rules(ts) -> list:
    """rules 兼容三代形态：dict（rule_id 键控）/ list（rule_id 字段或按序 R000X 派生，与落盘文件名同规）。"""
    r = ts.get("rules") if isinstance(ts, dict) else None
    out = []
    if isinstance(r, dict):
        out = [(str(k), v) for k, v in r.items()]
    elif isinstance(r, list):
        for i, rule in enumerate(r, 1):
            rid = str(rule.get("rule_id") or rule.get("id") or f"R{i:04d}")
            out.append((rid, rule))
    return out


def rule_field_targets(rule) -> list:
    """规则的输出字段集，兼容三代：fields 三桶 dict / fields flat list（target_field）/ 老式 field_targets。"""
    out, seen = [], set()

    def add(name):
        if name and name not in seen:
            seen.add(name)
            out.append(name)

    fields = rule.get("fields")
    if isinstance(fields, list):
        for item in fields:
            if isinstance(item, dict):
                add(item.get("target_field") or item.get("target"))
    elif isinstance(fields, dict):
        for bucket in ("processed", "assign"):
            for item in fields.get(bucket) or []:
                if isinstance(item, dict):
                    add(item.get("target"))
        for item in fields.get("direct") or []:
            if isinstance(item, str):
                toks = item.split()
                if toks:
                    add(toks[-1])
    for name in rule.get("field_targets") or []:
        add(name)
    return out


def rule_sql_file(art_root: Path, rid: str):
    """规则 SQL 定位：确定性文件名优先（etl/{rid}.sql / select/{rid}_select.sql），缺则按 rid 前缀单点取。"""
    for cand in (art_root / "etl" / f"{rid}.sql",
                 art_root / "select" / f"{rid}_select.sql",
                 art_root / "select" / f"{rid}.sql"):
        if cand.is_file():
            return cand
    for sub in ("etl", "select"):
        d = art_root / sub
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.name.startswith(rid) and f.suffix == ".sql":
                    return f
    return None


def payload_from_archive(case_dir: Path, granularity: str = "task"):
    """10_project_deliver 案例目录 → payload 列表（task=案例一行 / rule=每规则一行 / both=并集）。"""
    art_root = find_artifact_root(case_dir)
    if art_root is None:
        return None, "无 ts.md 产物档案（未完成或目录不合规）"

    rs_path = find_rs_input(case_dir)
    rs = load_json(rs_path) if rs_path else None
    if rs is None:
        return None, "rs_input.json 缺失（无法派生 input/expected）"

    meta = rs.get("meta", {}) or {}
    target = meta.get("target", {}) or {}
    if not (target.get("schema") or target.get("table")):
        target = target.get("f_table") or {}  # 老式 {f_table:{schema,table,cn}} 嵌套形态
    schema, table = target.get("schema", ""), target.get("table", "")
    full = f"{schema}.{table}" if schema else table
    grain = meta.get("grain", "")
    desc = clip(target.get("description", "") or target.get("cn", ""), 200)
    fields = rs.get("field_mappings", []) or []
    sources = rs.get("source_tables", []) or []
    sched = rs.get("schedule", {}) or {}
    dq = rs.get("dq_requirements", []) or []

    task_input = (
        f"任务：为 {full} 完成设计、评审、开发及测试（输入=RS+mapping，流程=设计→闸口→编码→UT）。\n"
        f"表说明：{desc}\n粒度：{grain}\n调度：{sched.get('strategy', '')} / {sched.get('frequency', '')}\n"
        f"映射字段 {len(fields)} 项，来源表 {len(sources)} 张。"
    )
    # 目标字段/来源表清单：judge 逐项核验的枚举依据（quick 模式无 retrieval_context 列，清单必须进 expected）
    tgt_fields, seen_f = [], set()
    for m in fields:
        tc = m.get("target_column")
        if tc and tc not in seen_f:
            seen_f.add(tc)
            tgt_fields.append(tc)
    src_tables, seen_t = [], set()
    for s in sources:
        name = s.get("source_table") if isinstance(s, dict) else str(s)
        if name and name not in seen_t:
            seen_t.add(name)
            src_tables.append(name)

    expected = (
        "任务完成标准（自 RS 派生，逐项可核验）：\n"
        f"- 目标表 {full}，粒度：{grain}\n"
        f"- 目标字段 {len(tgt_fields)} 项：{', '.join(tgt_fields)}"
        "（应全部出现在 DDL 与 SELECT 输出列中，标准审计字段允许另加）\n"
        f"- 来源表 {len(src_tables)} 张：{', '.join(src_tables)}\n"
        f"- 建表 DDL（create_table_{table}.sql）与映射结构一致；ETL 每规则一个 SELECT 文件\n"
        f"- 调度方案：{sched.get('strategy', '')}"
        + (f"；DQ 检查 {len(dq)} 条" if dq else "")
        # UT 标准只在该案例档案确有 ut_report.md 时提出——标准跟着交付件实际范围走，
        # 不给无 UT 产出的老档案虚设无法举证的标准
        + ("\n- 通过 UT：ut_report.md 致命项零失败（报告随产物交付）" if ut_report_digest(art_root) else "")
    )
    task_payload = {
        "task_input": task_input,
        "rs_digest": "",
        "retrieval": mapping_digest(rs),
        "expected": expected,
        "actual": build_actual(art_root, str(case_dir)),
        # 上传前确定性自检依据：这些字段必须出现在（截断后的）actual 里，judge 才核得完覆盖
        "coverage_fields": tgt_fields,
    }

    if granularity == "task":
        return [task_payload], None

    # 规则粒度：ts.json 每规则一行（规则 SQL + 目标表 DDL + 规则字段清单——交付件的自然子单元）
    rule_payloads = []
    ts = load_json(art_root / "ts.json")
    for rid, rule in normalize_rules(ts) if ts else []:
        tgts = rule_field_targets(rule)
        sqlf = rule_sql_file(art_root, rid)
        if sqlf is None or not tgts:
            continue  # 规则行要求 SQL 与字段清单双在位，缺则不拆
        tt = rule.get("target_table") or full
        ddl = art_root / "ddl" / f"create_table_{tt.split('.')[-1]}.sql"
        try:
            sql_text = sqlf.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        actual = f"——{sqlf.relative_to(art_root)}——\n{clip(sql_text, CAP_PER_FILE)}"
        if ddl.is_file():
            try:
                actual += f"\n\n——ddl/{ddl.name}——\n{clip(ddl.read_text(encoding='utf-8').strip(), CAP_PER_FILE)}"
            except Exception:
                pass
        actual += f"\n\n档案来源：{case_dir}"
        rule_payloads.append({
            "label": f"{case_dir.name}:{rid}",
            "task_input": (
                f"{task_input}\n本规则：{rid}"
                f"（{rule.get('rule_name') or rule.get('name') or ''}），"
                f"step_type={rule.get('step_type') or 'full'}，目标表 {tt}——产出该规则的加工 SELECT。"
            ),
            "rs_digest": "",
            "retrieval": mapping_digest(rs, only_fields=set(tgts)),
            "expected": (
                "规则完成标准（自 ts 设计派生，逐项可核验）：\n"
                f"- 本规则输出列 {len(tgts)} 项：{', '.join(tgts)}（应全部出现在 SELECT 输出列中）\n"
                f"- SELECT 落盘为一个文件（{sqlf.name}），加工口径与 mapping 一致\n"
                f"- 与目标表 {tt} 的 DDL 结构一致"
            ),
            "actual": actual,
            "coverage_fields": tgts,
        })

    if granularity == "rule":
        return rule_payloads, (None if rule_payloads else "无可拆规则（ts.json 缺失或规则无 SQL/字段清单）")
    return [task_payload] + rule_payloads, None


def asset_name(dirname: str) -> str:
    prefix = dirname.split("_", 1)
    return prefix[1] if len(prefix) == 2 and prefix[0].isdigit() else dirname


def match_deliver(asset: str, deliver_root: Path):
    """按资产名 join 10_project_deliver（多档取 ts.md 在位且 mtime 最新）。"""
    if not deliver_root.is_dir():
        return None
    cands = [
        d
        for d in deliver_root.iterdir()
        if d.is_dir() and (d.name == asset or d.name.endswith("_" + asset) or d.name.startswith(asset + "_"))
    ]
    cands = [d for d in cands if find_artifact_root(d) is not None]
    if not cands:
        return None
    return max(cands, key=lambda d: (d / "ddlc_design_dev").stat().st_mtime)


def payload_from_evalsuite(case_dir: Path, deliver_root: Path):
    """eval-suite 案例 → payload：input/expected 来自 expectations.json，actual 来自产物档案。"""
    exp = load_json(case_dir / "expectations.json")
    if exp is None:
        return None, "expectations.json 缺失"

    prompt = exp.get("prompt", "")
    target = exp.get("target_table", "")
    rs_digest = ""
    rs_md = case_dir / "RS.md"
    if rs_md.is_file():
        try:
            rs_digest = clip(rs_md.read_text(encoding="utf-8").strip(), CAP_RS_DIGEST)
        except Exception:
            rs_digest = ""

    scoring = exp.get("scoring", {}) or {}
    checks = exp.get("checks", []) or []
    files = [p for c in checks if c.get("type") == "files_exist" for p in c.get("paths", [])]
    exp_lines = ["任务完成标准："]
    if scoring:
        exp_lines.append("- 评分维度：" + " / ".join(f"{k}{v}" for k, v in scoring.items()))
    if files:
        exp_lines.append("- 应产出文件：" + ", ".join(files[:12]))
        if len(files) > 12:
            exp_lines.append(f"  （等共 {len(files)} 个）")

    deliver = match_deliver(asset_name(case_dir.name), deliver_root)
    if deliver is None:
        return None, f"10_project_deliver 无匹配产物档案（资产 {asset_name(case_dir.name)}）"
    return [{
        "task_input": f"任务：{prompt}\n目标表：{target}",
        "rs_digest": rs_digest,
        "retrieval": ("输入材料（RS）摘要：\n" + rs_digest) if rs_digest else "",
        "expected": "\n".join(exp_lines),
        "actual": build_actual(find_artifact_root(deliver), str(deliver)),
    }], None


# ── payload → 行（quick / dataset 两种形态）────────────────

def shape_row(payload: dict, mode: str, metric: str) -> dict:
    columns = QUICK_COLUMNS if mode == "quick" else DATASET_COLUMNS
    row = {c: "" for c in columns}
    if mode == "quick":
        row["metric_name"] = metric
        inp = payload["task_input"]
        if payload["rs_digest"]:
            inp += f"\n需求摘要（RS）：\n{payload['rs_digest']}"
        row["input"] = clip(inp, CAP_INPUT)
        row["expected_output"] = clip(payload["expected"], CAP_EXPECTED)
    else:
        row["input"] = clip(payload["task_input"], CAP_INPUT)
        row["expected_output"] = clip(payload["expected"], CAP_EXPECTED)
        row["retrieval_context"] = clip(payload["retrieval"], CAP_RETRIEVAL)
    row["actual_output"] = clip(payload["actual"], CAP_ACTUAL)
    return row


# ── 输出（平台只收 Excel，单产物）────────────────────────


def iter_case_roots(root: Path) -> list[Path]:
    """收集含 ddlc_design_dev 的案例目录——目录名是流程定死的确定性名字，按名收集非通配猜文件。

    兼容两种布局：老式一层平铺（{资产}/ddlc_design_dev）与新布局三层嵌套
    （{appid}/{schema}/{资产}/ddlc_design_dev）；下划线/点开头目录不入。
    """
    found = []
    for dirpath, dirnames, _ in os.walk(root):
        parts = Path(dirpath).parts
        if any(p.startswith("_") or p.startswith(".") for p in parts[len(root.parts) :]):
            dirnames[:] = []
            continue
        if "ddlc_design_dev" in dirnames:
            found.append(Path(dirpath))
            dirnames.remove("ddlc_design_dev")  # 档案内部不再下钻
    return sorted(found)

def write_xlsx(rows, out_base: Path, columns) -> Path:
    out_base.parent.mkdir(parents=True, exist_ok=True)
    xlsx_path = out_base.with_suffix(".xlsx")
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("✗ openpyxl 不可用（xlsx 是唯一产物，必装）：pip install openpyxl", file=sys.stderr)
        sys.exit(1)

    wb = Workbook()
    ws = wb.active
    ws.title = "eval_import"
    ws.append(columns)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([r[c] for c in columns])
    widths = {"metric_name": 14, "input": 60, "actual_output": 80,
              "expected_output": 60, "retrieval_context": 70}
    for i, col in enumerate(columns, 1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(col, 12)
    ws.freeze_panes = "A2"
    wb.save(xlsx_path)
    return xlsx_path


def main():
    ap = argparse.ArgumentParser(description="内网评测平台导入集/评估集一键构造器")
    ap.add_argument("--source", choices=["evalsuite", "archive"], default="evalsuite",
                    help="evalsuite=本地试点（cases × 产物档案 join）/ archive=档案直读（内网真实案例）")
    ap.add_argument("--mode", choices=["quick", "dataset"], default="quick",
                    help="quick=快速评估导入（行级 metric_name）/ dataset=评估集（无 metric_name + retrieval_context）")
    ap.add_argument("--root", default=None,
                    help="案例根目录：evalsuite 默认本脚本所在 eval-suite/cases；archive 必填（10_project_deliver）")
    ap.add_argument("--deliver-root", default=None,
                    help="evalsuite 源的产物档案根（默认兄弟目录 10_project_deliver）")
    ap.add_argument("--out", default=None, help="输出基准路径（默认 out/platform_[import|dataset][_intranet]）")
    ap.add_argument("--granularity", choices=["task", "rule", "both"], default="task",
                    help="task=案例一行（默认）/ rule=每规则一行（30+ 扩容主力：规则=交付件自然子单元，"
                         "行数=Σ规则数）/ both=并集。仅 archive 源生效")
    ap.add_argument("--case", default=None,
                    help="只导出指定案例（目录名子串匹配，如 003 / dwb_trade_wide_f）——单案例端到端试点用")
    ap.add_argument("--metric-name", default=DEFAULT_METRIC_NAME,
                    help="评估器名称（仅 quick 模式使用；dataset 模式评估器在评估任务层选）")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    if args.source == "evalsuite":
        root = Path(args.root) if args.root else here / "cases"
        deliver_root = Path(args.deliver_root) if args.deliver_root else here.parent / "10_project_deliver"
        make_payloads = payload_from_evalsuite
        iter_cases = lambda: sorted(p for p in root.iterdir() if p.is_dir())
    else:
        if not args.root:
            ap.error("--source archive 需要 --root（10_project_deliver 路径）")
        root = Path(args.root)
        make_payloads = lambda d: payload_from_archive(d, args.granularity)
        iter_cases = lambda: iter_case_roots(root)

    rows, case_log = [], []
    for case_dir in iter_cases():
        if case_dir.name.startswith("_") or case_dir.name.startswith("."):
            continue
        if args.case and args.case not in case_dir.name:
            continue
        payloads, skip = make_payloads(case_dir)
        if not payloads:
            case_log.append({"case": case_dir.name, "included": False, "skip_reason": skip})
            continue
        for payload in payloads:
            entry = {"case": payload.get("label", case_dir.name)}
            row = shape_row(payload, args.mode, args.metric_name)
            # 确定性覆盖自检：expected 承诺的每个字段必须在 judge 实际可见的 actual 里——
            # 截断/缺产物导致的核不了，上传了必扣分，自检不过整行拦下
            missing = [f for f in payload.get("coverage_fields", []) if f not in row["actual_output"]]
            if missing:
                entry.update({"included": False,
                              "skip_reason": f"覆盖自检不过：{len(missing)} 字段不在 actual（截断/缺产物）：{', '.join(missing[:5])}…"})
            else:
                entry.update({
                    "included": True,
                    "len_input": len(row["input"]),
                    "len_actual": len(row["actual_output"]),
                    "len_expected": len(row["expected_output"]),
                    **({"len_retrieval": len(row["retrieval_context"])} if args.mode == "dataset" else {}),
                })
                rows.append(row)
            case_log.append(entry)

    suffix = "_intranet" if args.source == "archive" else ""
    out_base = Path(args.out) if args.out else here / "out" / f"platform_{args.mode}{suffix}"
    columns = QUICK_COLUMNS if args.mode == "quick" else DATASET_COLUMNS
    xlsx_path = write_xlsx(rows, out_base, columns)

    print(f"来源={args.source}  模式={args.mode}  案例目录={root}  入集={len(rows)} 行"
          + (f"  指标={args.metric_name}" if args.mode == "quick" else ""))
    for e in case_log:
        mark = "✓" if e["included"] else "✗"
        info = (f"in={e['len_input']} actual={e['len_actual']} exp={e['len_expected']}"
                + (f" retr={e['len_retrieval']}" if "len_retrieval" in e else "")) if e["included"] else e["skip_reason"]
        print(f"  {mark} {e['case']:<32} {info}")
    print(f"产物：{xlsx_path}")


if __name__ == "__main__":
    main()
