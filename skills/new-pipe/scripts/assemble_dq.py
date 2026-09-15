#!/usr/bin/env python3
"""
DQ 制品装配器: dq_decisions.yaml + dq/*.sql + rs_input + ts.json -> dq.json + ts.md DQ 章节 + 闸口①材料

2026-09-14 DQ 拆分：DQ 设计由 dws-dq-producer 独立会话完成（读 RS+mapping+待审 ts，
不读 design_logic/ETL SQL——审计独立性），本脚本是其产物的装配+校验门禁（闸口①前跑）：

  - dq.json   DQ 元数据唯一源（含锚定声明/模式/歧义标注 + dq 调度任务）——UT/导出消费
  - ts.md     §7 DQ 章节替换追加（主线章节字节不动——占位锚点整段替换）
  - _internal/dq_gate_summary.md  闸口① DQ 分级材料（断言式机器对照打包/对比式需人确认/歧义裁决点）

校验（LD 层迁入改造，权威在此）：
  N_DQ1  RS 有 DQ 需求但 dq_decisions 空（hard）
  N_DQ2  翻译条数少于 RS（warn，漏翻译线索）
  N_DQ3  RS 无需求但自加（warn，DQ 是业务决策归 RS）
  N_DQ4  violation_condition 必填（hard——新契约；断言式=表达式，对比式=摘要声明）
  N_DQ5  violation_condition 引用存在性（hard；域=目标表字段∪资产源表，无 cache 源表侧降 warn）
         + 三段式引用硬拦 + 中间表（tmp）禁引用（hard——tmp 是被检实现的一部分，独立重算禁碰）
  N_DQ6  mode 合法值 assertion/compare（hard）
  N_DQ7  对比式必填 compare_sources 且 ⊆ 资产源表（hard）
  N_DQ8  anchored_fields ⊆ 目标表字段（hard；断言式缺省自动提取补全，对比式必须显式声明）
  N_DQ9  SQL 文件在位且非空（文件名=dq_filename 派生，hard）
  N_DQ10 SQL 文本对账（hard）：三段式 / 目标别名限定列 ⊆ 目标表字段（幻觉列）/
         FROM 表引用 ⊆ {目标表∪资产源表}（tmp 拦截，CTE 名豁免）

用法:
  python assemble_dq.py --ts {build}/ts.json --rs {build}/_internal/rs_input.json \
      --decisions {build}/_internal/dq_decisions.yaml \
      [--design-decisions {build}/_internal/design_decisions.yaml] [--schema-cache {缓存}]

退出码: 0=成功, 1=校验失败, 2=文件/解析错误
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))

import yaml  # noqa: E402
from run_ut import dq_filename  # noqa: E402  文件名单点（UT 侧同源派生）
from sql_parse import (  # noqa: E402
    extract_qualified_refs, extract_logic_refs, find_three_part_refs,
    extract_from_tables, split_cte_main,
)
from lts_task_paths import load_schedule_config, resolve_schedule_path  # noqa: E402


# ============================================================
# 校验结果（简版——与 assemble_ts.ValidationResult 平行的薄容器）
# ============================================================
class DqResult:
    def __init__(self):
        self.items = []  # {code, level, msg}

    def hard(self, code, msg):
        self.items.append({"code": code, "level": "hard", "msg": msg})

    def warn(self, code, msg):
        self.items.append({"code": code, "level": "warn", "msg": msg})

    @property
    def n_hard(self):
        return sum(1 for i in self.items if i["level"] == "hard")

    def report_lines(self):
        lines = []
        for i in self.items:
            tag = "❌" if i["level"] == "hard" else "⚠️"
            lines.append(f"{tag} [{i['code']}] {i['msg']}")
        return lines


def _short(name: str) -> str:
    return str(name or "").rsplit(".", 1)[-1].strip().lower()


def _f_table_info(ts: dict):
    """目标 F 表（schema, 短名, 字段名集合）。

    字段条目取 build_tables 的真实产出键 target_field（build_field 产
    {target_field, field_type, field_comment, ...}）；name/column/field 为
    兼容形态兜底。字段名统一 lower（与 N_DQ8 锚定/引用校验同口径）。
    """
    f = ((ts.get("meta", {}).get("target", {}) or {}).get("f_table", {}) or {})
    schema = str(f.get("schema") or "").strip().lower()
    short = _short(f.get("table"))
    fields = set()
    for col in ((ts.get("tables", {}).get(short) or {}).get("fields") or []):
        if isinstance(col, dict):
            name = (col.get("target_field") or col.get("name")
                    or col.get("column") or col.get("field") or "")
        else:
            name = str(col)
        name = str(name).strip().lower()
        if name:
            fields.add(name)
    return schema, short, fields


def _tmp_tables(ts: dict) -> set:
    """中间表短名集合（target_role=intermediate 的目标表）——DQ 引用禁碰。"""
    out = set()
    for r in (ts.get("rules") or {}).values():
        if (r.get("target_role") or "target") == "intermediate":
            t = _short(r.get("target_table"))
            if t:
                out.add(t)
    return out


def _target_alias_columns(sql: str, f_short: str, f_schema: str) -> dict:
    """识别 SQL 里目标表的别名，返回 {别名: [列...]}（含 schema.table 限定形态）。"""
    import re
    aliases = {}
    pat = re.compile(
        r"(?:FROM|JOIN)\s+" +
        r"(?:" + re.escape(f_schema) + r"\.)?" + re.escape(f_short) +
        r"\s+(?:AS\s+)?([A-Za-z_]\w*)",
        re.IGNORECASE)
    for m in pat.finditer(sql):
        aliases[m.group(1).lower()] = True
    out = {}
    for al, col in extract_qualified_refs(sql):
        a = str(al or "").strip().lower()
        c = str(col or "").strip().lower()
        if a in aliases and c:
            out.setdefault(a, []).append(c)
    return out


def _auto_anchor_fields(vc: str, f_fields: set) -> list:
    """断言式锚定自动提取：violation_condition 里命中目标表字段集的引用（限定+裸）。"""
    hit = set()
    qualified, bare = extract_logic_refs(vc, f_fields)
    for _al, col in qualified:
        c = str(col).strip().lower()
        if c in f_fields:
            hit.add(c)
    for b in bare:
        c = str(b).strip().lower()
        if c in f_fields:
            hit.add(c)
    return sorted(hit)


# ============================================================
# 校验主函数
# ============================================================
def validate_and_build(rs_input: dict, ts: dict, decisions: dict, dq_dir: Path,
                       schema_cache_path: str = "", rs_contract: bool = True):
    """校验 dq_decisions 并装配 rules 条目。返回 (rules_out, DqResult)。

    rs_contract=False（opt 场景）：跳过 N_DQ1-3 的 RS 对照——条目权威=baseline dq.json
    清单+变更需求（影响分析管重做范围），不走新建的 RS 驱动契约。
    """
    vr = DqResult()
    rules_in = decisions.get("rules", []) or []
    if rs_contract:
        rs_dq = rs_input.get("dq_requirements", []) or []
        n_rs, n_dec = len(rs_dq), len(rules_in)

        # --- N_DQ1/2/3：与 RS 对照 ---
        if n_rs > 0 and n_dec == 0:
            vr.hard("N_DQ1",
                    f"RS 有 {n_rs} 条 DQ 需求（dq_requirements），但 dq_decisions.rules 为空——"
                    f"dws-dq-producer 未完成 DQ 设计（闸口①材料不完整，不放进 UT）")
        elif 0 < n_dec < n_rs:
            vr.warn("N_DQ2", f"RS 有 {n_rs} 条 DQ 需求，DQ 只设计了 {n_dec} 条，核对是否漏")
        elif n_rs == 0 and n_dec > 0:
            vr.warn("N_DQ3", f"RS 未提 DQ 需求，但自行设计了 {n_dec} 条——DQ 是业务决策归 RS，请确认")

    f_schema, f_short, f_fields = _f_table_info(ts)
    if not f_fields:
        vr.hard("N_DQ1", "ts.tables 里取不到目标 F 表字段集——先确认 ts.json 已组装")

    src_tables = rs_input.get("source_tables") or []
    if not src_tables:
        # opt 场景（无 rs_input）：源表集合从 ts.rules 派生（引用域/compare_sources 校验用）
        src_tables = [
            {"source_schema": st.get("schema", ""), "source_table": st.get("table", "")}
            for r in (ts.get("rules") or {}).values()
            for st in (r.get("source_tables") or []) if st.get("table")
        ]
    tbl_names = {_short(st.get("source_table")) for st in src_tables}
    tbl_names.discard("")
    if f_short:
        tbl_names.add(f_short)
    schemas = {str(st.get("source_schema") or "").strip().lower() for st in src_tables}
    if f_schema:
        schemas.add(f_schema)
    schemas.discard("")
    tmps = _tmp_tables(ts)

    cache_fields = set()
    if schema_cache_path:
        cand = Path(schema_cache_path)
        if cand.exists():
            try:
                for cols in (json.loads(cand.read_text(encoding="utf-8")).get("tables") or {}).values():
                    cache_fields |= {str(c).lower() for c in (cols or {})}
            except Exception:
                cache_fields = set()
    field_all = f_fields | cache_fields

    rules_out = []
    for i, d in enumerate(rules_in, 1):
        name = d.get("rule_name") or d.get("check_type") or f"?#{i}"
        check_type = (d.get("check_type") or "").strip()
        mode = (d.get("mode") or "").strip().lower()
        vc = (d.get("violation_condition") or "").strip()
        anchored = [str(a).strip().lower() for a in (d.get("anchored_fields") or []) if str(a).strip()]
        comp_srcs = [str(s).strip() for s in (d.get("compare_sources") or []) if str(s).strip()]
        ambiguities = d.get("ambiguities") or []

        # --- N_DQ6 mode ---
        if mode not in ("assertion", "compare"):
            vr.hard("N_DQ6", f"rules[{i}]（{name}）mode='{mode or '（空）'}' 不合法（assertion=断言式 / compare=对比式）")
        # --- N_DQ4 violation_condition 必填 ---
        if not vc:
            vr.hard("N_DQ4", f"rules[{i}]（{name}）缺 violation_condition——断言式写违规表达式"
                             f"（如 t.order_amount IS NULL），对比式写比对口径的摘要声明")
        # --- N_DQ5 引用存在性（violation_condition）---
        if vc:
            three = find_three_part_refs(vc)
            if three:
                vr.hard("N_DQ5", f"rules[{i}]（{name}）violation_condition 有三段式引用 {three}"
                                 f"——字段引用一律'别名.字段'两段；子查询表引用 schema.table 两段")
            bad = []
            for al, col in extract_logic_refs(vc, field_all)[0]:
                a, c = str(al).strip().lower(), str(col).strip().lower()
                if a in tmps or (a in schemas and c in tmps):
                    bad.append(f"{al}.{col}（中间表禁引用——tmp 是被检实现的一部分，独立重算禁碰）")
                elif a in schemas:
                    if c not in tbl_names:
                        bad.append(f"{al}.{c}（表不在资产源表/目标表内）")
                elif cache_fields and c not in field_all:
                    bad.append(f"{al}.{c}")
            if bad:
                vr.hard("N_DQ5", f"rules[{i}]（{name}）violation_condition 引用不存在：{bad}")
            if not cache_fields:
                vr.warn("N_DQ5", f"rules[{i}]（{name}）无 schema_cache——源表字段侧引用存在性未校验（闸口①人工确认）")
        # --- N_DQ7 对比式 compare_sources ---
        if mode == "compare":
            if not comp_srcs:
                vr.hard("N_DQ7", f"rules[{i}]（{name}）对比式必须声明 compare_sources"
                                 f"（比对的来源表，opt 影响分析依赖）")
            bad_src = [s for s in comp_srcs if _short(s) not in tbl_names or _short(s) in tmps]
            if bad_src:
                vr.hard("N_DQ7", f"rules[{i}]（{name}）compare_sources 含不在资产源表内的表：{bad_src}")
        # --- N_DQ8 锚定 ---
        if not anchored and mode == "assertion" and vc:
            anchored = _auto_anchor_fields(vc, f_fields)  # 断言式自动提取补全
        if not anchored:
            vr.hard("N_DQ8", f"rules[{i}]（{name}）缺 anchored_fields——对比式必须显式声明锚定字段"
                             f"（opt 影响分析=变更字段∩锚定字段）；断言式可由 violation_condition 自动提取（当前未提取到，请补）")
        bad_anchor = [a for a in anchored if a not in f_fields]
        if bad_anchor:
            vr.hard("N_DQ8", f"rules[{i}]（{name}）anchored_fields 含目标表没有的字段：{bad_anchor}")
        # --- N_DQ9/N_DQ10 SQL 文件 ---
        fname = dq_filename(i, check_type)
        fpath = dq_dir / fname
        sql = ""
        if not check_type or not fpath.exists():
            vr.hard("N_DQ9", f"rules[{i}]（{name}）SQL 文件缺失（预期 {fname}——文件名=规则序号+清洗 check_type）")
        else:
            sql = fpath.read_text(encoding="utf-8").strip()
            if not sql:
                vr.hard("N_DQ9", f"rules[{i}]（{name}）SQL 文件为空：{fname}")
        if sql:
            three = find_three_part_refs(sql)
            if three:
                vr.hard("N_DQ10", f"rules[{i}]（{name}）SQL 有三段式引用 {three}")
            # 目标别名限定列 ⊆ F 字段集（幻觉列）
            for al, cols in _target_alias_columns(sql, f_short, f_schema).items():
                bad_cols = [c for c in cols if c not in f_fields]
                if bad_cols:
                    vr.hard("N_DQ10", f"rules[{i}]（{name}）SQL 里目标表别名 '{al}' 引用了"
                                       f"目标表没有的列 {sorted(set(bad_cols))}——对照 ts.tables 改拼写（幻觉列）")
            # FROM 表引用 ⊆ 源表∪目标表，tmp 拦截（CTE 名豁免）
            cte_names, _main = split_cte_main(sql)
            cte_lower = {c.lower() for c in cte_names}
            for t in extract_from_tables(sql):
                tl = _short(t)
                if tl in cte_lower:
                    continue
                if tl in tmps:
                    vr.hard("N_DQ10", f"rules[{i}]（{name}）SQL 引用了中间表 '{t}'——独立重算禁碰 tmp"
                                       f"（从源表独立实现，不用被检对象的加工产物）")
                elif tl not in tbl_names:
                    vr.hard("N_DQ10", f"rules[{i}]（{name}）SQL 引用了资产外的表 '{t}'"
                                       f"（合法域=目标表∪资产源表）")

        rules_out.append({
            "idx": i,
            "rule_id": d.get("rule_id") or f"DQ_{i:03d}",
            "rule_name": d.get("rule_name") or check_type,
            "check_type": check_type,
            "scope": d.get("scope") or "",
            "mode": mode,
            "violation_condition": vc,
            "rule_desc": d.get("rule_desc") or "",
            "anchored_fields": anchored,
            "compare_sources": comp_srcs,
            "ambiguities": ambiguities,
            "waived": bool(d.get("waived")),
            "waive_reason": d.get("waive_reason") or "",
            "sql_file": fname,
        })

    return rules_out, vr


# ============================================================
# dq 调度任务（口径同 assemble_ts 原 tasks["dq"]：挂 I 视图下游）
# ============================================================
def build_dq_task(ts: dict, design_decisions: dict) -> dict:
    tasks_sched = ts.get("tasks", {}) or {}
    f_task = tasks_sched.get("f", {}) or {}
    view_task = tasks_sched.get("view", {}) or {}
    if not view_task.get("task_name"):
        return {}  # 原语义：无 I 视图不建 dq 任务（消费端 get("dq") 缺省）

    f = (ts.get("meta", {}).get("target", {}).get("f_table", {}) or {})
    f_short = str(f.get("table") or "")
    dec_sched = (design_decisions or {}).get("schedule", {}) or {}
    override = (dec_sched.get("task_project_override", {}) or {}).get("dq", {}) or {}
    if override.get("project_name") or override.get("task_group"):
        path = {"project_name": override.get("project_name", ""), "task_group": override.get("task_group", "")}
    else:
        path = resolve_schedule_path(load_schedule_config(), str(f.get("schema") or ""), "dq")
    view_short = str(view_task.get("task_name") or "").replace("task_", "", 1)
    return {
        "task_name": f"task_{f_short}_dq",
        "job_name": f"Pjob_{f_short}_dq",
        "cron": f_task.get("cron", ""),
        "upstream": [{"table": view_short, "task": view_task.get("task_name", ""), "dep_type": "宽依赖"}],
        "project_name": path["project_name"],
        "task_group": path["task_group"],
    }


# ============================================================
# ts.md §7 章节替换（占位锚点整段替换，主线章节字节不动）
# ============================================================
DQ_SECTION_TITLE = "## 7. 数据质量检查(DQ)"


def render_dq_section(dq: dict, rs_dq: list) -> str:
    rules = dq.get("rules") or []
    mode_cn = {"assertion": "断言式", "compare": "对比式", "": "-"}
    lines = [DQ_SECTION_TITLE, ""]
    if not rules:
        lines.append("*(RS 未提 DQ 需求，本资产无 DQ)*")
        lines.append("")
        return "\n".join(lines)
    lines.append(f"> DQ 由 dws-dq-producer 独立设计实现（读 RS+mapping 独立理解，不读主线实现），共 {len(rules)} 条。"
                 f"断言式=违规行探测器；对比式=独立重算比对。装配校验见 assemble_dq。")
    lines.append("")
    lines.append("| # | 模式 | 检查范围 | 检查类型 | 规则名称 | 违规条件/比对口径 | 锚定字段 | 比对来源 | 说明 |")
    lines.append("|---|------|----------|----------|----------|------------------|----------|----------|------|")
    for r in rules:
        waived = "（已豁免）" if r.get("waived") else ""
        lines.append(
            f"| {r['idx']} | {mode_cn.get(r.get('mode'), r.get('mode'))} | {r.get('scope', '')} "
            f"| {r.get('check_type', '')} | {r.get('rule_name', '')} "
            f"| `{r.get('violation_condition', '')}` | {', '.join(r.get('anchored_fields') or [])} "
            f"| {', '.join(r.get('compare_sources') or []) or '-'} | {r.get('rule_desc', '')}{waived} |")
    lines.append("")
    amb = [(r, a) for r in rules for a in (r.get("ambiguities") or [])]
    if amb:
        lines.append("**歧义标注**（producer 独立理解 mapping 时发现的二义，待人裁决——闸口①材料附页）：")
        lines.append("")
        for r, a in amb:
            lines.append(f"- DQ{r['idx']}（{r['rule_name']}）: {a.get('note', '')}"
                         + (f" 取舍：{' / '.join(a.get('options') or [])}" if a.get("options") else ""))
        lines.append("")
    return "\n".join(lines)


def patch_ts_md(md_path: Path, dq: dict, rs_dq: list):
    """定位 §7 标题整段替换（到下一个 '---' 或 '## ' 前）；标题不存在（旧档）则尾部追加。"""
    text = md_path.read_text(encoding="utf-8")
    section = render_dq_section(dq, rs_dq) + "\n"
    idx = text.find(DQ_SECTION_TITLE)
    if idx < 0:
        new_text = text.rstrip("\n") + "\n\n---\n\n" + section
    else:
        # 段尾=下一个顶层分隔（\n---\n 或 \n## ）或文件尾
        rest = text[idx + len(DQ_SECTION_TITLE):]
        end = len(text)
        for marker in ("\n---", "\n## "):
            p = rest.find(marker)
            if p >= 0:
                end = min(end, idx + len(DQ_SECTION_TITLE) + p)
        new_text = text[:idx] + section + text[end:]
    md_path.write_text(new_text, encoding="utf-8")


# ============================================================
# 闸口① DQ 分级材料
# ============================================================
def render_gate_summary(dq: dict, rs_dq: list, vr: DqResult) -> str:
    rules = dq.get("rules") or []
    lines = ["# DQ 设计材料（闸口①附页——与主线设计同审，一次看全）", ""]
    # 一、机器已核对（断言式且无歧义）
    auto = [r for r in rules if r.get("mode") == "assertion" and not (r.get("ambiguities") or [])]
    need = [r for r in rules if r.get("mode") == "compare" or (r.get("ambiguities") or [])]
    if auto:
        lines.append("## 一、机器已核对的断言式（引用存在/SQL在位/锚定有效——扫一眼即可）")
        lines.append("")
        lines.append("| # | 规则 | 违规条件 | 锚定字段 |")
        lines.append("|---|------|----------|----------|")
        for r in auto:
            lines.append(f"| {r['idx']} | {r['rule_name']} | `{r['violation_condition']}` "
                         f"| {', '.join(r.get('anchored_fields') or [])} |")
        lines.append("")
    # 二、需人确认——对比式（独立重算口径）
    if need:
        lines.append("## 二、需人确认（对比式口径 + 歧义裁决）")
        lines.append("")
        for r in need:
            lines.append(f"### DQ{r['idx']} {r['rule_name']}（{r.get('check_type','')}）")
            lines.append("")
            if r.get("mode") == "compare":
                lines.append(f"- **重算口径**（producer 独立实现，未读主线 design_logic/ETL SQL）: {r.get('rule_desc','')}")
                lines.append(f"- **比对来源**: {', '.join(r.get('compare_sources') or [])}")
                lines.append(f"- **比对口径摘要**: `{r.get('violation_condition','')}`")
            lines.append(f"- **锚定字段**: {', '.join(r.get('anchored_fields') or [])}")
            for a in (r.get("ambiguities") or []):
                lines.append(f"- **⚠️ 歧义待人裁决**: {a.get('note','')}"
                             + (f"（取舍：{' / '.join(a.get('options') or [])}）" if a.get("options") else ""))
            lines.append("")
    # 三、RS 对照（条数/原文）
    lines.append("## 三、RS DQ 需求对照（N_DQ2 漏翻译在此可见）")
    lines.append("")
    if rs_dq:
        lines.append(f"RS 共 {len(rs_dq)} 条需求 / DQ 设计 {len(rules)} 条：")
        lines.append("")
        for j, r in enumerate(rs_dq, 1):
            desc = r.get("rule_desc") or r.get("description") or ""
            lines.append(f"- RS#{j} [{r.get('check_type','')}] {r.get('rule_name','')}: {desc}")
    else:
        lines.append("RS 无 DQ 需求。" + ("（DQ 为自行补充，N_DQ3）" if rules else ""))
    lines.append("")
    # 四、校验发现
    if vr.items:
        lines.append("## 四、装配校验发现")
        lines.append("")
        lines.extend(vr.report_lines())
        lines.append("")
    return "\n".join(lines)


# ============================================================
# main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="DQ 制品装配器（dq_decisions+SQL -> dq.json+ts.md 章节+闸口①材料）")
    parser.add_argument("--ts", required=True, help="build/ts.json 路径")
    parser.add_argument("--rs", default="", help="_internal/rs_input.json 路径（new-pipe 场景；opt 场景可省——源表集合自动从 ts.rules 派生）")
    parser.add_argument("--decisions", required=True, help="_internal/dq_decisions.yaml 路径（dws-dq-producer 产出）")
    parser.add_argument("--design-decisions", default="", help="_internal/design_decisions.yaml（读 dq 任务 project 覆盖，可选）")
    parser.add_argument("--schema-cache", default="", help="schema 缓存路径（可选；无则源表字段侧降 warn）")
    parser.add_argument("--dq-dir", default="", help="DQ SQL 目录（默认 ts 同级 dq/；opt 场景传 build/dq——SQL 在变更现场，装配后由 pipe cp 入临时档案）")
    parser.add_argument("--no-rs-contract", action="store_true",
                        help="opt 场景：跳过 N_DQ1-3 的 RS 对照（条目权威=baseline dq.json 清单+影响分析，不走新建的 RS 驱动契约）")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    rs_path = Path(args.rs)
    dec_path = Path(args.decisions)

    def _die(msg):
        print(f"错误: {msg}", file=sys.stderr)
        sys.exit(2)

    if not ts_path.exists():
        _die(f"ts.json 不存在: {ts_path}")
    rs_input = {}
    if args.rs:
        rs_path = Path(args.rs)
        if not rs_path.exists():
            _die(f"rs_input.json 不存在: {rs_path}")
        try:
            rs_input = json.loads(rs_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            _die(f"rs_input.json 解析失败: {e}")
    if not dec_path.exists():
        _die(f"dq_decisions.yaml 不存在: {dec_path}（RS 有 DQ 需求时 dws-dq-producer 必须先完成设计）")
    try:
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
        decisions = yaml.safe_load(dec_path.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, yaml.YAMLError) as e:
        _die(f"文件解析失败: {e}")

    design_decisions = {}
    dd_path = Path(args.design_decisions) if args.design_decisions else dec_path.parent / "design_decisions.yaml"
    if dd_path.exists():
        try:
            design_decisions = yaml.safe_load(dd_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            design_decisions = {}

    build_dir = ts_path.parent
    dq_dir = Path(args.dq_dir) if args.dq_dir else build_dir / "dq"
    rs_dq = rs_input.get("dq_requirements", []) or []

    rules_out, vr = validate_and_build(rs_input, ts, decisions, dq_dir, args.schema_cache,
                                       rs_contract=not args.no_rs_contract)

    if vr.n_hard:
        print(f"DQ 装配校验失败（{vr.n_hard} 项硬阻断）：", file=sys.stderr)
        for ln in vr.report_lines():
            print(ln, file=sys.stderr)
        sys.exit(1)

    dq = {
        "version": "1.0.0",
        "spec_type": "dq",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generated_by": "assemble_dq.py",
        "meta": {
            "target_table": ((ts.get("meta", {}).get("target", {}).get("f_table", {}) or {}).get("schema", "")
                             + "." + str((ts.get("meta", {}).get("target", {}).get("f_table", {}) or {}).get("table", ""))),
            "business_key": ts.get("design", {}).get("business_key", []),
        },
        "rules": rules_out,
    }
    dq_task = build_dq_task(ts, design_decisions)
    if dq_task:
        dq["tasks"] = {"dq": dq_task}

    dq_path = build_dir / "dq.json"
    dq_path.write_text(json.dumps(dq, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = build_dir / "ts.md"
    if md_path.exists():
        patch_ts_md(md_path, dq, rs_dq)

    gate_path = build_dir / "_internal" / "dq_gate_summary.md"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(render_gate_summary(dq, rs_dq, vr), encoding="utf-8")

    print(f"DQ 装配完成: {dq_path}（{len(rules_out)} 条）")
    if dq_task:
        print(f"DQ 调度任务: {dq_task['task_name']} -> {dq_task['project_name']} / {dq_task['task_group']}")
    print(f"ts.md DQ 章节: 已{'替换' if md_path.exists() else '跳过（ts.md 不存在）'}")
    print(f"闸口①材料: {gate_path}")
    for ln in vr.report_lines():
        print(ln)
    sys.exit(0)


if __name__ == "__main__":
    main()
