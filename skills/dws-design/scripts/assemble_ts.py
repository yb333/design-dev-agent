#!/usr/bin/env python3
"""
TS 制品组装器: rs_input.json + design_decisions.yaml -> ts.json + ts.md

designer agent 产出 design_decisions.yaml(纯设计判断),
本脚本负责把确定性字段(类型/来源/注释)从 rs_input.json 搬进来,
组装出结构 100% 正确的 ts.json, 并渲染 ts.md。

组装时内置校验:
  - 字段完整性: design_decisions 的 field_targets 并集 == rs_input 所有 target_column
  - 规则无冲突: 同一 target_column 不能出现在多个规则的 field_targets
  - 字段可查: field_targets 里的名字必须在 rs_input 里找得到

用法:
  python assemble_ts.py \
    --rs 10_project_deliver/{资产名}/ddlc_design_dev/_internal/rs_input.json \
    --decisions 10_project_deliver/{资产名}/ddlc_design_dev/_internal/design_decisions.yaml \
    --outdir 10_project_deliver/{资产名}/ddlc_design_dev

退出码: 0=成功, 1=校验失败(设计决策有问题), 2=文件/解析错误
"""

import sys
import re
import json
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))
from config_paths import schedule_config_path

try:
    import yaml
except ImportError:
    print("错误: 需要 PyYAML。请运行 pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# ============================================================
# 中文 transform_rule -> 英文 transform_type 映射
# ============================================================
TRANSFORM_MAP = {
    "直接复制": "direct",
    "数据加工": "aggregate",
    "赋值": "assign",
    "序列": "sequence",
}

# 标准审计字段模板沉在 shared（precheck 也要读同一份标准）；此处 import 保持旧引用名不变
from dws_standards import STANDARD_AUDIT_TEMPLATE, STANDARD_AUDIT_NAMES

# 标准参数（所有资产默认都有，脚本自动注入，designer 无需声明）
# 加标准参数 = 在此列表追加一行（build_exec_params 通用循环处理，不改逻辑）
# 加新动态表达式 = 在 run_ut.py 的 DYNAMIC_EXPRS 追加（default_value 里 expr 引用）
# inject_when 枚举：always（所有资产）/ inline_init（inline init 模式）/ incremental（增量资产）
STANDARD_PARAMS = [
    {"name": "P_CYCLE_ID", "value_type": "string", "desc": "批次号",
     "inject_when": "always",
     "default_value": {"type": "dynamic", "expr": "today_ymdhms"}},
    {"name": "P_FLAG", "value_type": "string",
     "desc": "初始化控制：1=日增量（默认），2=初始化",
     "inject_when": "inline_init",
     "default_value": "1"},
    {"name": "P_START_DATE", "value_type": "date",
     "desc": "增量范围起点（上次调度时间，运行时平台注入；UT 用 default 兜底）",
     "inject_when": "incremental",
     "default_value": {"type": "dynamic", "expr": "yesterday_ymd"}},
    {"name": "P_END_DATE", "value_type": "date",
     "desc": "增量范围终点（当前时间，运行时平台注入；UT 用 default 兜底）",
     "inject_when": "incremental",
     "default_value": {"type": "dynamic", "expr": "today_ymd"}},
]


def _is_incremental_asset(decisions: dict) -> bool:
    """判断是否增量资产（有 init 段，或有 incremental_extract/merge 规则，或规则带 incremental 段）。"""
    if decisions.get("init"):
        return True
    for r in (decisions.get("rules") or []):
        if (r.get("step_type") or "") in ("incremental_extract", "merge"):
            return True
        if r.get("incremental"):
            return True
    return False


def _should_inject(when: str, decisions: dict) -> bool:
    """按 inject_when 枚举判断标准参数是否注入。加新条件 = 加枚举分支。"""
    if when == "always":
        return True
    if when == "inline_init":
        init_dec = decisions.get("init") or {}
        return isinstance(init_dec, dict) and (init_dec.get("group_mode") or "") == "inline"
    if when == "incremental":
        return _is_incremental_asset(decisions)
    return False


def build_exec_params(decisions):
    """组装 exec_params：标准参数按 inject_when 条件注入 + 业务参数透传。

    返回 {param_name: {value_type, desc, standard, default_value}}。
    standard=true 表示脚本注入（自带 default_value）；业务参数 default_value 由 designer 给。
    default_value 是 UT 兜底 + export 制品的默认值来源（运行时平台会覆盖）。
    """
    params = {}
    # 标准参数：通用循环（加标准参数 = 在 STANDARD_PARAMS 追加，不改这里）
    for sp in STANDARD_PARAMS:
        if _should_inject(sp.get("inject_when", "always"), decisions):
            params[sp["name"]] = {
                "value_type": sp["value_type"],
                "desc": sp["desc"],
                "standard": True,
                "default_value": sp.get("default_value", ""),
            }
    # 业务参数：designer 声明，透传 default_value
    for p in decisions.get("params", []):
        params[p["name"]] = {
            "value_type": p.get("value_type", "string"),
            "desc": p.get("desc", ""),
            "standard": False,
            "default_value": p.get("default_value", ""),
        }
    return params


def is_audit_field(fm: dict) -> bool:
    """判断字段是否审计字段：备注优先（含'审计字段'），字段名兜底（匹配标准名）。"""
    remark = (fm.get("remark") or "").strip()
    if "审计字段" in remark:
        return True
    target = (fm.get("target_column") or "").strip().lower()
    return target in STANDARD_AUDIT_NAMES


# ============================================================
# 数据流图渲染（ts.md §5 用 mermaid 呈现）
# ============================================================

# 维度表 schema（OR 关系：表名含 dim 或 schema 在此集合里，即判为维表）
DIM_SCHEMAS = {"dim", "dwrdim", "dwrdim_dw1"}


def is_dim_table(schema: str, table: str) -> bool:
    """判断是否维表（任一命中即维表）：
    1. 表名包含 'dim'
    2. schema ∈ {dim, dwrdim, dwrdim_dw1}

    维表在数据流图里不画节点，降级为步骤节点的标注（避免源表过多拥挤）。
    """
    if "dim" in (table or "").lower():
        return True
    if (schema or "").lower() in DIM_SCHEMAS:
        return True
    return False


def _sanitize_node_id(text: str) -> str:
    """mermaid 节点 ID 只能字母/数字/下划线。把 . - 等替换成 _。"""
    return re.sub(r'[^A-Za-z0-9_]', '_', text or "")


def _short_desc_for_mermaid(text: str, limit: int = 20) -> str:
    """截短设计意图用于 mermaid 节点 label（取第一个逗号/句号前，限长度）。"""
    if not text:
        return ""
    for sep in ["，", "。", ",", ".", "；"]:
        if sep in text:
            text = text.split(sep)[0]
            break
    return text[:limit] + "…" if len(text) > limit else text


def render_data_flow_mermaid(ts: dict) -> str:
    """从 ts.json 的 rules + data_flow 生成 mermaid flowchart TD 代码块。

    布局：上到下（TD），按 schedule_groups 分层。
    节点：表（源表/中间表/目标表/视图）+ 步骤（规则）混合。
    维表用 subgraph 框住，不画成主流程节点。
    无规则时返回空串。
    """
    rules = ts.get("rules", {})
    if not rules:
        return ""

    # 从 meta.source_tables 建表名→中文名映射
    meta_sources = {}
    for st in ts.get("meta", {}).get("source_tables", []):
        meta_sources[f"{st.get('schema','')}.{st.get('table','')}"] = st.get("table_cn", "")

    df = ts.get("data_flow", {})
    schedule_groups = df.get("schedule_groups", [])
    # 没有 schedule_groups → 按 exec_sequence 兜底
    if not schedule_groups:
        schedule_groups = [{"sequence": r.get("exec_sequence", 1), "rules": [code]}
                           for code, r in rules.items()]

    lines = ['```mermaid']
    lines.append('flowchart TD')
    lines.append('')

    # 节点ID → className 的映射（末尾用 class 语句批量赋类，兼容 Typora）
    node_classes = {}  # {node_id: class_name}
    all_dims = []  # 全局维表收集（去重），用于 subgraph

    # --- 收集源表节点（全局去重，跨规则共享） ---
    declared_sources = {}  # source_table_key → {schema, table, node_id}
    declared_targets = set()  # 已声明的产出表 node_id
    edges = []  # [(from_id, to_id, dashed)]

    for code in list(rules.keys()):
        rule = rules[code]
        for st in rule.get("source_tables", []):
            sch = st.get("schema", "")
            tbl = st.get("table", "")
            if not tbl:
                continue
            key = f"{sch}.{tbl}"
            if key in declared_sources:
                continue
            declared_sources[key] = {
                "schema": sch,
                "table": tbl,
                "node_id": "src_" + _sanitize_node_id(tbl),
            }

    # --- 按 schedule_groups 分层画节点和边 ---
    for group in schedule_groups:
        for code in group.get("rules", []):
            rule = rules.get(code)
            if not rule:
                continue

            target = rule.get("target_table", "")
            is_view = rule.get("is_view_step", False)
            step_id = "step_" + _sanitize_node_id(code)

            # 分类该规则的 source_tables
            fact_sources = []   # 非维表（画节点）

            for st in rule.get("source_tables", []):
                sch = st.get("schema", "")
                tbl = st.get("table", "")
                if not tbl:
                    continue
                if is_dim_table(sch, tbl):
                    # 维表收集到全局列表（去重），不画主流程节点
                    dim_key = f"{sch}.{tbl}"
                    if dim_key not in [d["key"] for d in all_dims]:
                        dim_cn = meta_sources.get(dim_key, "")
                        all_dims.append({"key": dim_key, "table": tbl, "schema": sch, "cn": dim_cn})
                else:
                    fact_sources.append((sch, tbl))

            # 步骤节点：用设计意图截短（不用维表标注）
            step_label = f'{code}'
            intent = rule.get("design_intent", "") or rule.get("rule_name", "")
            if intent:
                step_label += f' / {_short_desc_for_mermaid(intent)}'
            lines.append(f'  {step_id}("{step_label}")')
            node_classes[step_id] = "step"

            # 画非维表源表节点（schema.表名 + 中文名）+ 源表→步骤的边
            for sch, tbl in fact_sources:
                src_info = declared_sources.get(f"{sch}.{tbl}")
                if src_info:
                    src_id = src_info["node_id"]
                    if not src_info.get("_drawn"):
                        cn = meta_sources.get(f"{sch}.{tbl}", "")
                        label = f'{tbl}'
                        if sch:
                            label = f'{sch}.{tbl}'
                        if cn:
                            label += f'<br/>{cn}'
                        lines.append(f'  {src_id}["{label}"]')
                        src_info["_drawn"] = True
                        node_classes[src_id] = "source"
                    edges.append((src_id, step_id, False))

            # 画产出表节点 + 步骤→产出表的边
            if target:
                tgt_id = "tbl_" + _sanitize_node_id(target)
                if tgt_id not in declared_targets:
                    if is_view:
                        cls = "view"
                    elif "tmp" in target.lower():
                        cls = "intermediate"
                    else:
                        cls = "target"
                    lines.append(f'  {tgt_id}["{target}"]')
                    declared_targets.add(tgt_id)
                    node_classes[tgt_id] = cls
                edges.append((step_id, tgt_id, is_view))

        lines.append('')

    # --- 画中间表→后续步骤的边 ---
    for dep in df.get("dependencies", []):
        inter_tbl = dep.get("intermediate_table", "")
        to_code = dep.get("to", "")
        if inter_tbl and to_code:
            inter_id = "tbl_" + _sanitize_node_id(inter_tbl)
            step_id = "step_" + _sanitize_node_id(to_code)
            edges.append((inter_id, step_id, False))

    # --- 输出所有边 ---
    for from_id, to_id, dashed in edges:
        arrow = "-.->" if dashed else "-->"
        lines.append(f'  {from_id} {arrow} {to_id}')

    # --- classDef 样式定义 ---
    lines.append('')
    lines.append('  classDef source fill:#dbeafe,stroke:#3b82f6,stroke-width:1.5px,color:#1e3a5f')
    lines.append('  classDef step fill:#ede9fe,stroke:#8b5cf6,stroke-width:1.5px,color:#4c1d95')
    lines.append('  classDef intermediate fill:#f1f5f9,stroke:#64748b,stroke-width:1.5px,color:#334155,stroke-dasharray:5 3')
    lines.append('  classDef target fill:#dcfce7,stroke:#22c55e,stroke-width:2.5px,color:#166534')
    lines.append('  classDef view fill:#e0e7ff,stroke:#6366f1,stroke-width:1.5px,color:#3730a3,stroke-dasharray:5 3')
    lines.append('  classDef dim fill:#fef3c7,stroke:#f59e0b,stroke-width:1px,color:#78350f')

    # --- 维表 subgraph（框住所有维表，视觉上跟主流程分开）---
    if all_dims:
        lines.append('')
        lines.append('  subgraph dims["关联维表"]')
        for d in all_dims:
            dim_id = "dim_" + _sanitize_node_id(d["table"])
            label = d["table"]
            if d["cn"]:
                label += f'<br/>{d["cn"]}'
            lines.append(f'    {dim_id}["{label}"]')
            node_classes[dim_id] = "dim"
        lines.append('  end')

    # --- class 语句批量赋类（兼容 Typora，不用 ::: 内联）---
    # 按 class_name 分组节点
    by_class = {}
    for nid, cls in node_classes.items():
        by_class.setdefault(cls, []).append(nid)
    for cls, nids in by_class.items():
        lines.append(f'  class {",".join(nids)} {cls}')

    lines.append('```')

    return "\n".join(lines)


# ============================================================
# 校验
# ============================================================
def validate_decisions(decisions, field_map):
    """校验 design_decisions 的字段分配是否和 rs_input 一致。

    field_map: { target_column: field_mapping_record }
    返回 errors 列表(空=通过)。

    多步骤模型下的字段分配语义：
    - field_targets 表示该规则的 target_table 包含哪些字段
    - 同一字段名可以出现在不同规则的 field_targets（中间表和目标表都有 user_id）
    - 但同一张表不能被多个规则重复声明同一字段（同表内重复才报错）
    - 覆盖完整性：目标表（target_role=target）的规则并集必须覆盖 rs_input 所有字段
    """
    errors = []

    rules = decisions.get("rules", [])
    if not rules:
        errors.append("design_decisions 里没有定义任何规则(rules 为空)")
        return errors

    rs_fields = set(field_map.keys())

    # 按 (table_short, field) 维度查重——同一字段可跨表，但不能在同表重复
    # ★ build_mode 分流：accumulate（累积共建）模式允许同表字段重叠，transform（默认）严格查重
    seen_table_fields = {}  # (table_short, field) -> rule_code
    # 累积共建表集合（build_mode=accumulate 的表，字段可重叠不报 C9）
    accumulate_tables = set()
    for tbl_short_cfg, tbl_cfg in decisions.get("tables", {}).items():
        if (tbl_cfg.get("build_mode", "transform") if isinstance(tbl_cfg, dict) else "transform") == "accumulate":
            accumulate_tables.add(tbl_short_cfg)
    # 收集目标表（target_role=target 或无 target_role 的规则）覆盖的字段
    target_assigned = set()

    for rule in rules:
        code = rule.get("rule_code", "??")
        targets = rule.get("field_targets", [])
        if not targets:
            errors.append(f"规则 {code} 的 field_targets 为空")
            continue

        tbl = rule.get("target_table", "")
        tbl_short = tbl.rsplit(".", 1)[-1] if "." in tbl else tbl
        is_target = rule.get("target_role", "target") == "target"
        is_accumulate = tbl_short in accumulate_tables

        for t in targets:
            key = (tbl_short, t)
            if key in seen_table_fields:
                # accumulate 模式允许同表字段重叠（多来源共建），不报 C9
                if not is_accumulate:
                    errors.append(
                        f"字段 '{t}' 在表 '{tbl_short}' 重复分配: "
                        f"同时在 {seen_table_fields[key]} 和 {code} 里"
                        f"（若为累积共建表，请在 tables.{tbl_short}.build_mode 标 accumulate）"
                    )
            else:
                seen_table_fields[key] = code

            # 字段名必须在 rs_input 里找得到
            if t not in field_map:
                errors.append(
                    f"规则 {code} 的 field_targets 里 '{t}' 在 rs_input.json 里找不到"
                    f"(检查字段名拼写)"
                )

            # 目标表规则覆盖的字段计入完整性检查
            if is_target:
                target_assigned.add(t)

    # 覆盖完整性：目标表规则必须覆盖 rs_input 所有字段
    # （中间表的字段不要求覆盖 rs_input——它们可能是 designer 自建的聚合字段）
    missing = rs_fields - target_assigned
    if missing:
        errors.append(
            f"以下字段在 rs_input.json 里定义了, 但没有分配到任何目标表规则"
            f"(target_role=target): {sorted(missing)}"
        )

    # write_condition 校验：非全量 load_mode 必填且不含中文
    import re
    needs_condition = {"truncate_partition", "delete", "merge_into", "update"}
    for rule in rules:
        code = rule.get("rule_code", "??")
        load_mode = rule.get("load_mode", "truncate_table")
        cond = (rule.get("write_condition", "") or "").strip()
        if load_mode in needs_condition:
            if not cond:
                errors.append(
                    f"规则 {code} 的 load_mode={load_mode} 需要 write_condition"
                    f"（merge_into/update填ON条件如'T.id=T1.id'，"
                    f"truncate_partition填分区名，delete填删除WHERE）"
                )
            elif re.search(r'[\u4e00-\u9fff]', cond):
                errors.append(
                    f"规则 {code} 的 write_condition 含中文（应为SQL片段）: {cond}"
                )

    return errors


# ============================================================
# 五层校验契约（新增）
# ============================================================
# ValidationResult: 按层收集校验结果，替代原来的 errors 平铺列表
# 校验分三级：
#   hard（硬阻断）：结构上不可能对，exit 1
#   soft（软阻断）：默认拦，但有合法通道可填 exemptions 放行
#   warn（提示）：可疑不致命
class ValidationResult:
    """按层组织的校验结果。"""

    LAYER_ORDER = [
        ("L0", "第0层-锚点"),
        ("L1", "第1层-字段血缘"),
        ("L2", "第2层-加工路径"),
        ("L3", "第3层-增量"),
        ("L4", "第4层-工程保障"),
        ("LC", "横切"),
        ("LA", "累积共建"),
        ("LD", "DQ"),
        ("LI", "初始化设计"),
    ]

    def __init__(self):
        # list of {"layer", "code", "target", "level", "msg"}
        # 用 list 而非 dict：同 code 多条错误（如多条 C9 重复字段）都保留
        self.items: list[dict] = []

    def add_hard(self, layer: str, code: str, msg: str):
        self.items.append({"layer": layer, "code": code, "target": "", "level": "hard", "msg": msg})

    def add_soft(self, layer: str, code: str, msg: str, target: str = ""):
        self.items.append({"layer": layer, "code": code, "target": (target or "").strip().lower(), "level": "soft", "msg": msg})

    def add_warn(self, layer: str, code: str, msg: str):
        self.items.append({"layer": layer, "code": code, "target": "", "level": "warn", "msg": msg})

    def _is_exempted(self, code: str, target: str, exemptions: list) -> bool:
        """检查某条软阻断是否被豁免。target 用于匹配豁免对象（大小写不敏感）。"""
        t = (target or "").strip().lower()
        for ex in exemptions or []:
            if ex.get("code") == code:
                ex_target = (ex.get("target", "") or "").strip().lower()
                # target 空匹配（code-only 豁免）或精确匹配
                if ex_target == "" or ex_target == t:
                    return True
        return False

    def hard_errors(self, exemptions: list = None) -> list[tuple[str, str, str]]:
        """返回所有硬阻断项（含被未豁免的软阻断升级）。"""
        exemptions = exemptions or []
        out = []
        for info in self.items:
            if info["level"] == "hard":
                out.append((info["layer"], info["code"], info["msg"]))
            elif info["level"] == "soft":
                # 软阻断：检查是否豁免（用该条携带的 target 匹配）
                if not self._is_exempted(info["code"], info.get("target", ""), exemptions):
                    out.append((info["layer"], info["code"], info["msg"]))
        return out

    def soft_errors(self, exemptions: list = None) -> list[tuple[str, str, str]]:
        """返回所有软阻断项（用于单独提示可填豁免放行）。"""
        exemptions = exemptions or []
        out = []
        for info in self.items:
            if info["level"] == "soft" and not self._is_exempted(info["code"], info.get("target", ""), exemptions):
                out.append((info["layer"], info["code"], info["msg"]))
        return out

    def warnings(self) -> list[tuple[str, str, str]]:
        return [(info["layer"], info["code"], info["msg"]) for info in self.items if info["level"] == "warn"]

    def format_report(self, exemptions: list = None) -> str:
        """按层分组输出校验报告。"""
        exemptions = exemptions or []
        layer_names = dict(self.LAYER_ORDER)
        hards = self.hard_errors(exemptions)
        softs = self.soft_errors(exemptions)
        warns = self.warnings()

        if not hards and not softs and not warns:
            return ""

        lines = []
        # 硬阻断区：含未豁免的软阻断（完整 msg，因为这些会拦住）
        if hards:
            # 区分真硬阻断 vs 未豁免软阻断（后者提示可豁免）
            lines.append(f"❌ 设计校验失败（{len(hards)} 项阻断）:")
            for layer, code, msg in hards:
                lines.append(f"  [{layer_names.get(layer, layer)}] {code}: {msg}")
        # 软阻断提示区：只列出 code+target（完整 msg 已在上面阻断区），告诉用户哪些可填豁免
        if softs:
            lines.append(f"\n⏸ 其中 {len(softs)} 项是软阻断，可填 design_decisions.exemptions 放行（需说明理由，闸口①可见）:")
            seen = set()
            for layer, code, msg in softs:
                key = (layer, code)
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"  [{layer_names.get(layer, layer)}] {code} —— 在 exemptions 填 {{code: \"{code}\", target: \"...\", reason: \"...\"}}")
        if warns:
            lines.append(f"\n⚠ 提示（{len(warns)} 项，不阻断）:")
            for layer, code, msg in warns:
                lines.append(f"  [{layer_names.get(layer, layer)}] {code}: {msg}")
        return "\n".join(lines)


def validate_quartz_cron(cron: str) -> list[str]:
    """校验 Quartz 6 段 cron 表达式。返回错误列表（空=合法）。

    Quartz 格式：秒 分 时 日 月 周（6 段），支持修饰符 * ? , - / L W #
    """
    if not cron or not cron.strip():
        return ["cron 为空"]
    parts = cron.strip().split()
    if len(parts) != 6:
        return [f"cron 应为 6 段（秒 分 时 日 月 周），当前 {len(parts)} 段: '{cron}'"]

    # 每段允许的字符：数字 + 修饰符 * ? , - / L W # + 字母（Quartz 周支持 MON-SUN，月支持 JAN-DEC）
    import re
    valid_pat = re.compile(r"^[0-9A-Za-z*\?,\-/LW#]+$")
    errors = []
    field_names = ["秒", "分", "时", "日", "月", "周"]
    ranges = [(0, 59), (0, 59), (0, 23), (1, 31), (1, 12), (1, 7)]
    for i, (part, fname, (lo, hi)) in enumerate(zip(parts, field_names, ranges)):
        if not valid_pat.match(part):
            errors.append(f"cron 第{i+1}段({fname}) '{part}' 含非法字符")
            continue
        # 单值范围检查（只查纯数字单值，含修饰符/字母的跳过——组合由平台解析）
        if part.isdigit():
            v = int(part)
            if not (lo <= v <= hi):
                errors.append(f"cron 第{i+1}段({fname}) 值 {v} 越界（应为 {lo}-{hi}）")
    return errors


def _table_short(name: str) -> str:
    """取表短名（去掉 schema 前缀）。"""
    return name.rsplit(".", 1)[-1] if "." in name else name


def run_all_validations(decisions: dict, rs_input: dict, field_map: dict,
                        schema_cache_path=None) -> ValidationResult:
    """运行五层校验全集。返回 ValidationResult。

    存量校验（C7-C13）通过 validate_decisions 调用，结果并入 L1/L4。
    新增校验按层独立函数。schema_cache_path 可选——传了才做 N30 join 字段存在性
    硬校验（未连库无缓存时降为单条 warn 提示）。
    """
    vr = ValidationResult()
    rules = decisions.get("rules", [])

    # 存量校验 C7-C13 → 并入相应层（C7-C11 归 L1，C12-C13 归 L4）
    legacy_errors = validate_decisions(decisions, field_map)
    for err in legacy_errors:
        # 按 error 文本特征归类层
        if "write_condition" in err or "load_mode" in err:
            vr.add_hard("L4", "C12_13", err)
        elif "rules 为空" in err:
            vr.add_hard("L1", "C7", err)
        else:
            vr.add_hard("L1", "C8_11", err)

    # rules 为空时，后续校验无意义（与存量 C7 早退一致）
    if not rules:
        return vr

    # ============================================================
    # 第0层 锚点（N1-N4）
    # ============================================================
    # N1 grain 非空（每张目标表）
    for rule in rules:
        if rule.get("target_role", "target") != "target":
            continue
        grain = rule.get("grain") or {}
        if not isinstance(grain, dict):
            grain = {}
        if not (grain.get("input") or "").strip() or not (grain.get("output") or "").strip():
            vr.add_hard("L0", "N1", f"规则 {rule.get('rule_code','?')} 的 grain.input/output 为空（必须声明产出表粒度）")

    # N2 business_key 非空
    business_key = decisions.get("business_key") or []
    if not business_key:
        vr.add_hard("L0", "N2",
                    "business_key 为空。修正：填 business_key 为能唯一框定产出表一行的字段组合"
                    "（通常取 mapping/RS 标的主键，粒度变化时补字段），"
                    "并在 business_key_design 论证。这是第0层锚点，后续加工和 UT 验证都基于此。")

    # N3 business_key_design 论证完整
    bkd = decisions.get("business_key_design") or {}
    if not isinstance(bkd, dict):
        bkd = {}
    input_key = bkd.get("input_key") or []
    adjusted = bkd.get("adjusted", False)
    reason = (bkd.get("reason") or "").strip()
    if not input_key:
        vr.add_hard("L0", "N3", "business_key_design.input_key 为空（应填 mapping/RS 标注的主键）")
    if adjusted and not reason:
        vr.add_hard("L0", "N3", "business_key_design.adjusted=true 但 reason 为空（调整了主键必须说明原因）")
    if not adjusted and not reason:
        vr.add_hard("L0", "N3", "business_key_design.reason 为空（adjusted=false 时可写'沿用输入主键，产出粒度未变'）")

    # N4 business_key 字段在目标表存在
    # 目标表字段 = target_role=target 规则的 field_targets 并集
    target_fields = set()
    for rule in rules:
        if rule.get("target_role", "target") == "target":
            target_fields.update(rule.get("field_targets") or [])
    for k in business_key:
        if k not in target_fields:
            vr.add_hard("L0", "N4", f"business_key 字段 '{k}' 不在目标表的字段中（检查拼写或补字段）")

    # ============================================================
    # 第1层 N5（加工字段缺 design_logic）—— 从 missing_logic 收集
    # 注意：这里复用 build_rule 的逻辑判断，但 main 里已经算过。
    # 为避免重复，N5 在 main 里基于 assemble_ts 返回的 missing_logic 注入。
    # 此处不重复算。

    # ============================================================
    # 第2层 加工路径（N6-N12, N10b/c/d）
    # ============================================================
    valid_step_types = {"full", "aggregate", "incremental_extract", "merge"}
    valid_target_roles = {"intermediate", "target"}

    # 收集中间表信息
    intermediate_tables = {}  # tbl_short -> [rule_codes]
    target_rule_codes = set()
    rule_seq = {}  # rule_code -> exec_sequence
    all_rule_codes = set()
    for rule in rules:
        code = rule.get("rule_code", "?")
        all_rule_codes.add(code)
        rule_seq[code] = rule.get("exec_sequence", 1)
        st = rule.get("step_type", "full")
        tr = rule.get("target_role", "target")
        tbl_short = _table_short(rule.get("target_table", ""))

        # N6 step_type 合法
        if st not in valid_step_types:
            vr.add_hard("L2", "N6", f"规则 {code} 的 step_type='{st}' 不合法（应为 full/aggregate/incremental_extract/merge）")
        # N7 target_role 合法
        if tr not in valid_target_roles:
            vr.add_hard("L2", "N7", f"规则 {code} 的 target_role='{tr}' 不合法（应为 intermediate/target）")
        # N8 矛盾组合（只禁两种）
        if tr == "intermediate" and st == "merge":
            vr.add_hard("L2", "N8", f"规则 {code} 矛盾：target_role=intermediate + step_type=merge（中间表不会是合并步骤）")
        if tr == "target" and st == "incremental_extract":
            vr.add_hard("L2", "N8", f"规则 {code} 矛盾：target_role=target + step_type=incremental_extract（目标表不会是取数到tmp）")

        if tr == "intermediate":
            intermediate_tables.setdefault(tbl_short, []).append(code)

    # N9 intermediate 的 produces_for 非空
    for rule in rules:
        if rule.get("target_role", "target") == "intermediate":
            code = rule.get("rule_code", "?")
            pf = rule.get("produces_for") or []
            if not pf:
                vr.add_hard("L2", "N9", f"规则 {code} 是中间表(intermediate)但 produces_for 为空（中间表必须声明被谁消费）")

    # N10 下游 reads 非空（merge 必须；full 有中间表时必须；无中间表放行）
    has_intermediate = len(intermediate_tables) > 0
    for rule in rules:
        code = rule.get("rule_code", "?")
        st = rule.get("step_type", "full")
        reads = rule.get("reads") or []
        if st == "merge" and not reads:
            vr.add_hard("L2", "N10", f"规则 {code} 是 merge 步骤但 reads 为空（合并必须读中间表）")
        if st == "full" and has_intermediate and not reads:
            # full 装配步骤应读中间表（但排除 full 产中间表的情况）
            if rule.get("target_role", "target") == "target":
                vr.add_hard("L2", "N10", f"规则 {code} 是 full(target) 但 reads 为空（存在中间表时，装配步骤必须读中间表）")

    # N10b 每张产出的中间表必须被某下游 reads 引用
    all_reads = set()
    for rule in rules:
        for r in _reads_tables(rule.get("reads")):
            all_reads.add(_table_short(r))
    for tbl_short, producers in intermediate_tables.items():
        if tbl_short not in all_reads:
            vr.add_hard("L2", "N10b", f"中间表 '{tbl_short}' 产出了但没有下游 reads 引用它（悬空中间表）")

    # N10c/N10d 依赖顺序 + 循环检测（基于 produces_for 图）
    # 构建 produces_for 边：A produces_for B 表示 A->B
    edges = []  # (from_code, to_code)
    for rule in rules:
        a = rule.get("rule_code", "?")
        for b in rule.get("produces_for") or []:
            edges.append((a, b))

    # N11 produces_for 指向的 rule_code 存在
    for a, b in edges:
        if b not in all_rule_codes:
            vr.add_hard("L2", "N11", f"规则 {a} 的 produces_for 指向 '{b}'，但该规则不存在")

    # N12 reads 指向的表存在（∈ intermediate 产出的表）；自引用例外
    intermediate_table_names = set(intermediate_tables.keys())
    for rule in rules:
        code = rule.get("rule_code", "?")
        own_tbl = _table_short(rule.get("target_table", ""))
        for r in _reads_tables(rule.get("reads")):
            r_short = _table_short(r)
            if r_short == own_tbl:
                continue  # 自引用例外（累积共建场景），不校验存在性
            if r_short not in intermediate_table_names:
                vr.add_hard("L2", "N12", f"规则 {code} 的 reads 指向 '{r}'，但没有中间表规则产出该表")

    # N10c 依赖顺序：produces_for A->B 则 seq(A) < seq(B)
    for a, b in edges:
        if b not in all_rule_codes:
            continue  # N11 已报
        sa, sb = rule_seq.get(a), rule_seq.get(b)
        if sa is not None and sb is not None and sa >= sb:
            vr.add_hard("L2", "N10c", f"依赖顺序错误：{a}(seq={sa}) produces_for {b}(seq={sb})，应满足 seq({a}) < seq({b})")

    # N10d 循环依赖检测（DFS）
    def detect_cycle(graph_edges):
        from collections import defaultdict
        g = defaultdict(list)
        nodes = set()
        for f, t in graph_edges:
            g[f].append(t)
            nodes.add(f)
            nodes.add(t)
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in nodes}
        cycle_path = []

        def dfs(n, path):
            color[n] = GRAY
            for nb in g.get(n, []):
                if nb not in color:
                    continue
                if color[nb] == GRAY:
                    return path + [n, nb]
                if color[nb] == WHITE:
                    res = dfs(nb, path + [n])
                    if res:
                        return res
            color[n] = BLACK
            return None

        for n in nodes:
            if color.get(n) == WHITE:
                res = dfs(n, [])
                if res:
                    return res
        return None

    cycle = detect_cycle(edges)
    if cycle:
        vr.add_hard("L2", "N10d", f"循环依赖：{' → '.join(cycle)}")

    # ============================================================
    # 第3层 增量（N14-N17）
    # ============================================================
    schedule = rs_input.get("schedule") or {}
    incremental_tables = schedule.get("incremental_tables") or []
    extract_rules = [r for r in rules if r.get("step_type") == "incremental_extract"]
    n_drivers = len(incremental_tables)
    n_extracts = len(extract_rules)

    # 只在标了增量时校验（避免全量场景误报）
    is_incremental_asset = bool(incremental_tables) or n_extracts > 0

    if is_incremental_asset:
        # N14（判据收紧）：资产标了增量但"完全没管增量"才硬阻断。
        # "完全没管" = 没有 extract 规则 + 没有任何规则的 incremental 段非空。
        # （旧版第三个析取"规则 source 涉驱动表"已删——规则读驱动表是数据来源的必然，
        #  恒为真，会让 N14 形同虚设。）
        has_extract = n_extracts > 0
        has_incremental_section = any(
            (r.get("incremental") or {}) and
            any((r.get("incremental", {}) or {}).get(f) for f in ("key", "filter"))
            for r in rules
        )
        if not has_extract and not has_incremental_section:
            vr.add_hard("L3", "N14",
                f"资产标了增量（{n_drivers} 张驱动表）但完全没增量处理（无 extract 规则、无 incremental 段）"
                f"——增量数据被当全量装载。增量资产的标准形态：增量取数（incremental_extract→tmp，"
                f"加工可并入此步）+ 终态规则增量更新目标表（merge_into 等），至少两个规则，"
                f"见 incremental-playbook §二")

        # N28（hard）：增量资产至少两个规则，终态必须是独立的增量更新规则——杜绝单规则直灌。
        # 不论单规则是 full（全量心智错装增量）还是带 incremental 段的直灌，都不被支持：
        # 取数与写目标分离是平台调度/重跑/排错的稳定结构。
        if len(rules) < 2:
            vr.add_hard("L3", "N28",
                f"增量资产只有 {len(rules)} 个规则——至少两个：增量取数（incremental_extract→tmp，"
                f"加工可并入此步）+ 终态规则以增量写入方式更新目标表（merge_into/no_delete/delete/"
                f"truncate_partition）。单规则直灌目标表不被支持（见 incremental-playbook §二铁律）")

        # N15 extract 的 incremental{} 填全（仅在存在 extract 规则时查）
        for rule in extract_rules:
            code = rule.get("rule_code", "?")
            inc = rule.get("incremental") or {}
            if not isinstance(inc, dict):
                inc = {}
            for f in ("key", "filter", "init_filter"):
                if not (inc.get(f) or "").strip():
                    vr.add_hard("L3", "N15", f"规则 {code} 是 incremental_extract 但 incremental.{f} 为空（增量取数必须有 {f}）")

        # N16（降 warn）：每张驱动表的增量字段是否出现在增量范围里。
        # 这是语义判断（取决于该表字段是否落到目标），校验只提示，由 designer + 闸口①保证。
        # 收集所有增量规则（extract + 有 incremental 段的规则）引用的增量字段
        all_inc_keys = set()
        for r in rules:
            inc = r.get("incremental") or {}
            k = (inc.get("key") or "").strip().lower()
            if k:
                all_inc_keys.add(k)
        for dt in incremental_tables:
            drv_table = (dt.get("source_table") or "").strip()
            drv_key = (dt.get("incremental_key") or "").strip().lower()
            if drv_key and drv_key not in all_inc_keys:
                vr.add_warn("L3", "N16", f"驱动表 '{drv_table}' 的增量字段 '{drv_key}' 未在任何规则的 incremental.key 中出现——确认该表的变化已被增量范围覆盖（并集场景检查 OR 条件是否覆盖每张驱动表）")

    # N_INIT2（hard）：增量目标规则 load_mode 不能是 truncate_table（全删全插 与增量矛盾）。
    # init/增量双管道模型的兜底：load_mode 是"增量写入方式"，init 的先删全插由 init 管道承担。
    # 触发锚点两个（任一）：规则自身声明了增量（incremental.filter / step_type=merge），
    # 或 RS 说了增量（incremental_tables 非空）——后者专抓"designer 什么都不标、按全量心智
    # 直灌增量数据"的低级错误（规则没声明增量时，规则锚定的判据全部失明）。
    # 不误伤：中间 tmp（intermediate）的 truncate 合法（tmp 每次重建）；非增量资产的 full 规则
    # truncate 合法；init.rules 不在 rules 里（独立 init 段），不触发。
    for rule in rules:
        code = rule.get("rule_code", "?")
        if rule.get("target_role") != "target":
            continue
        inc = rule.get("incremental") or {}
        has_inc_filter = isinstance(inc, dict) and bool((inc.get("filter") or "").strip())
        is_merge = rule.get("step_type") == "merge"
        rs_says_incremental = bool(incremental_tables)
        if (has_inc_filter or is_merge or rs_says_incremental) and rule.get("load_mode", "truncate_table") == "truncate_table":
            why = ("incremental.filter" if has_inc_filter
                   else "step_type=merge" if is_merge
                   else "RS 标了增量（增量驱动表非空）")
            vr.add_hard("L3", "N_INIT2",
                f"规则 {code} 是增量目标（{why}）但 load_mode=truncate_table"
                f"（全删全插），与增量语义矛盾：每次增量会清空历史。load_mode 应为增量写入方式"
                f"（merge_into/no_delete/delete/truncate_partition）；init 的先删全插由 init 管道承担"
                f"（见 incremental-playbook §八）")

    # ============================================================
    # 第4层 工程（N18-N21）
    # ============================================================
    sched = decisions.get("schedule") or {}
    # N18 schedule_type 合法
    stype = (sched.get("schedule_type") or "").strip()
    if stype and stype not in ("daily", "hourly", "realtime"):
        vr.add_hard("L4", "N18", f"schedule_type='{stype}' 不合法（应为 daily/hourly/realtime）")

    # N19 cron Quartz 6 段格式
    cron = (sched.get("cron") or "").strip()
    if cron:
        for cerr in validate_quartz_cron(cron):
            vr.add_hard("L4", "N19", cerr)

    # N_JOIN1 关联键类型对账闭合（rs_input._join_type_risks × designer joins）
    # 只在 precheck 检出跨大类风险对时启用（宁放过：无对账事实不硬判）。
    # 风险对要么在 joins 里显式声明 cast（coder 按声明写转换），要么业务豁免
    # （决策=接受）——不兼容必须变成设计产物里看得见的决策。
    join_risks = rs_input.get("_join_type_risks") or []
    if join_risks:
        from sql_parse import parse_join_pairs

        risky_quals = {}
        for rk in join_risks:
            key = frozenset(((rk.get("left") or "").lower(), (rk.get("right") or "").lower()))
            risky_quals[key] = rk
        exempt_conds = {
            (d.get("condition") or "").strip()
            for d in (rs_input.get("_join_type_decisions") or [])
            if (d.get("decision") or "").strip() == "接受"
        }
        # 别名 → schema.table（designer joins 用 rs_input 全局别名）
        alias_map = {}
        for st in rs_input.get("source_tables") or []:
            al = (st.get("source_alias") or "").strip().lower()
            if al:
                alias_map[al] = f"{(st.get('source_schema') or '').strip()}.{(st.get('source_table') or '').strip()}"
        for rule in rules:
            code = rule.get("rule_code", "?")
            for j in rule.get("joins") or []:
                cond = (j.get("condition") or "").strip()
                for (la, lc), (ra, rc) in parse_join_pairs(cond):
                    lq = f"{alias_map.get(la, '')}.{lc}".lower()
                    rq = f"{alias_map.get(ra, '')}.{rc}".lower()
                    hit = risky_quals.get(frozenset((lq, rq)))
                    if not hit:
                        continue
                    has_cast = bool((j.get("cast") or "").strip())
                    if not has_cast and cond not in exempt_conds:
                        vr.add_hard("L4", "N_JOIN1",
                            f"规则 {code} 的关联 {j.get('alias', '?')}（{cond}）键类型跨大类"
                            f"（{hit.get('left')} {hit.get('left_type')} ↔ "
                            f"{hit.get('right')} {hit.get('right_type')}）但未声明 cast 也未豁免"
                            f"——在 joins 里补 cast（显式转换表达式，如 a.x::numeric），"
                            f"或到 precheck 关联类型决策里选'接受'（业务豁免，需人确认）")

    # N20/N21 distribution_key（per-table，校验字段在所属表存在）
    dec_tables = decisions.get("tables") or {}
    # 构建每张表的字段集合（从 rules 的 field_targets 按表聚合）
    table_fields: dict[str, set] = {}
    for rule in rules:
        ts = _table_short(rule.get("target_table", ""))
        table_fields.setdefault(ts, set()).update(rule.get("field_targets") or [])

    valid_distribute_types = {"HASH", "ROUNDROBIN", "REPLICATION", ""}
    for tbl_short, tbl_cfg in dec_tables.items():
        if not isinstance(tbl_cfg, dict):
            continue
        dt = (tbl_cfg.get("distribute_type") or "").strip().upper()
        if dt not in valid_distribute_types:
            vr.add_hard("L4", "N20", f"表 '{tbl_short}' 的 distribute_type='{dt}' 不合法（应为 HASH/ROUNDROBIN/REPLICATION）")
        dkeys = tbl_cfg.get("distribution_key") or []
        tbl_flds = table_fields.get(tbl_short, set())
        for dk in dkeys:
            if dk not in tbl_flds:
                # 智能区分：带 schema 前缀（含 .）剥掉后能命中 → 格式问题（去掉前缀即可）；
                # 剥掉后也不命中 → 字段真不存在，列本表字段帮对照
                if "." in str(dk):
                    stripped = str(dk).split(".")[-1]
                    if stripped in tbl_flds:
                        vr.add_hard("L4", "N21",
                                    f"表 '{tbl_short}' 的 distribution_key '{dk}' 带了 schema 前缀——"
                                    f"字段名只写 '{stripped}'（不带 schema. 前缀），去掉前缀即可通过")
                        continue
                fld_preview = ", ".join(sorted(tbl_flds)[:10]) + ("..." if len(tbl_flds) > 10 else "")
                vr.add_hard("L4", "N21",
                            f"表 '{tbl_short}' 的 distribution_key 字段 '{dk}' 不在该表字段中"
                            f"（本表字段: {fld_preview}。注意：填字段名不带 schema 前缀）")

    # ============================================================
    # 横切（N22-N25）
    # ============================================================
    # N_AUDIT_TYPE 审计字段类型与标准不一致 → warn（组装时已强制标准类型，此为透明提示）
    for fm in (rs_input.get("field_mappings") or []):
        col = (fm.get("target_column") or "").lower()
        if col in STANDARD_AUDIT_TEMPLATE:
            mt = (STANDARD_AUDIT_TEMPLATE[col]["type"] or "").lower().replace(" ", "")
            it = (fm.get("target_type") or "").lower().replace(" ", "")
            if it and it != mt:
                vr.add_warn("LC", "N_AUDIT_TYPE",
                            f"审计字段 {col} 的 mapping 类型 '{fm.get('target_type')}' 与标准 "
                            f"'{STANDARD_AUDIT_TEMPLATE[col]['type']}' 不一致，已按标准覆盖（建议修正 mapping）")

    # 参数校验：业务参数 default_value 必填 + 不重复声明标准参数
    standard_names = {sp["name"].upper() for sp in STANDARD_PARAMS}
    for p in (decisions.get("params") or []):
        if not isinstance(p, dict):
            continue
        pname = (p.get("name") or "").strip()
        if not pname:
            continue
        if pname.upper() in standard_names:
            vr.add_warn("LC", "N_PARAM_DUP",
                        f"参数 {pname} 是标准参数（脚本按 inject_when 自动注入），无需声明")
            continue
        dv = p.get("default_value")
        if dv is None or (isinstance(dv, str) and dv == "") or (isinstance(dv, dict) and not dv):
            vr.add_hard("LC", "N_PARAM_DEFAULT",
                        f"业务参数 {pname} 缺 default_value（UT 兜底 + export 制品默认值都需要；运行时平台会覆盖）")

    # N22 增量 filter/init_filter 里 ${PARAM} 引用的参数都在 params 声明过
    declared_params = {p.get("name", "").upper() for p in (decisions.get("params") or []) if isinstance(p, dict)}
    # 标准参数按 inject_when 注入的，自动算"已声明"（filter 引用合法）
    for sp in STANDARD_PARAMS:
        if _should_inject(sp.get("inject_when", "always"), decisions):
            declared_params.add(sp["name"].upper())
    import re as _re2
    for rule in extract_rules:
        code = rule.get("rule_code", "?")
        inc = rule.get("incremental") or {}
        for f in ("filter", "init_filter"):
            val = inc.get(f) or ""
            for m in _re2.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", val):
                if m.upper() not in declared_params:
                    vr.add_hard("LC", "N22", f"规则 {code} 的 incremental.{f} 引用参数 '${{{m}}}' 未在 params 声明（标准参数 P_CYCLE_ID/P_FLAG/P_START_DATE/P_END_DATE 按条件自动注入，引用合法）")

    # N25 design_approach 非空（进 ts 文档）
    ca = decisions.get("complexity_analysis") or {}
    if not isinstance(ca, dict):
        ca = {}
    if not (ca.get("design_approach") or "").strip():
        vr.add_hard("LC", "N25", "complexity_analysis.design_approach 为空（设计思路必须写清，进 ts 文档）")

    # N23/N24 data_flow/schedule_groups rule 引用存在（warn）
    df = decisions.get("data_flow") or {}
    for dep in df.get("dependencies") or []:
        if not isinstance(dep, dict):
            continue
        for k in ("from", "to"):
            v = dep.get(k, "")
            if v and v not in all_rule_codes:
                vr.add_warn("LC", "N23", f"data_flow.dependencies 的 {k}='{v}' 不在规则列表中")
    for sg in df.get("schedule_groups") or []:
        if not isinstance(sg, dict):
            continue
        for r in sg.get("rules") or []:
            if r not in all_rule_codes:
                vr.add_warn("LC", "N24", f"schedule_groups 的规则 '{r}' 不在规则列表中")

    # ============================================================
    # 累积共建专项（N26-N27）
    # ============================================================
    accumulate_tables_set = set()
    for tbl_short, tbl_cfg in dec_tables.items():
        if isinstance(tbl_cfg, dict) and (tbl_cfg.get("build_mode", "transform")) == "accumulate":
            accumulate_tables_set.add(tbl_short)

    # N26 声明了 dedup_strategy 的规则，target/key/priority 必填
    for rule in rules:
        ds = rule.get("dedup_strategy")
        if not ds:
            continue
        code = rule.get("rule_code", "?")
        if not isinstance(ds, dict):
            vr.add_hard("LA", "N26", f"规则 {code} 的 dedup_strategy 格式错误（应为字典）")
            continue
        for f in ("target", "key", "priority"):
            v = ds.get(f)
            if f == "key":
                if not v:
                    vr.add_hard("LA", "N26", f"规则 {code} 的 dedup_strategy.key 为空（排重键必填）")
            elif not (v or "").strip():
                vr.add_hard("LA", "N26", f"规则 {code} 的 dedup_strategy.{f} 为空")

    # N27 accumulate 表有字段重叠但没声明 dedup_strategy → warn
    # 重新检测字段重叠（accumulate 模式下）
    overlap_per_table: dict[str, int] = {}
    field_rule_count: dict[tuple, int] = {}
    for rule in rules:
        ts = _table_short(rule.get("target_table", ""))
        if ts not in accumulate_tables_set:
            continue
        for t in rule.get("field_targets") or []:
            field_rule_count[(ts, t)] = field_rule_count.get((ts, t), 0) + 1
    for (ts, t), cnt in field_rule_count.items():
        if cnt > 1:
            overlap_per_table[ts] = overlap_per_table.get(ts, 0) + 1
    for ts, overlap_cnt in overlap_per_table.items():
        # 该表的规则有没有声明 dedup_strategy
        has_dedup = any(
            (r.get("dedup_strategy") or {}).get("target", "") and _table_short((r.get("dedup_strategy") or {}).get("target", "")) == ts
            for r in rules
        )
        if not has_dedup:
            vr.add_warn("LA", "N27", f"累积共建表 '{ts}' 有 {overlap_cnt} 个重叠字段但没声明 dedup_strategy（确认多来源是否有数据重叠需排重）")

    # ============================================================
    # DQ 一致性（N_DQ1-N_DQ3）—— DQ 完全跟随 RS
    # designer 是翻译者：RS 有 DQ 需求 → 翻译产 dq_rules；RS 无 → dq_rules 留空
    # ============================================================
    rs_dq = rs_input.get("dq_requirements", []) or []
    dec_dq = decisions.get("dq_rules", []) or []
    n_rs = len(rs_dq)
    n_dec = len(dec_dq)
    if n_rs > 0 and n_dec == 0:
        # N_DQ1（硬阻断）：RS 有 DQ 需求但 designer 没翻译产 dq_rules（漏翻译，"一次有一次没有"的根因）
        vr.add_hard("LD", "N_DQ1",
                    f"RS 有 {n_rs} 条 DQ 需求（dq_requirements），但 dq_rules 为空。"
                    f"RS 有 DQ 时 designer 必须翻译产 dq_rules（scope/check_type/rule_name 跟 RS 一致，"
                    f"rule_desc 写技术口径给 coder）")
    elif 0 < n_dec < n_rs:
        # N_DQ2（warn）：翻译后条数少于 RS，可能漏翻译
        vr.add_warn("LD", "N_DQ2",
                    f"RS 有 {n_rs} 条 DQ 需求，dq_rules 只翻译了 {n_dec} 条，核对是否漏翻译")
    elif n_rs == 0 and n_dec > 0:
        # N_DQ3（warn）：RS 无 DQ 需求但 designer 自行加了（DQ 是业务决策归 RS）
        vr.add_warn("LD", "N_DQ3",
                    f"RS 未提 DQ 需求（dq_requirements 为空），但 dq_rules 自行补充了 {n_dec} 条。"
                    f"DQ 是业务决策归 RS，请确认")

    # ============================================================
    # 初始化设计（LI 层）—— init 管道（与增量管道 rules 平行）
    # load_mode 装不下 init/增量两种写入 → init 单独成段。
    # 校验 designer 的 init 声明（装配器 build_init_section 按不变量补全输出）。
    # ============================================================
    init_dec = decisions.get("init")
    if init_dec and isinstance(init_dec, dict) and (init_dec.get("mode") or "").strip():
        i_mode = (init_dec.get("mode") or "").strip()
        i_group = (init_dec.get("group_mode") or "").strip()
        # mode / group_mode 合法值（hard）
        if i_mode not in ("explicit", "derive"):
            vr.add_hard("LI", "N_INIT_MODE",
                        f"init.mode='{i_mode}' 不合法（应为 explicit 或 derive）")
        if i_group not in ("inline", "separate"):
            vr.add_hard("LI", "N_INIT_GROUP",
                        f"init.group_mode='{i_group}' 不合法（应为 inline 同组p_flag 或 separate 独立规则组）")

        if i_mode == "explicit":
            # 增量管道里的 delta 机器 tmp（incremental_extract 产出的 intermediate 表）
            delta_tmp_tables = set()
            for r in rules:
                if r.get("step_type") == "incremental_extract":
                    tt = r.get("target_table", "")
                    if tt:
                        delta_tmp_tables.add(_table_short(tt).lower())
            for ir in (init_dec.get("rules") or []):
                icode = ir.get("rule_code") or "?"
                # N_INIT1（hard）：init 规则不应显式声明非 truncate 的 load_mode
                # （init 全是先删全插，load_mode 由装配器统一补 truncate_table，designer 不手填）
                ilm = (ir.get("load_mode") or "").strip()
                if ilm and ilm != "truncate_table":
                    vr.add_hard("LI", "N_INIT1",
                                f"init 规则 {icode} 显式声明 load_mode='{ilm}'，"
                                f"init 规则的 load_mode 由装配器统一补为 truncate_table（先删全插），不要手填")
                # N_INIT3（warn）：init 规则引用 delta 机器 tmp → 提示确认剥净
                for rd in _reads_tables(ir.get("reads")):
                    rd_short = _table_short(rd).lower()
                    if rd_short and rd_short in delta_tmp_tables:
                        vr.add_warn("LI", "N_INIT3",
                                    f"init 规则 {icode} 读取 '{rd}'（增量 delta 机器产出的 tmp）——"
                                    f"确认 delta 机器已剥净，init 是全量加工不需要增量隔离")
                # N_INIT4（warn）：既无 core_from 又无 field_logics → 口径为空
                if not (ir.get("core_from") or "").strip() and not (ir.get("field_logics") or {}):
                    vr.add_warn("LI", "N_INIT4",
                                f"init 规则 {icode} 既无 core_from 又无 field_logics——"
                                f"核心加工口径为空（field_logics 空时 coder 无口径可参考），确认是否需要")

    # ============================================================
    # N29（warn）：design_logic 照抄 mapping 原文（翻译者原则的产物探测）。
    # 只对"数据加工"类字段查（赋值/直取的 detail 本来就是字面量，查了全是噪音）；
    # 完全一致才报（改写过=拆解过的证据），warn 不拦，闸口①可见。
    # ============================================================
    for rule in rules:
        code = rule.get("rule_code", "?")
        for col, logic in (rule.get("field_logics") or {}).items():
            fm = field_map.get(col) or {}
            if (fm.get("transform_rule") or "").strip() != "数据加工":
                continue
            detail = (fm.get("transform_detail") or fm.get("mapping_expression") or "").strip()
            if not detail or detail in ("-", "无"):
                continue
            if str(logic).strip() == detail:
                vr.add_warn("L1", "N29",
                    f"规则 {code} 字段 {col} 的 design_logic 与 mapping 的 transform_detail 完全一致"
                    f"——疑似照抄原文。design_logic 应是拆解后的技术口径（收敛时机/过滤/去重/排序），"
                    f"不是业务描述搬运（翻译者原则）")

    # ============================================================
    # N30（hard/warn）：designer 声明的 joins 引用字段必须真实存在（第4层⓪的产物兜底）。
    # 校验对象是 designer 自己的声明（结构化产物），不是 mapping 原文——先例 N21
    # （distribution_key ∈ 表字段）。存在性查两处：源表查 schema_cache（precheck 连库产出），
    # tmp 表查产出规则的 field_targets。降误报：别名解析不了/表不在缓存 → 跳过不猜；
    # 无 cache 文件 → 整体降为单条 warn（未连库）。专抓 rn=1 类：条件里"裸字段 = 字面量"
    # （无别名前缀）在规则涉及的表里都查无 → 开窗残留。
    # ============================================================
    any_joins_declared = any(rule.get("joins") for rule in rules)
    # 别名 → schema.table（rs_input 全局源表别名；N30 解析 + N31/N32 绑定校验共用）
    alias_map = {}
    for st in rs_input.get("source_tables") or []:
        al = (st.get("source_alias") or "").strip().lower()
        if al:
            alias_map[al] = f"{(st.get('source_schema') or '').strip()}.{(st.get('source_table') or '').strip()}".lower()
    # tmp 表 → 字段集（产出规则的 field_targets；中间表的存在性查这里）
    tmp_fields = {}
    for r in rules:
        tt = _table_short(r.get("target_table", "")).lower()
        tmp_fields.setdefault(tt, set()).update(
            c.lower() for c in (r.get("field_targets") or []))
    cache_tables = {}
    if schema_cache_path is not None:
        try:
            _cand = Path(schema_cache_path)
            if _cand.exists():
                _raw = json.loads(_cand.read_text(encoding="utf-8"))
                for k, v in (_raw.get("tables") or {}).items():
                    cache_tables[k.lower()] = {c.lower() for c in (v or {})}
        except Exception:
            cache_tables = {}
    if any_joins_declared and schema_cache_path is not None and not cache_tables:
        vr.add_warn("L4", "N30",
            "声明了 joins 但未连库无 schema_cache——关联条件引用字段的存在性未校验"
            "（第4层⓪人工确认：条件里每个字段要在源表真实存在）")
    if cache_tables:
        from sql_parse import extract_condition_field_refs
        for rule in rules:
            code = rule.get("rule_code", "?")
            # 规则级 tmp 别名绑定（reads 对象形式声明；字符串形式默认别名=表短名）
            rule_tmp_alias = _rule_tmp_aliases(rule)
            # 待查文本：join 条件 + 规则级 filter（都是 designer 声明的结构化产物）
            texts = [((j.get("condition") or "").strip()) for j in rule.get("joins") or []]
            _flt = (rule.get("filter") or "").strip()
            if _flt:
                texts.append(_flt)
            for cond in texts:
                if not cond:
                    continue

                def _resolve(al: str):
                    """别名 → (表key, 是否tmp)。rs_input 全局别名优先，其次本规则 tmp 别名。"""
                    if al in alias_map:
                        return alias_map[al], False
                    if al in rule_tmp_alias:
                        return rule_tmp_alias[al], True
                    return None, False

                qualified_refs, _bare = extract_condition_field_refs(cond)
                alias_tables = set()
                for a, _c in qualified_refs:
                    tk, _is_tmp = _resolve(a)
                    if tk:
                        alias_tables.add(tk)
                # ① 别名限定引用 a.x：定位到表后查存在
                for al, col in qualified_refs:
                    tbl_key, is_tmp_ref = _resolve(al)
                    if tbl_key is None:
                        continue  # 别名解析不了（可能是函数/CTE 名）→ 跳过不猜
                    if is_tmp_ref or tbl_key in tmp_fields:
                        if col not in tmp_fields.get(tbl_key, set()):
                            vr.add_hard("L4", "N30",
                                f"规则 {code} 的条件（{cond}）引用 {al}.{col}，"
                                f"但中间表 {tbl_key} 的字段里没有 '{col}'——检查拼写或补 field_targets")
                        continue
                    fields = cache_tables.get(tbl_key)
                    if fields is None:
                        continue  # 表不在缓存 → 跳过（宁放过）
                    if col not in fields:
                        vr.add_hard("L4", "N30",
                            f"规则 {code} 的条件（{cond}）引用 {al}.{col}，"
                            f"但源表 {tbl_key} 里没有字段 '{col}'——join_condition 可能是"
                            f"copy 源代码的残留（典型 rn=1 开窗产物，表里无此字段）：不自行还原，"
                            f"需源端提供开窗定义，闸口①退回（见 SKILL 第4层⓪）")
                # ② 裸字段 = 字面量：在规则涉及的源表/tmp 字段里查，都查无才报
                if not alias_tables:
                    continue  # 条件里没有可解析的别名限定 → 无法圈定范围，跳过不猜
                for bcol in dict.fromkeys(_bare):
                    if bcol in ("and", "or", "not", "is", "in", "like", "between"):
                        continue
                    found = any(bcol in cache_tables.get(t, set()) for t in alias_tables) \
                        or any(bcol in fs for t, fs in tmp_fields.items() if t in alias_tables)
                    if not found:
                        vr.add_hard("L4", "N30",
                            f"规则 {code} 的条件（{cond}）引用裸字段 '{bcol}'，"
                            f"在涉及的源表里都不存在——典型是 copy 源代码的开窗残留"
                            f"（如 rn=1，ROW_NUMBER 取一行的逻辑字段）：真实语义是'从表按业务键不唯一、"
                            f"开窗取一行'，需源端提供开窗定义（按啥分组/排序），闸口①退回，"
                            f"designer 不自行还原（见 SKILL 第4层⓪）")

    # ============================================================
    # N31/N32 别名绑定（结构校验，不依赖 schema_cache）。
    # 别名是字段来源/关联条件的引用键：规则内一个别名只许指一张表（SQL 查询语义）。
    # N31（hard）：同一别名绑定到不同表（rs_input 源表 vs tmp、或 reads 内冲突）。
    # N32（warn）：joins/source_aliases 引用的别名无表绑定（tmp 别名要在 reads 对象形式声明）。
    # ============================================================
    for rule in rules:
        code = rule.get("rule_code", "?")
        rule_tmp_alias = _rule_tmp_aliases(rule)
        refs = {(a or "").strip().lower() for a in (rule.get("source_aliases") or [])}
        for j in rule.get("joins") or []:
            _ja = (j.get("alias") or "").strip() if isinstance(j, dict) else ""
            if _ja:
                refs.add(_ja.lower())
        if not refs and not rule_tmp_alias:
            continue
        bindings: dict = {}  # alias -> 表key（rs_input 全局的带 schema，tmp 为短名小写）
        for a in refs:
            if a in alias_map:
                bindings[a] = alias_map[a]
        conflicts = []
        for a, t in rule_tmp_alias.items():
            if a in bindings and bindings[a] != t:
                conflicts.append(f"{a}: {bindings[a]} ↔ {t}")
            bindings[a] = t
        if conflicts:
            vr.add_hard("L4", "N31",
                f"规则 {code} 的别名绑定冲突（一个别名在一个规则里只许指一张表）: "
                f"{'; '.join(conflicts)}——tmp 别名换个名字，或改 rs_input 源表别名（全局）")
        unbound = sorted(a for a in refs if a not in bindings)
        if unbound:
            vr.add_warn("L4", "N32",
                f"规则 {code} 引用的别名 {unbound} 没有表绑定（不在 rs_input 源表别名，"
                f"也不在本规则 reads 的 tmp 别名里）——tmp 表别名用 reads 对象形式声明"
                f"（如 reads: [{{table: tmp1, alias: t1}}]），否则 coder 无法定位该别名指哪张表")

    return vr


def _reads_tables(reads) -> list:
    """reads 表名列表（兼容对象形式 {table, alias} 与字符串形式）。"""
    out = []
    for r in reads or []:
        out.append(str(r.get("table") if isinstance(r, dict) else r))
    return out


def _rule_tmp_aliases(rule: dict) -> dict:
    """解析规则的 reads → {别名小写: tmp表短名小写}。字符串形式默认别名=表短名。"""
    out = {}
    for r in rule.get("reads") or []:
        if isinstance(r, dict):
            t_short = _table_short(str(r.get("table") or ""))
            a = ((r.get("alias") or "").strip() or t_short).lower()
        else:
            t_short = _table_short(str(r))
            a = t_short.lower()
        if t_short:
            out[a] = t_short.lower()
    return out


# ============================================================
# 组装 ts.json
# ============================================================
def build_field(field_rec, logic, rule_aliases, is_assembly=False, reads_tables=None,
                all_source_rows=None, tmp_source="", tmp_alias=""):
    """从 rs_input 的 field_mapping 记录 + design_logic 组装 ts 的 field 对象。

    field_rec: rs_input.field_mappings 的一条记录（取 target_type/transform_rule/design_logic 默认）
    logic: design_decisions 里该字段的 design_logic(可能为 None -> 用默认)
    rule_aliases: 该规则实际读的表别名集合（source_aliases ∪ joins 别名；装配规则判断"真源表直取 vs tmp 搬运"用）
    is_assembly: 是否装配/merge 规则（reads 非空）。装配规则字段默认直取（从临时表搬）。
    reads_tables: 装配规则读取的临时表名列表（用于生成"直取 tmp.xxx"的默认 logic）
    all_source_rows: 该 target_column 的所有 rs_input 来源行（多来源合并 source_fields 用）。
                     None 时用 field_rec 单行。field_type 只取 field_rec 的（对着目标，不对来源）。
    tmp_source: 该字段血缘归属的 tmp 表短名（产出它的前序规则的 target_table；
                调用方按 field_targets 血缘算出）。空时退 reads_tables[0]。
    tmp_alias: 该 tmp 在本规则的别名（reads 对象声明或默认表短名）——design_logic
               引用限定符用它（t1.a）；source_fields 的 alias 位也填它。
    """
    transform_rule = field_rec.get("transform_rule", "直接复制")
    transform_type = TRANSFORM_MAP.get(transform_rule, "direct")

    alias = field_rec.get("source_alias", "")
    source_column = field_rec.get("source_column", "")
    source_table = field_rec.get("source_table", "")
    target_column = field_rec.get("target_column", "")

    # design_logic + transform_type：根据规则角色 + designer 是否写了 logic 共同决定。
    # ★ 装配/merge 规则（reads 非空）的无 logic 字段 = 从临时表搬运——**必须在 direct 分支之前判**：
    #   否则 mapping 里"直接复制"的字段会先命中 direct 分支，产出"直取 ht.a"（step1 的源表别名，
    #   本规则根本不 FROM 它，coder 照写必炸 UT）。例外：字段来源别名在本规则实际读的表集合里
    #   （step2 join 进来的真源表直取）→ 保持源表直取。血缘归属的 tmp 由调用方精确传入。
    carried_from_tmp = False
    if logic:
        design_logic = logic
        # designer 显式写了口径 → 按原 transform_type（加工）走，不改
    elif transform_type == "assign":
        design_logic = "固定赋值"
    elif is_assembly:
        if transform_type == "direct" and alias and rule_aliases and alias in rule_aliases:
            # 字段来源 = 本规则 join 进来的真源表（如 step2 关联 cx 补取的字段）
            design_logic = f"直取 {alias}.{source_column}"
        else:
            # 来源属于前序规则（step1 的 ht 等）→ 本步从 tmp 搬运（引用限定符用 tmp 别名）
            transform_type = "direct"
            src_tbl = tmp_source or (reads_tables[0] if reads_tables else "临时表")
            src_ref = tmp_alias or src_tbl
            design_logic = f"直取 {src_ref}.{target_column}（前序步骤已加工，本步搬运）"
            carried_from_tmp = True
    elif transform_type == "direct":
        design_logic = f"直取 {alias}.{source_column}" if alias else f"直取 {source_table}.{source_column}"
    else:
        # 加工类字段没写 logic 是个问题, 但先给个占位, 校验层会警告
        design_logic = f"[需补充] 加工逻辑未写, transform_detail: {field_rec.get('transform_detail', '')}"

    # source_fields：装配规则的搬运字段指向 tmp（field 名 = target_column，前序已落同名；
    # alias 位填本规则的 tmp 别名），不能沿用 rs_input 的源表血缘（ht.a 会把 coder 引向不存在的 FROM）。
    if carried_from_tmp:
        _tbl = tmp_source or (reads_tables[0] if reads_tables else "临时表")
        source_fields_list = [{"table": _tbl, "field": target_column, "alias": tmp_alias or _tbl}]
    elif all_source_rows:
        source_fields_list = [
            {
                "table": r.get("source_table", ""),
                "field": r.get("source_column", ""),
                "alias": r.get("source_alias", ""),
            }
            for r in all_source_rows
            if r.get("source_column")  # 跳过无来源的（赋值/序列）
        ]
    else:
        source_fields_list = [
            {"table": source_table, "field": source_column, "alias": alias}
        ] if source_column else []

    # ★ 审计字段类型强制标准（平台契约，不因 mapping 输入漂移）：
    # mapping 提供的审计字段 target_type 与标准不一致时按 STANDARD_AUDIT_TEMPLATE 覆盖
    #（不一致本身由 precheck/校验 warn 提示，这里保证产出正确）
    fname = (field_rec.get("target_column") or "").lower()
    if fname in STANDARD_AUDIT_TEMPLATE:
        field_type = STANDARD_AUDIT_TEMPLATE[fname]["type"]
    else:
        field_type = field_rec.get("target_type", "")

    return {
        "target_field": field_rec.get("target_column", ""),
        "field_type": field_type,
        "field_comment": field_rec.get("target_column_cn", ""),
        "transform_type": transform_type,
        "source_fields": source_fields_list,
        "design_logic": design_logic,
    }


def build_rule(rule_dec, field_map, rs_source_tables, target_schema=""):
    """组装一个规则对象。字段定义不在此产出（由 build_tables 按表汇总）。
    target_schema：目标表 schema——自产中间表与目标表同 schema（建表在同一个库 schema 下），
    伪源表带上它，coder 的 FROM/JOIN 才能写全 schema.table。"""
    code = rule_dec.get("rule_code", "")
    targets = rule_dec.get("field_targets", [])
    logics = rule_dec.get("field_logics") or {}

    # 检查加工类字段是否写了 logic（字段定义已搬到 tables，这里只做口径完整性校验）
    # ★ 面向多步骤：reads 非空的规则（装配/merge，从临时表搬运）字段默认直取，不强制写 logic。
    # 只有 reads 为空的规则（extract/aggregate/full 单灌，字段在本规则加工）才要求加工字段写 logic。
    reads = rule_dec.get("reads") or []
    is_assembly_rule = bool(reads)  # 装配/merge 规则：字段从临时表搬，默认直取
    missing_logic = []
    for t in targets:
        rec = field_map.get(t)
        if not rec:
            continue
        logic = logics.get(t)
        transform_rule = rec.get("transform_rule", "直接复制")
        transform_type = TRANSFORM_MAP.get(transform_rule, "direct")
        if is_assembly_rule:
            continue  # 装配规则字段默认直取，不强制写 logic（designer 显式写了则当二次加工）
        if transform_type != "direct" and not logic and not is_audit_field(rec):
            missing_logic.append(t)

    # source_tables: 从 rs_input 的 source_tables 按别名补全 schema/table
    rs_sources = {st.get("source_alias", ""): st for st in rs_source_tables}
    rule_sources = []
    aliases = rule_dec.get("source_aliases") or []
    if not aliases:
        aliases = list(rs_sources.keys())
    for sa in aliases:
        rs_st = rs_sources.get(sa, {})
        rule_sources.append({
            "schema": rs_st.get("source_schema", ""),
            "table": rs_st.get("source_table", ""),
            "alias": sa,
        })

    # ★ 装配/merge 规则（reads 非空）：把 reads 的临时表也加进 source_tables（伪源表）。
    # reads 支持两种形式（向后兼容）：
    #   字符串 "tmp1"                → 别名默认 = 表短名
    #   对象 {table: tmp1, alias: t1} → 别名显式声明（规则内唯一，N31 校验）
    # ts 的 reads 保持表名列表（DAG 语义不变）；别名绑定进 source_tables 伪源表。
    reads = rule_dec.get("reads") or []
    read_entries = []  # [(表短名, 别名)]
    for r in reads:
        if isinstance(r, dict):
            r_tbl = str(r.get("table") or "")
            r_alias = (r.get("alias") or "").strip() or _table_short(r_tbl)
        else:
            r_tbl = str(r)
            r_alias = _table_short(r_tbl)
        r_short = _table_short(r_tbl) if "." in r_tbl else r_tbl
        read_entries.append((r_short, r_alias))
    existing_tables = {src["table"].split(".")[-1].lower() for src in rule_sources if src.get("table")}
    for r_short, r_alias in read_entries:
        if r_short and r_short.split(".")[-1].lower() not in existing_tables:
            rule_sources.append({
                "schema": target_schema,   # 自产 tmp 与目标表同 schema（coder 的 FROM 写全 schema.table）
                "table": r_short,
                "alias": r_alias,       # 临时表别名（reads 对象声明或默认表短名）
                "_from_reads": True,    # 标记来自 reads（临时表），区别于 rs_input 源表
            })

    return {
        "rule_name": rule_dec.get("rule_name", ""),
        "scenario": rule_dec.get("scenario", ""),
        "exec_sequence": rule_dec.get("exec_sequence", 1),
        "target_table": rule_dec.get("target_table", ""),
        "is_view_step": rule_dec.get("is_view_step", False),
        "design_intent": rule_dec.get("design_intent", ""),
        "load_mode": rule_dec.get("load_mode", "truncate_table"),
        "write_condition": rule_dec.get("write_condition", ""),  # 写入条件（MERGE ON/分区名/delete WHERE），designer填脚本只搬运
        "step_type": rule_dec.get("step_type", "full"),  # full/aggregate/incremental_extract/merge（design-guide §4.4）
        "target_role": rule_dec.get("target_role", "target"),  # intermediate/target
        "produces_for": rule_dec.get("produces_for", []) or [],  # 中间表规则填：产出供哪些规则消费
        "reads": [str(r.get("table") if isinstance(r, dict) else r) for r in reads],  # 表名列表（DAG）
        "incremental": rule_dec.get("incremental", {}),  # 增量设计（key/filter/init_time_range/init_strategy）
        "filter": (rule_dec.get("filter") or "").strip(),  # 规则级行过滤（WHERE，如 del_flag='N'；join 级限定在 joins.filter）
        "source_tables": rule_sources,
        "grain": rule_dec.get("grain", {}),
        "joins": rule_dec.get("joins", []),
        "join_safety": rule_dec.get("join_safety", []),
        "dedup_strategy": rule_dec.get("dedup_strategy") or {},  # 排重策略（累积共建场景，designer定策略coder翻译）
        "field_targets": targets,
        "field_logics": logics,
    }, missing_logic


def infer_logical_group(schema: str) -> str:
    """按 schema 推断逻辑集群（TO GROUP）。"""
    if not schema:
        return "LC_DW1"
    s = schema.lower()
    if "drt" in s:
        return "gtoup_version1"
    return "LC_DW1"


def build_tables(rules: dict, decisions: dict, field_map: dict, rs_input: dict, target_f_table: str) -> dict:
    """组装 tables 段（表实体，含字段定义 + 物理属性）。

    - 字段定义从 rs_input.field_mappings 按 rule→target_table→field_targets 分组搬入
    - 物理属性从 decisions.tables 取，缺失用默认
    - 审计字段补充到最终目标表的 fields
    - I 视图不放 tables（无物理属性，字段=F表镜像）
    """
    dec_tables = decisions.get("tables", {})
    supplemented = []  # 审计字段补充（由 build_design 算出，这里通过参数传入更解耦，但简化处理从 design 读不到）
    # 审计字段：从 rs_input 识别来源提供的 + 标准模板
    all_fm = rs_input.get("field_mappings", [])
    source_audit = [fm for fm in all_fm if is_audit_field(fm)]
    source_audit_names = {(fm.get("target_column") or "").lower() for fm in source_audit}
    supplemented_names = STANDARD_AUDIT_NAMES - source_audit_names

    # 最终目标表名（短名，不含 schema）
    final_table_short = target_f_table.rsplit(".", 1)[-1] if "." in target_f_table else target_f_table

    tables = {}
    for code, rule in rules.items():
        tbl = rule.get("target_table", "")
        if not tbl or rule.get("is_view_step"):
            continue
        tbl_short = tbl.rsplit(".", 1)[-1] if "." in tbl else tbl

        # 字段定义：从 field_map 按 field_targets 组装（design_logic 取规则 field_logics）
        # ★ 每个规则都算（不只首规则）：accumulate 多规则写同表时，各规则字段并集入表 +
        #   rule 级 source_refs 各归各的来源（不互相污染）
        rule_logics = rule.get("field_logics", {})
        rule_reads = rule.get("reads") or []
        # reads 的表短名（用于装配规则字段的"直取 tmp.xxx"默认 logic）
        reads_short = [_table_short(r) if ("." in str(r)) else r for r in rule_reads]
        is_asm = bool(rule_reads)  # 装配/merge 规则
        # 本规则实际读的别名集合 = source_aliases ∪ joins 别名（装配规则判断"真源表直取 vs tmp 搬运"：
        # 字段来源别名在集合里 = join 进来的真源表；不在 = 前序规则血缘，搬运）
        rule_alias_set = set(rule.get("source_aliases") or [])
        for _j in rule.get("joins") or []:
            _ja = (_j.get("alias") or "").strip() if isinstance(_j, dict) else ""
            if _ja:
                rule_alias_set.add(_ja)
        # tmp 表短名 → 别名（build_rule 已把 reads 别名放进伪源表；design_logic/切片引用用别名）
        tmp_alias_map = {str(st.get("table", "")).lower(): (st.get("alias") or "")
                         for st in (rule.get("source_tables") or []) if st.get("_from_reads")}
        # 字段 → 产出它的 tmp 表（血缘：本规则 reads 的表里，哪个前序规则的 field_targets 含该字段）
        reads_short_set = {str(r).lower() for r in reads_short}
        lineage: dict = {}
        if is_asm:
            for _code2, _rule2 in rules.items():
                _t2 = _rule2.get("target_table", "")
                _t2_short = (_t2.rsplit(".", 1)[-1] if "." in _t2 else _t2).lower()
                if _t2_short in reads_short_set:
                    for _fn in _rule2.get("field_targets", []):
                        lineage.setdefault(_fn.lower(), _t2_short)
        # 中间表 designer 声明的字段类型（自建字段/rs_input 没有的字段）
        dec_tbl_cfg = dec_tables.get(tbl_short, {})
        if not isinstance(dec_tbl_cfg, dict):
            dec_tbl_cfg = {}
        dec_tbl_fields = dec_tbl_cfg.get("fields") or {}  # {字段名: 类型}
        rule_field_objs = []  # [(target名, field对象)] 本规则的字段产出
        missing_types = []  # 找不到类型的字段（rs_input 没 + designer 没声明）
        for tname in rule.get("field_targets", []):
            rec = field_map.get(tname)
            # 收集该 target_column 的所有来源行（多来源合并 source_fields）
            all_source_rows = [fm for fm in all_fm if fm.get("target_column") == tname]
            if rec:
                _tmp_src = lineage.get(tname.lower(), "")
                f = build_field(rec, rule_logics.get(tname), rule_alias_set,
                                is_assembly=is_asm, reads_tables=reads_short,
                                all_source_rows=all_source_rows,
                                tmp_source=_tmp_src,
                                tmp_alias=tmp_alias_map.get(_tmp_src, ""))
            elif tname in dec_tbl_fields:
                # 中间表自建字段（rs_input 没有，designer 在 tables.fields 声明了类型）
                declared_type = dec_tbl_fields[tname]
                f = {
                    "target_field": tname,
                    "field_type": declared_type,
                    "field_comment": "",
                    "transform_type": "direct",
                    "source_fields": [],
                    "design_logic": f"中间表自建字段（designer 声明类型 {declared_type}）",
                }
            elif tname.lower() in STANDARD_AUDIT_NAMES:
                continue  # 审计字段后面统一补
            else:
                # rs_input 没有 + designer 没声明 → 类型缺失，记下来后面 warn
                missing_types.append(tname)
                f = {
                    "target_field": tname,
                    "field_type": "",
                    "field_comment": "",
                    "transform_type": "direct",
                    "source_fields": [],
                    "design_logic": "[类型缺失] rs_input 无此字段且 designer 未声明类型",
                }
            rule_field_objs.append((tname, f))
        if missing_types:
            import sys as _sys
            print(f"[warn] 表 {tbl_short} 以下字段类型缺失（rs_input 无 + designer 未在 tables.fields 声明）: {missing_types}", file=_sys.stderr)

        # ★ rule 级来源映射（coder 直取行的唯一口径；accumulate 同字段多来源各归各的规则）
        rule["source_refs"] = {}
        for _tn, _f in rule_field_objs:
            _sfs = _f.get("source_fields") or []
            if _sfs:
                _sf = _sfs[0]
                if _sf.get("alias") and _sf.get("field"):
                    rule["source_refs"][_tn] = f"{_sf['alias']}.{_sf['field']}"
                elif _sf.get("table") and _sf.get("field"):
                    rule["source_refs"][_tn] = f"{_sf['table']}.{_sf['field']}"

        # ★ accumulate 多规则写同表：字段并集（首声明者赢），物理属性保持首规则
        if tbl_short in tables:
            existing_names = {f["target_field"].lower() for f in tables[tbl_short]["fields"]}
            for _tn, _f in rule_field_objs:
                if _tn.lower() not in existing_names:
                    tables[tbl_short]["fields"].append(_f)
            continue

        # 判断表类型
        is_final = (tbl_short == final_table_short)
        tbl_type = "target" if is_final else "intermediate"

        fields = [_f for _tn, _f in rule_field_objs]

        # 目标表补充审计字段
        if is_final:
            for aname in supplemented_names:
                spec = STANDARD_AUDIT_TEMPLATE.get(aname, {})
                # 检查是否已在 fields 里（防重复）
                existing_names = {f["target_field"].lower() for f in fields}
                if aname.lower() not in existing_names:
                    fields.append({
                        "target_field": aname,
                        "field_type": spec.get("type", ""),
                        "field_comment": "审计字段（自动补充）",
                        "transform_type": "assign",
                        "source_fields": [],
                        "design_logic": f"固定赋值 {spec.get('default', '')}",
                    })

        # 物理属性
        dec_tbl = dec_tables.get(tbl_short, {})
        # schema 用于推断逻辑集群
        tbl_schema = ""
        for fm in all_fm:
            pass  # schema 从 target_table 或 meta 取更准
        # 从 target_table 拆 schema
        if "." in tbl:
            tbl_schema = tbl.split(".")[0]

        # 分布键：per-table 声明优先；没填则用旧版全局 distribution_key 兜底
        dec_dist = dec_tbl.get("distribution_key", [])
        if not dec_dist:
            dec_dist = decisions.get("distribution_key", [])

        # 分布方式：HASH（默认）/ ROUNDROBIN / REPLICATION
        # 有分布键 → HASH；无分布键 → ROUNDROBIN；designer 可显式指定
        distribute_type = dec_tbl.get("distribute_type", "")
        if not distribute_type:
            distribute_type = "HASH" if dec_dist else "ROUNDROBIN"

        tables[tbl_short] = {
            "type": tbl_type,
            "distribution_key": dec_dist,
            "distribute_type": distribute_type,
            "partition": dec_tbl.get("partition", ""),
            "storage": dec_tbl.get("storage", "column"),
            "logical_group": dec_tbl.get("logical_group", "") or infer_logical_group(tbl_schema),
            "fields": fields,
        }

    return tables


# ============================================================
# 调度任务路径配置（schedule_config.json）
# ============================================================

def load_schedule_config(config_path: str = "") -> dict:
    """读 schedule_config.json。未找到返回空 dict。

    实际配置在 ~/.config/opencode/schedule_config.json（install 时不覆盖已有，
    和 db-sources/platform_config 一致）。
    结构：{default: {project_name, task_group},
           schema_mappings: {schema: {project_name, task_group}},
           init_override: {project_name, task_group}（可选）,
           dq_override: {project_name, task_group}（可选）}
    """
    if not config_path:
        config_path = str(schedule_config_path())
    p = Path(config_path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    # 过滤掉 _comment / _structure 等说明字段
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def resolve_schedule_path(sched_config: dict, schema: str, task_kind: str) -> dict:
    """按 schema + 任务类型解析调度任务路径（project_name/task_group）。

    task_kind: 'f' | 'view' | 'dq' | 'init'
    查找优先级：override 段（init_override / dq_override）→ schema_mappings → default

    返回 {project_name, task_group}（找不到都为空串，不报错）。
    """
    if not sched_config:
        return {"project_name": "", "task_group": ""}

    default_cfg = sched_config.get("default", {}) or {}
    schema_cfg = (sched_config.get("schema_mappings", {}) or {}).get(schema, {}) or {}

    # 任务类型 override：init → init_override；dq → dq_override；f/view 走 schema 默认
    override_cfg = {}
    if task_kind == "init":
        override_cfg = sched_config.get("init_override", {}) or {}
    elif task_kind == "dq":
        override_cfg = sched_config.get("dq_override", {}) or {}

    # 合并优先级：override > schema_mappings > default
    project_name = (override_cfg.get("project_name")
                    or schema_cfg.get("project_name")
                    or default_cfg.get("project_name", ""))
    task_group = (override_cfg.get("task_group")
                  or schema_cfg.get("task_group")
                  or default_cfg.get("task_group", ""))
    return {"project_name": project_name, "task_group": task_group}


def build_meta(rs_input, decisions):
    """组装 meta(从 rs_input 搬确定性数据)。"""
    rs_meta = rs_input.get("meta", {})
    target = rs_meta.get("target", {})

    # rs_input 的 target 已有 f_table 和 i_view（preprocess 从 _i 推导）
    f_table = target.get("f_table", {})
    i_view = target.get("i_view", {})

    # 兜底：如果 rs_input 还是旧格式（只有 schema/table/cn），推导一下
    if not f_table and target.get("table"):
        table_name = target["table"]
        if table_name.endswith("_i"):
            f_table = {"schema": target.get("schema", ""), "table": table_name[:-2] + "_f", "cn": target.get("cn", "")}
            i_view = {"schema": target.get("schema", ""), "table": table_name, "cn": target.get("cn", "")}
        else:
            f_table = {"schema": target.get("schema", ""), "table": table_name, "cn": target.get("cn", "")}
            i_view = {"schema": target.get("schema", ""), "table": table_name[:-2] + "_i" if table_name.endswith("_f") else table_name + "_i", "cn": target.get("cn", "")}

    # source_tables(从 rs_input 搬, 按表去重——同一张表多次关联只列一次)
    seen_tables = {}  # table -> {schema, table, table_cn, aliases}
    for st in rs_input.get("source_tables", []):
        t = st.get("source_table", "")
        a = st.get("source_alias", "")
        if not t:
            continue
        if t not in seen_tables:
            seen_tables[t] = {
                "schema": st.get("source_schema", ""),
                "table": t,
                "table_cn": st.get("source_table_cn", ""),
                "aliases": [],
            }
        if a and a not in seen_tables[t]["aliases"]:
            seen_tables[t]["aliases"].append(a)
    # 转成列表，别名合并成逗号分隔
    source_tables = []
    for st_info in seen_tables.values():
        st_info["alias"] = ", ".join(st_info.pop("aliases"))
        source_tables.append(st_info)

    # 调度: rs_input 给大框架 + designer 细化
    rs_sched = rs_input.get("schedule", {})
    dec_sched = decisions.get("schedule", {})

    # LTS 调度参数（designer 声明，默认含 V_CYCLE_ID→P_CYCLE_ID + V_GROUP_CODE）
    default_lts_params = [
        {"lts_var": "V_CYCLE_ID", "etl_param": "P_CYCLE_ID", "desc": "批次号"},
        {"lts_var": "V_GROUP_CODE", "etl_param": "", "desc": "规则组编码"},
    ]
    lts_params = dec_sched.get("lts_params", default_lts_params)

    # cron 和 schedule_type（designer 填）
    cron = dec_sched.get("cron", "")
    schedule_type = dec_sched.get("schedule_type", "daily")

    # 表名（用兜底后的 f_table/i_view，不用原始 target）
    f_table_short = f_table.get("table", "")
    i_view_short = i_view.get("table", "")
    target_schema = f_table.get("schema", "") or i_view.get("schema", "")

    # F 表 upstream：RS 湖表调度提供的（原样保留 project/group/app/env + task）+ designer 新增的
    f_upstream = []
    for u in rs_sched.get("upstream", []):
        # RS 的湖表调度表含 table/task/env/app/project/group，原样保留（跨项目依赖归属正确）
        item = {k: v for k, v in u.items() if v}
        item.setdefault("dep_type", "宽依赖")
        f_upstream.append(item)
    for u in dec_sched.get("upstream_added", []):
        # designer 新增的依赖：table/task/dep_type 必填，project/group/app 可选
        f_upstream.append({
            "table": u.get("table", ""),
            "task": u.get("task", ""),
            "dep_type": u.get("dep_type", "宽依赖"),
            "project": u.get("project", ""),
            "group": u.get("group", ""),
            "app": u.get("app", ""),
        })

    # 调度任务路径（project_name/task_group）：从 schedule_config 取默认值，designer 可覆盖。
    # 不同任务类型（F/view/dq/初始化）可能归属不同项目组，每个 task 单独确定。
    sched_config = load_schedule_config()
    # designer 的覆盖（task_project_override: {init: {...}, dq: {...}}）
    task_override = dec_sched.get("task_project_override", {}) or {}

    def _resolve_task_path(task_kind: str):
        """按任务类型解析 project_name/task_group。
        task_kind: 'f' | 'view' | 'dq' | 'init'
        优先级：designer 覆盖 > schedule_config 的 override > schema 默认 > default
        """
        # designer 显式覆盖最优先
        if task_kind in task_override and isinstance(task_override[task_kind], dict):
            ov = task_override[task_kind]
            if ov.get("project_name") or ov.get("task_group"):
                return {
                    "project_name": ov.get("project_name", ""),
                    "task_group": ov.get("task_group", ""),
                }
        # schedule_config 按 schema 取默认（含 override 段）
        return resolve_schedule_path(sched_config, target_schema, task_kind)

    # 标准化构建 tasks（F / view / dq）
    f_path = _resolve_task_path("f")
    tasks = {
        "f": {
            "task_name": f"task_{f_table_short}" if f_table_short else "",
            "job_name": f"Pjob_{f_table_short}" if f_table_short else "",
            "cron": cron,
            "upstream": f_upstream,
            "project_name": f_path["project_name"],
            "task_group": f_path["task_group"],
        }
    }
    if i_view_short:
        view_path = _resolve_task_path("view")
        tasks["view"] = {
            "task_name": f"task_{i_view_short}",
            "job_name": f"Pjob_{i_view_short}",
            "cron": cron,
            "upstream": [{"table": f_table_short, "task": f"task_{f_table_short}", "dep_type": "宽依赖"}],
            "project_name": view_path["project_name"],
            "task_group": view_path["task_group"],
        }
        # DQ 调度任务：仅当 dq_rules 非空时才建（DQ 完全跟随 RS，无 DQ 不产调度任务）
        if decisions.get("dq_rules"):
            dq_path = _resolve_task_path("dq")
            tasks["dq"] = {
                "task_name": f"task_{f_table_short}_dq",
                "job_name": f"Pjob_{f_table_short}_dq",
                "cron": cron,
                "upstream": [{"table": i_view_short, "task": f"task_{i_view_short}", "dep_type": "宽依赖"}],
                "project_name": dq_path["project_name"],
                "task_group": dq_path["task_group"],
            }

    # init 调度任务：仅当 init.group_mode == "separate" 时建（init 独立规则组 + 独立一次性任务）
    # group_mode == "inline" 不建独立任务（init 规则进 f 任务，靠 P_FLAG 运行条件选跑）
    init_dec = decisions.get("init") or {}
    if (isinstance(init_dec, dict)
            and (init_dec.get("group_mode") or "") == "separate"
            and f_table_short):
        init_path = _resolve_task_path("init")
        tasks["init"] = {
            "task_name": f"task_{f_table_short}_init",
            "job_name": f"Pjob_{f_table_short}_init",
            "cron": cron,
            "upstream": [],  # 一次性任务，操作员触发；源数据依赖隐式
            "project_name": init_path["project_name"],
            "task_group": init_path["task_group"],
        }

    schedule = {
        "schedule_type": schedule_type,
        "cron": cron,
        "exec_params": build_exec_params(decisions),
        "lts_params": lts_params,
        "tasks": tasks,
    }

    # 字段统计：识别审计字段（来源提供的），其余为业务字段
    all_fields = rs_input.get("field_mappings", [])
    source_audit = [fm for fm in all_fields if is_audit_field(fm)]
    source_audit_names = {(fm.get("target_column") or "").lower() for fm in source_audit}
    # 来源没提供的审计字段，需要补充
    supplemented = STANDARD_AUDIT_NAMES - source_audit_names
    business_count = len(all_fields) - len(source_audit)
    audit_count = len(source_audit) + len(supplemented)  # 来源的 + 补充的 = 总审计数

    load_strat = rs_meta.get("load_strategy", {})
    strategy = load_strat.get("strategy", "")
    return {
        "target": {
            "f_table": f_table,
            "i_view": i_view,
        },
        "grain": rs_meta.get("grain", ""),
        "load_strategy": {
            "strategy": strategy,
            "label": "",
            "delete_mode": "",
        },
        "field_count": {
            "business": business_count,
            "audit": audit_count,
            "total": business_count + audit_count,
        },
        "source_tables": source_tables,
        "schedule": schedule,
    }


def build_design(decisions, rs_input):
    """组装 design。audit_fields 智能处理：来源有用来源的，来源没的用标准模板补充。"""
    comp = decisions.get("complexity_analysis", {})

    # 审计字段智能处理
    all_fields = rs_input.get("field_mappings", [])
    source_audit = [fm for fm in all_fields if is_audit_field(fm)]
    source_audit_names = {(fm.get("target_column") or "").lower() for fm in source_audit}

    audit_fields = {}
    # 来源提供的审计字段：用来源的类型和默认值
    for fm in source_audit:
        name = (fm.get("target_column") or "").lower()
        audit_fields[name] = {
            "type": fm.get("target_type", ""),
            "default": (fm.get("transform_detail") or fm.get("mapping_expression") or "").strip(),
            "source": "mapping",  # 标记来自 mapping
        }
    # 来源没提供的审计字段：用标准模板补充
    for name, spec in STANDARD_AUDIT_TEMPLATE.items():
        if name not in source_audit_names:
            audit_fields[name] = {**spec, "source": "supplemented"}  # 标记自动补充

    supplemented = STANDARD_AUDIT_NAMES - source_audit_names

    return {
        "complexity_analysis": {
            "design_approach": comp.get("design_approach", ""),
            "segmentation_decision": comp.get("segmentation_decision", ""),
            "segmentation_reason": comp.get("segmentation_reason", ""),
            "data_volume": comp.get("data_volume", ""),
        },
        "audit_fields": audit_fields,
        "audit_supplemented": sorted(supplemented),
        "business_key": decisions.get("business_key", []),
        "business_key_design": decisions.get("business_key_design", {}),
        "exemptions": decisions.get("exemptions", []),
    }


def build_init_section(decisions: dict, rules: dict, target_f_table: str) -> dict:
    """组装 init 段（初始化管道，与增量管道 rules 平行）。

    幂等：不依赖校验通过，全程防御性取值（main 校验阶段也调 assemble_ts）。

    - 无 init 段（decisions.init 为空）→ 返回 None（ts.json 不含 init key）。
    - derive（模式一二）：克隆增量规则产 init.rules 元数据（filter→init_filter、终态 truncate、
      core_from 指向源规则、INIT_ 前缀）。init 是独立规则（与增量同结构），元数据设计阶段物化；
      SQL 由 coder 适配（读 core_from 源 .sql 改 filter），不在此产。
    - explicit（模式三）：按 7 不变量展开 designer 的 init.rules：
        终态(target) → target_table=增量F表 / load_mode=truncate_table / write_condition空 /
                       field_targets=增量终态全字段
        中间(intermediate) → load_mode=truncate_table（tmp 重建），其余 designer 声明
      field_logics 没写则从 core_from 抄（口径相同时省得重写）。
    """
    init_dec = decisions.get("init")
    if not init_dec or not isinstance(init_dec, dict):
        return None
    mode = (init_dec.get("mode") or "").strip()
    if not mode:
        return None
    group_mode = (init_dec.get("group_mode") or "").strip()
    section = {"mode": mode, "group_mode": group_mode, "rules": {}}

    if mode == "derive":
        # derive（模式一二，无 delta 机器）：克隆增量规则产 init.rules 元数据。
        # init 管道 = 增量管道同结构，只是 extract 的 WHERE 用 init_filter、终态 load_mode→truncate。
        # SQL 不在此产——由 coder 适配（slice_ts 带 core_from 的源 .sql + filter/init_filter，coder 改 filter）。
        def _init_code(c):
            return c if str(c).startswith("INIT_") else f"INIT_{c}"
        for code, r in rules.items():
            if r.get("is_view_step"):
                continue  # 视图步骤不属于数据管道
            inc = r.get("incremental") or {}
            cloned = {
                "rule_name": (r.get("rule_name") or code) + "(初始化)",
                "exec_sequence": r.get("exec_sequence", 1),
                "target_table": r.get("target_table", ""),
                "target_role": r.get("target_role", "target"),
                "step_type": r.get("step_type", "full"),
                "is_view_step": False,
                # init 全是先删全插（中间 tmp 重建 / 终态全量装载）
                "load_mode": "truncate_table",
                "write_condition": "",
                "produces_for": [_init_code(c) for c in (r.get("produces_for") or [])],
                "reads": list(r.get("reads") or []),  # tmp 表名复用，不加前缀
                "joins": list(r.get("joins") or []),
                "field_targets": list(r.get("field_targets") or []),
                "field_logics": dict(r.get("field_logics") or {}),
                "core_from": code,  # 指向源增量规则，coder 适配时读它的 .sql
                "design_intent": f"derive 派生：克隆自 {code}，SQL 由 coder 适配（filter→init_filter）",
            }
            # 保留 incremental 段（含 filter + init_filter），slice_ts 据此告诉 coder 改哪个 filter
            if isinstance(inc, dict) and inc:
                cloned["incremental"] = inc
            section["rules"][_init_code(code)] = cloned
        return section

    # mode == "explicit"：按 7 不变量展开 designer 的 init.rules

    # 找增量终态（首个 target_role=target 规则）取 target_table + field_targets（不变量1/4）
    # 用增量终态规则的 target_table（带 schema，与 rules 完全一致），而非 meta.f_table（可能是短名）
    inc_terminal = None
    for r in rules.values():
        if r.get("target_role") == "target":
            inc_terminal = r
            break
    inc_terminal_targets = list((inc_terminal or {}).get("field_targets") or [])
    inc_terminal_table = (inc_terminal or {}).get("target_table") or target_f_table

    for r in (init_dec.get("rules") or []):
        code = r.get("rule_code") or ""
        target_role = r.get("target_role") or "target"
        core_from = r.get("core_from") or ""
        # field_logics：designer 没写 + 有 core_from → 从 core_from 抄
        field_logics = r.get("field_logics")
        if field_logics is None and core_from and core_from in rules:
            field_logics = rules[core_from].get("field_logics") or {}
        if field_logics is None:
            field_logics = {}

        if target_role == "target":
            # 终态：7 不变量补全
            built = {
                "rule_name": r.get("rule_name") or f"初始化-{code}",
                "exec_sequence": r.get("exec_sequence", 1),
                "target_table": inc_terminal_table or r.get("target_table", ""),
                "target_role": "target",
                "step_type": r.get("step_type") or "full",
                "load_mode": "truncate_table",
                "write_condition": "",
                "joins": r.get("joins") or [],
                "field_targets": list(inc_terminal_targets) if inc_terminal_targets else list(r.get("field_targets") or []),
                "field_logics": field_logics,
                "core_from": core_from,
                "design_intent": r.get("design_intent") or "初始化（全量），装配器按不变量补全",
            }
        else:
            # 中间 tmp 规则：designer 声明 target_table/reads/field_targets，load_mode 强制 truncate_table
            # （init tmp 全量重建也是先删全插；复用增量 tmp，不新建）
            built = {
                "rule_name": r.get("rule_name") or f"初始化-{code}",
                "exec_sequence": r.get("exec_sequence", 1),
                "target_table": r.get("target_table", ""),
                "target_role": target_role,
                "step_type": r.get("step_type") or "full",
                "load_mode": "truncate_table",
                "write_condition": "",
                "reads": r.get("reads") or [],
                "produces_for": r.get("produces_for") or [],
                "joins": r.get("joins") or [],
                "field_targets": list(r.get("field_targets") or []),
                "field_logics": field_logics,
                "core_from": core_from,
                "design_intent": r.get("design_intent") or "初始化中间加工（全量）",
            }
        section["rules"][code] = built
    return section


def assemble_ts(rs_input, decisions):
    """组装完整 ts.json dict。"""
    # 建 field_map: target_column -> field_mapping 记录
    field_map = {}
    for fm in rs_input.get("field_mappings", []):
        tc = fm.get("target_column", "")
        if tc:
            field_map[tc] = fm

    meta = build_meta(rs_input, decisions)
    design = build_design(decisions, rs_input)

    rules = {}
    all_missing_logic = []
    for rule_dec in decisions.get("rules", []):
        code = rule_dec.get("rule_code", "")
        rule_obj, missing_logic = build_rule(
            rule_dec, field_map, rs_input.get("source_tables", []),
            target_schema=meta.get("target", {}).get("f_table", {}).get("schema", ""))
        rules[code] = rule_obj
        if missing_logic:
            all_missing_logic.append((code, missing_logic))

    # 组装 tables 段（表实体：字段定义 + 物理属性）
    f_table_full = meta.get("target", {}).get("f_table", {}).get("table", "")
    tables = build_tables(rules, decisions, field_map, rs_input, f_table_full)

    # 组装 init 段（初始化管道，与 rules 平行；无 init 段返回 None → 不含 init key）
    init_section = build_init_section(decisions, rules, f_table_full)

    ts = {
        "version": "1.0.0",
        "spec_type": "ts",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generated_by": "assemble_ts.py",
        "meta": meta,
        "design": design,
        "tables": tables,
        "rules": rules,
        "data_flow": decisions.get("data_flow", {}),
        "dq_rules": decisions.get("dq_rules", []),
    }
    if init_section is not None:
        ts["init"] = init_section
    return ts, all_missing_logic, field_map


# ============================================================
# 渲染 ts.md(从 ts.json 投影, 7章)
# ============================================================
def render_md(ts):
    """从 ts.json 渲染 ts.md(人读投影)。"""
    meta = ts["meta"]
    target = meta["target"]
    rules = ts["rules"]
    design = ts["design"]
    tables = ts.get("tables", {})

    lines = []
    lines.append(f"# ETL 技术规格(TS)")
    lines.append("")
    lines.append(f"> 目标表: `{target['f_table']['schema']}.{target['f_table']['table']}`"
                 f"({target['f_table']['cn']}) - 生成 {ts['generated_at']}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # §1 概述
    lines.append("## 1. 概述")
    lines.append("")
    lines.append("| 项目 | 内容 |")
    lines.append("|------|------|")
    lines.append(f"| **F 表** | `{target['f_table']['schema']}.{target['f_table']['table']}`（{target['f_table']['cn']}） |")
    i_view = target.get("i_view", {})
    if i_view and i_view.get("table"):
        lines.append(f"| **I 视图** | `{i_view.get('schema', '')}.{i_view.get('table', '')}`（F表镜像，对外查询） |")
    # 业务主键（替代原"目标粒度"——主键即粒度定义）
    bk = design.get("business_key", [])
    lines.append(f"| **业务主键** | {', '.join(bk) if bk else '-'} |")
    # 写入策略：全量可重刷 / 增量（详见规则详情）
    all_truncate = all(r.get("load_mode") == "truncate_table" for r in rules.values())
    load_label = "全量（可随时重刷）" if all_truncate else "增量（详见规则详情）"
    lines.append(f"| **写入策略** | {load_label} |")
    fc = meta["field_count"]
    lines.append(f"| **字段统计** | {fc['total']} |")
    # 规则数（含直封视图提示）
    has_view = any(r.get("is_view_step") for r in rules.values())
    rule_label = f"{len(rules)}"
    if has_view:
        rule_label += "（含直封视图）"
    lines.append(f"| **规则数** | {rule_label} |")
    lines.append("")
    lines.append("**来源表**:")
    lines.append("")
    lines.append("| # | 表名 | 中文名 | 别名 |")
    lines.append("|---|------|--------|------|")
    for i, st in enumerate(meta["source_tables"], 1):
        lines.append(f"| {i} | {st['schema']}.{st['table']} | {st['table_cn']} | {st['alias']} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # §2 表模型设计（统一表格，目标表优先）
    lines.append("## 2. 表模型设计")
    lines.append("")
    f_table_short = target["f_table"]["table"]
    i_view_short = target["i_view"].get("table", "")

    def _short_desc(text: str, limit: int = 30) -> str:
        """截短说明：取第一个逗号/句号前的内容，或限制长度。"""
        if not text:
            return ""
        for sep in ["，", "。", ",", "."]:
            if sep in text:
                text = text.split(sep)[0]
                break
        return text[:limit] + "…" if len(text) > limit else text

    def _dist_label(t):
        """分布类型+分布键合并显示，如 HASH(product_id) / ROUNDROBIN / REPLICATION"""
        dtype = t.get("distribute_type", "HASH")
        dkeys = t.get("distribution_key", [])
        if dtype == "HASH" and dkeys:
            return f"HASH({', '.join(dkeys)})"
        elif dtype == "REPLICATION":
            return "REPLICATION"
        else:
            return dtype or "—"

    # 排序：目标F表 → 中间表 → 视图
    lines.append("| 表名 | 类型 | 分布 | 分区 | 字段数 | 说明 |")
    lines.append("|------|------|------|------|--------|------|")
    # 目标 F 表
    if f_table_short in tables:
        t = tables[f_table_short]
        part = t.get("partition") or "—"
        fcount = len(t.get("fields", []))
        lines.append(f"| `{f_table_short}` | 目标F表 | {_dist_label(t)} | {part} | {fcount} | {target['f_table'].get('cn', '')} |")
    # 中间表
    for tname, t in tables.items():
        if t.get("type") == "intermediate":
            part = t.get("partition") or "—"
            fcount = len(t.get("fields", []))
            # 找对应规则的 design_intent，截短成简述
            intent = ""
            for r in rules.values():
                rt = r.get("target_table", "")
                if rt.rsplit(".", 1)[-1] == tname or rt == tname:
                    intent = _short_desc(r.get("design_intent", ""))
                    break
            lines.append(f"| `{tname}` | 中间表 | {_dist_label(t)} | {part} | {fcount} | {intent} |")
    # 视图（无物理属性）
    if i_view_short:
        f_fields = len(tables.get(f_table_short, {}).get("fields", []))
        lines.append(f"| `{i_view_short}` | 直封视图 | — | — | 同F表 | F表镜像，对外查询 |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # §3 设计思路（designer 写的自然语言，含设计考虑的指标 + 整体策略）
    lines.append("## 3. 设计思路")
    lines.append("")
    comp = design.get("complexity_analysis", {})
    # design_approach 是 designer 写的设计思路（自然语言，自然引用了 JOIN 数/聚合字段等指标）
    approach = comp.get("design_approach", "") or comp.get("segmentation_reason", "")
    if approach:
        lines.append(f"> {approach}")
        lines.append("")
    seg = comp.get("segmentation_decision", "")
    if seg:
        lines.append(f"**分段结论**: **{seg}**")
        lines.append("")
    lines.append("---")
    lines.append("")

    # §4 规则详情
    lines.append("## 4. 规则详情")
    lines.append("")
    for code, r in rules.items():
        lines.append(f"### {code} - {r['rule_name']}")
        lines.append("")
        lines.append("| 项目 | 内容 |")
        lines.append("|------|------|")
        # 场景：默认(default)不展示，非默认才显示
        scenario = r.get("scenario", "")
        if scenario and scenario != "default":
            lines.append(f"| 场景 | {scenario} |")
        lines.append(f"| 执行序 | {r['exec_sequence']} |")
        lines.append(f"| 产出表 | `{r['target_table']}` |")
        # 步骤类型/目标角色：非默认值才展示（默认 full/target 不显示，减少噪音）
        step_type = r.get("step_type", "full")
        target_role = r.get("target_role", "target")
        if step_type != "full" or target_role != "target":
            lines.append(f"| 步骤类型 | {step_type}（{target_role}） |")
        lines.append(f"| 写入方式 | {r.get('load_mode', '-')} |")
        if r.get("design_intent"):
            lines.append(f"| 设计意图 | {r['design_intent']} |")
        lines.append(f"| 字段数 | {len(r.get('field_targets', []))} |")
        lines.append("")

        # 关联安全：只有有风险的（join_key_unique=false）才展示
        risky_joins = [js for js in r.get("join_safety", []) if not js.get("join_key_unique")]
        if risky_joins:
            lines.append("**关联风险**:")
            lines.append("")
            for js in risky_joins:
                tbl = js.get("table", "")
                strategy = js.get("strategy", "")
                lines.append(f"- `{tbl}`: {strategy}")
            lines.append("")

        # 重要字段逻辑：只写有口径的、非审计字段
        logics = r.get("field_logics", {})
        if logics:
            lines.append("**字段逻辑**:")
            lines.append("")
            for name, logic in logics.items():
                lines.append(f"- `{name}`: {logic}")
            lines.append("")
        lines.append("---")
        lines.append("")

    # §5 数据流向（只留数据流图，血缘/执行顺序已被图覆盖）
    lines.append("## 5. 数据流向")
    lines.append("")
    mermaid_graph = render_data_flow_mermaid(ts)
    if mermaid_graph:
        lines.append(mermaid_graph)
        lines.append("")
    lines.append("---")
    lines.append("")

    # §6 调度配置（F表 / I视图 / DQ 三任务）
    lines.append("## 6. 调度配置")
    lines.append("")
    sched = meta.get("schedule", {})
    tasks_sched = sched.get("tasks", {})
    lts_params = sched.get("lts_params", [])

    def _render_task_section(title, task_info):
        """渲染单个调度任务段（F表/I视图/DQ 通用）"""
        if not task_info or not task_info.get("task_name"):
            return
        lines.append(f"### {title}")
        lines.append("")
        lines.append("| 配置项 | 值 |")
        lines.append("|--------|-----|")
        lines.append(f"| 调度任务 | {task_info.get('task_name', '-')} |")
        lines.append(f"| 执行Job | {task_info.get('job_name', '-')} |")
        # 调度任务路径（项目/任务组，来自 schedule_config，designer 可覆盖）
        project = task_info.get("project_name", "")
        group = task_info.get("task_group", "")
        if project or group:
            lines.append(f"| 项目 / 任务组 | {project} / {group} |")
        lines.append(f"| 调度周期 | {task_info.get('cron', '-') or '-'} |")
        lines.append("")
        upstream = task_info.get("upstream", [])
        if upstream:
            lines.append("**上游依赖**:")
            lines.append("")
            # 上游依赖加 项目/任务组 列（跨项目依赖归属可见）
            lines.append("| 源表 | 项目 / 任务组 | 调度任务 | 依赖类型 |")
            lines.append("|------|---------------|---------|---------|")
            for u in upstream:
                u_proj = u.get("project", "")
                u_grp = u.get("group", "")
                pg = f"{u_proj} / {u_grp}" if (u_proj or u_grp) else "-"
                lines.append(f"| {u.get('table', '')} | {pg} | {u.get('task', '') or '-'} | {u.get('dep_type', '宽依赖')} |")
            lines.append("")

    # LTS 参数（全局，只在 F 表段前展示一次）
    if lts_params:
        lines.append("**LTS 参数**:")
        lines.append("")
        lines.append("| LTS 变量 | 赋值给 ETL 参数 | 说明 |")
        lines.append("|----------|----------------|------|")
        for p in lts_params:
            etl = p.get("etl_param", "") or "—"
            lines.append(f"| {p.get('lts_var', '')} | {etl} | {p.get('desc', '')} |")
        lines.append("")

    _render_task_section("F 表调度", tasks_sched.get("f", {}))
    _render_task_section("I 视图调度", tasks_sched.get("view", {}))
    _render_task_section("DQ 调度", tasks_sched.get("dq", {}))

    lines.append("---")
    lines.append("")

    # §7 DQ（RS 驱动：RS L06 有需求 designer 翻译产，没有则不产）
    lines.append("## 7. 数据质量检查(DQ)")
    lines.append("")
    dq = ts.get("dq_rules", [])
    if dq:
        lines.append(f"> DQ 由 RS L06 驱动，designer 翻译成技术口径，coder 按 dq_rules 产出（共 {len(dq)} 条）。")
        lines.append("")
        lines.append("| 检查范围 | 检查类型 | 规则名称 | 规则描述（技术口径） |")
        lines.append("|----------|----------|----------|----------|")
        for d in dq:
            lines.append(f"| {d.get('scope', '')} | {d.get('check_type', '')} | {d.get('rule_name', '')} | {d.get('rule_desc', '')} |")
    else:
        lines.append("*(RS 未提 DQ 需求，本资产不产 DQ：coder 不产 DQ SQL，无 DQ 调度任务)*")
    lines.append("")

    # §8 增量设计（条件出现：只有有增量规则的资产才显示）
    # 不再按 load_mode 过滤——否则增量目标若误设 truncate_table 反而被藏起来，
    # 闸口①看不见矛盾。N_INIT2 会拦这种配置，这里让它可见。
    incremental_rules = {
        code: r for code, r in rules.items()
        if r.get("incremental")
    }
    if incremental_rules:
        lines.append("---")
        lines.append("")
        lines.append("## 8. 增量设计")
        lines.append("")
        lines.append("> 本资产含增量规则，以下规则采用增量写入策略。")
        lines.append("")
        for code, r in incremental_rules.items():
            inc = r.get("incremental", {})
            lines.append(f"### {code} - {r.get('rule_name', '')}")
            lines.append("")
            lines.append("| 项目 | 内容 |")
            lines.append("|------|------|")
            lines.append(f"| 写入方式 | {r.get('load_mode', '-')} |")
            if inc.get("key"):
                lines.append(f"| 增量字段 | `{inc['key']}` |")
            if inc.get("filter"):
                lines.append(f"| 增量条件 | `{inc['filter']}` |")
            if inc.get("init_filter"):
                lines.append(f"| 初始化条件 | `{inc['init_filter']}` |")
            if inc.get("init_time_range"):
                lines.append(f"| 初始化时间范围 | {inc['init_time_range']} |")
            if inc.get("init_strategy"):
                lines.append(f"| 初始化策略 | {inc['init_strategy']} |")
            if inc.get("init_mode"):
                lines.append(f"| 初始化方式 | **{inc['init_mode']}** |")
            lines.append("")

    # 初始化设计（条件出现：ts.json 含 init 段时）
    # init 和增量是同一目标表的两个写入管道：增量日常跑，init 首次全量装载（先删全插）。
    init_section = ts.get("init")
    if init_section and init_section.get("mode"):
        lines.append("---")
        lines.append("")
        lines.append("## 初始化设计（init 管道）")
        lines.append("")
        i_mode = init_section.get("mode", "")
        i_group = init_section.get("group_mode", "")
        lines.append(f"- **模式**: `{i_mode}`（{'显式独立设计（模式三：增量有 delta 机器）' if i_mode == 'explicit' else '从增量管道派生（模式一二：增量只多范围 WHERE）'}）")
        lines.append(f"- **组织**: `{i_group}`（{'同规则组 p_flag 选跑' if i_group == 'inline' else '独立规则组独立调度'}）")
        lines.append("")
        if i_mode == "derive":
            lines.append("> init 从增量管道派生：各 extract 的 WHERE 换成 incremental.init_filter，终态 load_mode 换成 truncate_table。下游物化时生成 init 执行行。")
            listed = False
            for code, r in incremental_rules.items():
                inc = r.get("incremental", {})
                if inc.get("init_filter"):
                    lines.append(f"  - {code}: init_filter = `{inc['init_filter']}`")
                    listed = True
            if not listed:
                lines.append("  *(无 extract 规则带 init_filter)*")
            lines.append("")
        elif i_mode == "explicit":
            init_rules = init_section.get("rules") or {}
            if init_rules:
                lines.append("> init 规则由装配器按不变量补全（终态 load_mode=truncate_table / write_condition 空 / field_targets=目标全字段 / tmp 复用）。designer 只声明 core_from + joins（核心结构，剥掉 delta 机器）。")
                lines.append("")
                for code, r in init_rules.items():
                    lines.append(f"### {code} - {r.get('rule_name', '')}")
                    lines.append("")
                    lines.append("| 项目 | 内容 |")
                    lines.append("|------|------|")
                    lines.append(f"| 目标表 | {r.get('target_table', '-')} |")
                    lines.append(f"| 角色 | {r.get('target_role', '-')} |")
                    lines.append(f"| 写入方式 | {r.get('load_mode', '-')} |")
                    if r.get("core_from"):
                        lines.append(f"| 口径抄自 | `{r.get('core_from')}` |")
                    joins = r.get("joins") or []
                    if joins:
                        jsum = "; ".join(f"{j.get('alias', '')}({j.get('type', '')})" for j in joins)
                        lines.append(f"| 核心结构 | {jsum} |")
                    lines.append("")
            else:
                lines.append("*(explicit 模式但无 init 规则)*")
                lines.append("")

    # §9 分区设计（条件出现：只有有分区的表才显示）
    partition_tables = {
        tname: t for tname, t in tables.items()
        if t.get("partition")
    }
    if partition_tables:
        lines.append("---")
        lines.append("")
        lines.append("## 9. 分区设计")
        lines.append("")
        lines.append("| 表名 | 分区表达式 |")
        lines.append("|------|-----------|")
        for tname, t in partition_tables.items():
            lines.append(f"| `{tname}` | `{t['partition']}` |")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="TS 制品组装器: rs_input.json + design_decisions.yaml -> ts.json + ts.md"
    )
    parser.add_argument("--rs", required=True, help="rs_input.json 路径")
    parser.add_argument("--decisions", required=True, help="design_decisions.yaml 路径")
    parser.add_argument("--outdir", required=True, help="输出目录(ts.json + ts.md 写到这里)")
    args = parser.parse_args()

    # 1. 读 rs_input.json
    rs_path = Path(args.rs)
    if not rs_path.exists():
        print(f"错误: rs_input.json 不存在: {rs_path}", file=sys.stderr)
        sys.exit(2)
    try:
        rs_input = json.loads(rs_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"错误: rs_input.json 解析失败: {e}", file=sys.stderr)
        sys.exit(2)

    # 2. 读 design_decisions.yaml
    dec_path = Path(args.decisions)
    if not dec_path.exists():
        print(f"错误: design_decisions.yaml 不存在: {dec_path}", file=sys.stderr)
        sys.exit(2)
    try:
        decisions = yaml.safe_load(dec_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        print(f"错误: design_decisions.yaml 解析失败: {e}", file=sys.stderr)
        sys.exit(2)

    if not isinstance(decisions, dict):
        print("错误: design_decisions.yaml 顶层应为字典(mapping)", file=sys.stderr)
        sys.exit(2)

    # 3. 建 field_map 并校验
    field_map = {}
    for fm in rs_input.get("field_mappings", []):
        tc = fm.get("target_column", "")
        if tc:
            field_map[tc] = fm

    print(f"rs_input: {len(field_map)} 个目标字段, {len(rs_input.get('source_tables', []))} 个源表")
    print(f"design_decisions: {len(decisions.get('rules', []))} 个规则")

    # ★ target_table _i→_f 兜底转换：ts 设计针对 F 表，designer 填了 _i 自动转 _f
    _i_converted_rules = []
    for rule in decisions.get("rules", []):
        tbl = rule.get("target_table", "")
        if tbl and (tbl.endswith("_i") or (".") in tbl and tbl.rsplit(".", 1)[-1].endswith("_i")):
            # 短名以 _i 结尾 → 转 _f
            schema_part = tbl.rsplit(".", 1)[0] + "." if "." in tbl else ""
            short = tbl.rsplit(".", 1)[-1]
            new_tbl = schema_part + short[:-2] + "_f"
            rule["target_table"] = new_tbl
            _i_converted_rules.append(f"{rule.get('rule_code','?')}: {tbl} → {new_tbl}")
    if _i_converted_rules:
        print(f"[warn] target_table 填的是 _i，已自动转 _f（ts 设计针对 F 表）:")
        for r in _i_converted_rules:
            print(f"  {r}")

    # 3a. 五层校验（含存量 C7-C13 + 新增 N1-N30）
    # N30 需要 schema_cache（rs_input 同级的 _internal 缓存，precheck 连库产出）
    _cache_path = Path(args.rs).resolve().parent / "schema_cache.json"
    vr = run_all_validations(decisions, rs_input, field_map, schema_cache_path=_cache_path)
    exemptions = decisions.get("exemptions") or []

    # N5（W1 升级）：加工字段缺 design_logic 现在是硬阻断
    # 先组装拿到 missing_logic（不落盘），再注入校验结果
    # 注意：assemble_ts 内部会 build_rule 收集 missing_logic，这里先跑一次拿结果
    ts, missing_logic, _ = assemble_ts(rs_input, decisions)
    for code, fields in missing_logic:
        vr.add_hard("L1", "N5",
                    f"规则 {code} 的加工字段未写 design_logic: {fields}。"
                    f"修正：在该规则的 field_logics 里给每个字段写自然语言口径，"
                    f"如 '{fields[0] if fields else '字段名'}: 本币金额=原币×汇率'。" +
                    (f"（若该规则是装配/merge 步骤、字段从临时表搬运，请在 reads 里声明读取的临时表，"
                      f"装配规则字段默认直取不要求写 logic）" if not any(r.get("reads") for r in decisions.get("rules", []) if r.get("rule_code") == code) else ""))

    # 输出校验报告（按层分组）
    report = vr.format_report(exemptions)
    hard_errors = vr.hard_errors(exemptions)
    if hard_errors:
        print("\n" + report, file=sys.stderr)
        print("\n请修正 design_decisions.yaml 后重跑（看 [第X层] 标识定位到对应 playbook）。", file=sys.stderr)
        sys.exit(1)
    # 软阻断/警告不阻断，但打印提示
    if report:
        print("\n" + report)

    # 5. 写出
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 从 ts.json 取资产名（f_table 表名）用于 md 文件命名
    asset_name = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("table", "ts")
    ts_json_path = outdir / "ts.json"
    ts_json_path.write_text(json.dumps(ts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n产出 ts.json: {ts_json_path}")

    ts_md_path = outdir / f"{asset_name}_ts.md"
    ts_md_path.write_text(render_md(ts), encoding="utf-8")
    print(f"产出 {asset_name}_ts.md: {ts_md_path}")

    # 6. 摘要
    rules = ts["rules"]
    scenarios = set(r["scenario"] for r in rules.values() if r["scenario"])
    print(f"\n[完成] {len(rules)} 个规则, {len(scenarios)} 个场景, "
          f"{ts['meta']['field_count']['total']} 个字段(含审计)")


if __name__ == "__main__":
    main()
