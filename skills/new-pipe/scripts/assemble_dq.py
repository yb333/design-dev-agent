#!/usr/bin/env python3
"""
DQ 校验渲染器: producer 的 dq.json + dq/*.sql + rs_input + ts.json -> 补全后的 dq.json + ts.md DQ 章节

2026-09-15 精简定调（两跳并一跳）：dws-dq-producer **直接产 dq.json + SQL**（不再有
dq_decisions.yaml 中间产物），本脚本退化为三件事——**校验 + 补全 + 渲染**：

  1. 校验（实证有值的保留项）：
     N_DQ1  RS 对照：RS 有需求但 rules 空（hard）/ 条数偏少（warn）/ RS 无自加（warn）
     N_DQ4  violation_condition 必填（hard——断言式=表达式，对比式=口径摘要声明）
     N_DQ5  violation_condition 引用对账（hard：三段式 / 引用存在[域=目标表∪资产源表，
            无 cache 源表侧降 warn] / 中间表 tmp 禁引用——独立重算禁碰被检实现）
     N_DQ9  SQL 文件在位且非空（文件名=dq_filename 按序派生，hard）
     N_DQ10 SQL 文本对账（hard：三段式 / 目标别名限定列 ⊆ 目标表字段[幻觉列] /
            FROM ⊆ 目标表∪资产源表[tmp 拦截，CTE 名豁免]）
  2. 补全：idx 按序 / sql_file 派生 / mode 缺省 assertion（值合法校验）/ meta 从 ts
  3. 渲染：ts.md §7 DQ 表格（追加式，主线章节字节不动）——**评审就看这一处**
     （独立评审材料已砍：dq_gate_summary 退役，歧义标注随表格呈现）

锚定声明/compare_sources 暂缓（2026-09-15 用户定调：opt DQ 变更低频，精简优先——
dq_impact 的影响分析走 violation_condition/SQL 粗提兜底，opt 实遇再迭代）。

用法:
  python assemble_dq.py --ts {build}/ts.json --dq-src {build}/dq.json \
      --rs {build}/_internal/rs_input.json [--schema-cache {缓存}]

opt 场景：--rs 可省（源表集合自动从 ts.rules 派生）+ --no-rs-contract（条目权威=
baseline 清单+影响分析，不走新建的 RS 驱动契约）+ --dq-dir（SQL 在变更现场 build/dq）。

退出码: 0=成功, 1=校验失败, 2=文件/解析错误
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))

import yaml  # noqa: E402  (design-decisions 读 dq 任务 project 覆盖用)
from run_ut import dq_filename  # noqa: E402  文件名单点（UT 侧同源派生）
from sql_parse import (  # noqa: E402
    extract_qualified_refs, extract_logic_refs, find_three_part_refs,
    extract_from_tables, split_cte_main, extract_top_projection,
    check_bracket_balance, check_no_select_star, check_no_line_comment,
    extract_table_refs_raw,
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
    兼容形态兜底。字段名统一 lower（与引用校验同口径）。
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


# ============================================================
# 校验主函数
# ============================================================
def validate_and_build(rs_input: dict, ts: dict, rules_in: list, dq_dir: Path,
                       schema_cache_path: str = "", rs_contract: bool = True,
                       declined: list = None):
    """校验 producer 的 rules 清单并补全条目。返回 (rules_out, DqResult)。

    rs_contract=False（opt 场景）：跳过 N_DQ1-3 的 RS 对照——条目权威=baseline
    dq.json 清单+变更需求（影响分析管重做范围），不走新建的 RS 驱动契约。
    declined：producer 建议不做的 RS 条目（[{rs_rule_name, reason}]）——结构类
    检查（类型一致性/字段存在性）已被流程内建覆盖，做 DQ 是重复；计入 RS 覆盖
    但拍板权在人（ts.md"建议不做"段）。
    """
    vr = DqResult()

    # --- N_DQ1/2/3：与 RS 对照（declined=producer 建议不做的条目——显式决策计入覆盖，
    # 拍板权在人：ts.md 表格后的"建议不做"段）---
    declined = declined or []
    if rs_contract:
        rs_dq = rs_input.get("dq_requirements", []) or []
        n_rs, n_dec = len(rs_dq), len(rules_in)
        n_dec_ok = n_dec + len(declined)
        if n_rs > 0 and n_dec_ok == 0:
            vr.hard("N_DQ1",
                    f"RS 有 {n_rs} 条 DQ 需求（dq_requirements），但 dq.json 的 rules 为空——"
                    f"dws-dq-producer 未完成 DQ 设计（闸口①材料不完整，不放进 UT）")
        elif 0 < n_dec_ok < n_rs:
            _note = f"（另有 {len(declined)} 条建议不做——人拍板见 ts.md）" if declined else ""
            vr.warn("N_DQ2", f"RS 有 {n_rs} 条 DQ 需求，DQ 只设计了 {n_dec} 条{_note}，核对是否漏")
        elif n_rs == 0 and n_dec > 0:
            vr.warn("N_DQ3", f"RS 未提 DQ 需求，但自行设计了 {n_dec} 条——DQ 是业务决策归 RS，请确认")

    f_schema, f_short, f_fields = _f_table_info(ts)
    if not f_fields:
        vr.hard("N_DQ1", "ts.tables 里取不到目标 F 表字段集——先确认 ts.json 已组装")

    src_tables = rs_input.get("source_tables") or []
    if not src_tables:
        # opt 场景（无 rs_input）：源表集合从 ts.rules 派生（引用域校验用）
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
        mode = (d.get("mode") or "").strip().lower() or "assertion"  # 缺省补全
        vc = (d.get("violation_condition") or "").strip()
        ambiguities = d.get("ambiguities") or []

        # mode 值合法（轻校验：缺省已补，乱值拦）
        if mode not in ("assertion", "compare"):
            vr.hard("N_DQ4", f"rules[{i}]（{name}）mode='{mode}' 不合法（assertion=断言式 / compare=对比式，可缺省=assertion）")
        # --- N_DQ4 violation_condition 必填 ---
        if not vc:
            vr.hard("N_DQ4", f"rules[{i}]（{name}）缺 violation_condition——断言式写违规表达式"
                             f"（如 t.order_amount IS NULL），对比式写比对口径的摘要声明")
        # --- N_DQ5 引用对账（violation_condition）---
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
            # 基础风格三项（原 check_sql --dq 吸收——2026-09-15 校验合并：DQ 唯一校验入口）
            for _fn, _tag in ((check_bracket_balance, "[语法]"), (check_no_select_star, "[规范]"),
                              (check_no_line_comment, "[规范]")):
                ok, msg = _fn(sql)
                if not ok:
                    vr.hard("N_DQ10", f"rules[{i}]（{name}）{_tag} {msg}")
            three = find_three_part_refs(sql)
            if three:
                vr.hard("N_DQ10", f"rules[{i}]（{name}）SQL 有三段式引用 {three}")
            # schema 前缀（裸表名报错，CTE 名豁免）
            cte_names, _main = split_cte_main(sql)
            cte_lower = {c.lower() for c in cte_names}
            bare_refs = sorted({ref for ref in extract_table_refs_raw(sql)
                                if "." not in ref and ref.lower() not in cte_lower})
            if bare_refs:
                vr.hard("N_DQ10", f"rules[{i}]（{name}）FROM/JOIN 引用必须带 schema 前缀"
                                   f"（schema.table）: {bare_refs}")
            # 目标别名限定列 ⊆ F 字段集（幻觉列）
            for al, cols in _target_alias_columns(sql, f_short, f_schema).items():
                bad_cols = [c for c in cols if c not in f_fields]
                if bad_cols:
                    vr.hard("N_DQ10", f"rules[{i}]（{name}）SQL 里目标表别名 '{al}' 引用了"
                                       f"目标表没有的列 {sorted(set(bad_cols))}——对照 ts.tables 改拼写（幻觉列）")
            # 输出列含 business_key（违规行要能回溯到业务对象）
            bk = [str(k).lower() for k in (ts.get("design", {}).get("business_key") or [])]
            proj = extract_top_projection(sql)
            if proj is not None and proj != ["*"] and bk:
                missing_bk = [k for k in bk if k not in proj]
                if missing_bk:
                    vr.hard("N_DQ10", f"rules[{i}]（{name}）输出列缺业务键 {missing_bk}——"
                                       f"违规行要能回溯到业务对象（输出列=业务键+违规字段值）")
            # 聚合语法（2026-09-15 内网实证：聚合对比缺 GROUP BY——返回全 NULL，
            # producer 自己推测根因）：顶层 SELECT 含聚合函数但无 GROUP BY → 语法/语义错
            import re as _re
            _body_main = (split_cte_main(sql)[1] or sql)
            _has_agg = bool(_re.search(r'\b(sum|count|avg|max|min|string_agg)\s*\(', _body_main, _re.IGNORECASE))
            _has_gb = bool(_re.search(r'\bgroup\s+by\b', _body_main, _re.IGNORECASE))
            if _has_agg and not _has_gb:
                vr.hard("N_DQ10", f"rules[{i}]（{name}）SQL 有聚合列但无 GROUP BY——"
                                   f"聚合对比必须分组（分组键也输出）；聚合后才判的条件收 HAVING")
            # FROM 表引用 ⊆ 源表∪目标表，tmp 拦截（CTE 名豁免）
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
    declined = dq.get("declined") or []
    mode_cn = {"assertion": "断言式", "compare": "对比式", "": "-"}
    lines = [DQ_SECTION_TITLE, ""]
    if not rules and not declined:
        lines.append("*(RS 未提 DQ 需求，本资产无 DQ)*")
        lines.append("")
        return "\n".join(lines)
    if not rules:
        lines.append("> producer 甄别后无实施条目（RS 需求全为建议不做，见下）——闸口①人拍板。")
        lines.append("")
    lines.append(f"> DQ 由 dws-dq-producer 独立设计实现（读 RS+mapping 独立理解，不读主线实现），共 {len(rules)} 条。"
                 f"断言式=违规行探测器；对比式=独立重算比对。")
    lines.append("")
    lines.append("| # | 模式 | 检查范围 | 检查类型 | 规则名称 | 违规条件/比对口径 | 说明 |")
    lines.append("|---|------|----------|----------|----------|------------------|------|")
    for r in rules:
        waived = "（已豁免）" if r.get("waived") else ""
        amb_mark = " ⚠️歧义" if (r.get("ambiguities")) else ""
        lines.append(
            f"| {r['idx']} | {mode_cn.get(r.get('mode'), r.get('mode'))} | {r.get('scope', '')} "
            f"| {r.get('check_type', '')} | {r.get('rule_name', '')} "
            f"| `{r.get('violation_condition', '')}` | {r.get('rule_desc', '')}{waived}{amb_mark} |")
    lines.append("")
    amb = [(r, a) for r in rules for a in (r.get("ambiguities") or [])]
    if amb:
        lines.append("**歧义标注（producer 独立理解 mapping 发现的二义，闸口①待人裁决）：**")
        lines.append("")
        for r, a in amb:
            lines.append(f"- DQ{r['idx']}（{r['rule_name']}）: {a.get('note', '')}"
                         + (f" 取舍：{' / '.join(a.get('options') or [])}" if a.get("options") else ""))
        lines.append("")
    declined = dq.get("declined") or []
    if declined:
        lines.append("**建议不做（producer 甄别：结构类检查已被流程内建覆盖，做 DQ 是重复——闸口①人拍板，不同意则要求补做）：**")
        lines.append("")
        for d in declined:
            lines.append(f"- RS「{d.get('rs_rule_name', '?')}」: {d.get('reason', '')}")
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


def _locate_ts_md(ts: dict, build_dir: Path) -> Path:
    """按产出标准寻址 ts.md：{f_table 短名}_ts.md（3322a75 命名标准，消费方适配）
    > ts.md（旧档兜底）。都无 → 返回标准名（供追加场景新建）。"""
    _f = ((ts.get("meta", {}) or {}).get("target", {}) or {}).get("f_table") or {}
    if not isinstance(_f, dict):
        _f = {}
    short = str(_f.get("table") or "ts")
    std = build_dir / f"{short}_ts.md"
    if std.exists():
        return std
    legacy = build_dir / "ts.md"
    if legacy.exists():
        return legacy
    return std


# ============================================================
# main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="DQ 校验渲染器（producer 的 dq.json+SQL -> 校验+补全+ts.md DQ 章节）")
    parser.add_argument("--ts", required=True, help="build/ts.json 路径")
    parser.add_argument("--dq-src", required=True, help="producer 产的 dq.json 路径（校验补全后原地写回）")
    parser.add_argument("--rs", default="", help="_internal/rs_input.json 路径（new-pipe 场景；opt 场景可省——源表集合自动从 ts.rules 派生）")
    parser.add_argument("--design-decisions", default="", help="_internal/design_decisions.yaml（读 dq 任务 project 覆盖，可选）")
    parser.add_argument("--schema-cache", default="", help="schema 缓存路径（可选；无则源表字段侧降 warn）")
    parser.add_argument("--dq-dir", default="", help="DQ SQL 目录（默认 ts 同级 dq/；opt 场景传 build/dq——SQL 在变更现场，校验后由 pipe cp 入临时档案）")
    parser.add_argument("--no-rs-contract", action="store_true",
                        help="opt 场景：跳过 N_DQ1-3 的 RS 对照（条目权威=baseline dq.json 清单+影响分析，不走新建的 RS 驱动契约）")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    dq_src_path = Path(args.dq_src)

    def _die(msg):
        print(f"错误: {msg}", file=sys.stderr)
        sys.exit(2)

    if not ts_path.exists():
        _die(f"ts.json 不存在: {ts_path}")
    if not dq_src_path.exists():
        _die(f"dq.json 不存在: {dq_src_path}（RS 有 DQ 需求时 dws-dq-producer 必须先交卷：dq.json + dq/*.sql）")
    rs_input = {}
    if args.rs:
        rs_path = Path(args.rs)
        if not rs_path.exists():
            _die(f"rs_input.json 不存在: {rs_path}")
        try:
            rs_input = json.loads(rs_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            _die(f"rs_input.json 解析失败: {e}")
    try:
        ts = json.loads(ts_path.read_text(encoding="utf-8"))
        dq_src = json.loads(dq_src_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _die(f"文件解析失败: {e}")

    design_decisions = {}
    dd_path = Path(args.design_decisions) if args.design_decisions else dq_src_path.parent / "_internal" / "design_decisions.yaml"
    if dd_path.exists():
        try:
            design_decisions = yaml.safe_load(dd_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            design_decisions = {}

    rules_in = dq_src.get("rules") or []
    declined_in = dq_src.get("declined") or []
    dq_dir = Path(args.dq_dir) if args.dq_dir else ts_path.parent / "dq"
    rs_dq = rs_input.get("dq_requirements", []) or []

    # schema_cache 缺省自动定位（precheck 产的公共信息——ts 同级 _internal/），
    # 不要求显式传参（2026-09-15 修复：此前缺省空导致每条规则误报"无 schema_cache"warn）
    cache_arg = args.schema_cache
    if not cache_arg:
        _auto = ts_path.parent / "_internal" / "schema_cache.json"
        if _auto.exists():
            cache_arg = str(_auto)

    rules_out, vr = validate_and_build(rs_input, ts, rules_in, dq_dir, cache_arg,
                                       rs_contract=not args.no_rs_contract,
                                       declined=declined_in)

    if vr.n_hard:
        print(f"DQ 校验失败（{vr.n_hard} 项硬阻断）：", file=sys.stderr)
        for ln in vr.report_lines():
            print(ln, file=sys.stderr)
        sys.exit(1)

    # 校验补全后原地写回 producer 的 dq.json（终态：补 idx/sql_file/mode/meta + dq 任务）
    f_meta = (ts.get("meta", {}).get("target", {}).get("f_table", {}) or {})
    dq = {
        "version": "1.0.0",
        "spec_type": "dq",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generated_by": "dws-dq-producer + assemble_dq",
        "meta": {
            "target_table": f"{f_meta.get('schema', '')}.{f_meta.get('table', '')}",
            "business_key": ts.get("design", {}).get("business_key", []),
        },
        "rules": rules_out,
    }
    if declined_in:
        dq["declined"] = declined_in
    dq_task = build_dq_task(ts, design_decisions)
    if dq_task:
        dq["tasks"] = {"dq": dq_task}
    dq_src_path.write_text(json.dumps(dq, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = _locate_ts_md(ts, ts_path.parent)
    if md_path.exists():
        patch_ts_md(md_path, dq, rs_dq)

    print(f"DQ 校验渲染完成: {dq_src_path}（{len(rules_out)} 条）")
    if dq_task:
        print(f"DQ 调度任务: {dq_task['task_name']} -> {dq_task['project_name']} / {dq_task['task_group']}")
    print(f"ts.md DQ 章节: 已渲染到 {md_path.name}——评审看 ts.md 的 DQ 表格")
    for ln in vr.report_lines():
        print(ln)
    sys.exit(0)


if __name__ == "__main__":
    main()
