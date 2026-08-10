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

# 标准审计字段模板（4个固定字段，用于补充缺失的审计字段）
STANDARD_AUDIT_TEMPLATE = {
    "del_flag":            {"type": "nvarchar(1)",                    "default": "'N'"},
    "crt_cycle_id":        {"type": "bigint",                         "default": "'${P_CYCLE_ID}'"},
    "last_upd_cycle_id":   {"type": "bigint",                         "default": "'${P_CYCLE_ID}'"},
    "dw_last_update_date": {"type": "timestamp(0) without time zone", "default": "CURRENT_TIMESTAMP"},
}
STANDARD_AUDIT_NAMES = set(STANDARD_AUDIT_TEMPLATE.keys())

# 标准参数（所有资产默认都有，脚本自动注入，designer 无需声明）
# 现仅批次号；如未来加标准参数，在此列表追加即可。
STANDARD_PARAMS = [
    {"name": "P_CYCLE_ID", "value_type": "string", "desc": "批次号"},
]


def build_exec_params(decisions):
    """组装 exec_params：标准参数自动注入 + 业务参数透传。

    返回 {param_name: {value_type, desc, standard}}。
    standard=true 表示脚本自动注入（所有资产都有）。
    """
    params = {}
    for sp in STANDARD_PARAMS:
        params[sp["name"]] = {
            "value_type": sp["value_type"],
            "desc": sp["desc"],
            "standard": True,
        }
    for p in decisions.get("params", []):
        params[p["name"]] = {
            "value_type": p.get("value_type", "string"),
            "desc": p.get("desc", ""),
            "standard": False,
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


def run_all_validations(decisions: dict, rs_input: dict, field_map: dict) -> ValidationResult:
    """运行五层校验全集。返回 ValidationResult。

    存量校验（C7-C13）通过 validate_decisions 调用，结果并入 L1/L4。
    新增校验按层独立函数。
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
        for r in rule.get("reads") or []:
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
        for r in rule.get("reads") or []:
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
        # N14（松绑后语义）：资产标了增量但"完全没管增量"才硬阻断。
        # "完全没管" = 没有 extract 规则 + 没有任何规则的 incremental 段非空 + 没有规则的 source 涉及驱动表。
        # 至于用几个规则、extract 数和驱动表数关系——是 designer 的设计自由（见 incremental-playbook 三种模式）。
        has_extract = n_extracts > 0
        has_incremental_section = any(
            (r.get("incremental") or {}) and
            any((r.get("incremental", {}) or {}).get(f) for f in ("key", "filter"))
            for r in rules
        )
        # 规则的 source_aliases 涉及任一驱动表
        driver_table_shorts = {_table_short((dt.get("source_table") or "")).lower() for dt in incremental_tables}
        rs_source_shorts = {
            (st.get("source_table") or "").split(".")[-1].lower()
            for st in (rs_input.get("source_tables") or [])
        }
        rules_touch_driver = False
        for r in rules:
            r_aliases = r.get("source_aliases") or []
            # 别名映射到表名（从 rs_input source_tables 找），看是否涉及驱动表
            for st in (rs_input.get("source_tables") or []):
                if (st.get("source_alias") or "") in (r_aliases or []):
                    if (st.get("source_table") or "").split(".")[-1].lower() in driver_table_shorts:
                        rules_touch_driver = True
            # source_aliases 留空 = 用全部源表（build_rule 兜底逻辑），涉及驱动表即算
            if not r_aliases and driver_table_shorts & rs_source_shorts:
                rules_touch_driver = True
        if not has_extract and not has_incremental_section and not rules_touch_driver:
            vr.add_hard("L3", "N14", f"资产标了增量（{n_drivers} 张驱动表）但完全没增量处理（无 extract 规则、无 incremental 段、规则 source 不涉驱动表）——增量变化完全没被覆盖")

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
                vr.add_hard("L4", "N21", f"表 '{tbl_short}' 的 distribution_key 字段 '{dk}' 不在该表字段中（建表会报错）")

    # ============================================================
    # 横切（N22-N25）
    # ============================================================
    # N22 增量 filter/init_filter 里 ${PARAM} 引用的参数都在 params 声明过
    declared_params = {p.get("name", "").upper() for p in (decisions.get("params") or []) if isinstance(p, dict)}
    # P_CYCLE_ID 由脚本自动注入，不算未声明
    declared_params.add("P_CYCLE_ID")
    import re as _re2
    for rule in extract_rules:
        code = rule.get("rule_code", "?")
        inc = rule.get("incremental") or {}
        for f in ("filter", "init_filter"):
            val = inc.get(f) or ""
            for m in _re2.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", val):
                if m.upper() not in declared_params:
                    vr.add_hard("LC", "N22", f"规则 {code} 的 incremental.{f} 引用参数 '${{{m}}}' 未在 params 声明（P_CYCLE_ID 自动注入除外）")

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

    return vr


# ============================================================
# 组装 ts.json
# ============================================================
def build_field(field_rec, logic, rule_aliases, is_assembly=False, reads_tables=None):
    """从 rs_input 的 field_mapping 记录 + design_logic 组装 ts 的 field 对象。

    field_rec: rs_input.field_mappings 的一条记录
    logic: design_decisions 里该字段的 design_logic(可能为 None -> 用默认)
    rule_aliases: 该规则关联的源表别名集合(用于决定 source_fields)
    is_assembly: 是否装配/merge 规则（reads 非空）。装配规则字段默认直取（从临时表搬）。
    reads_tables: 装配规则读取的临时表名列表（用于生成"直取 tmp.xxx"的默认 logic）
    """
    transform_rule = field_rec.get("transform_rule", "直接复制")
    transform_type = TRANSFORM_MAP.get(transform_rule, "direct")

    alias = field_rec.get("source_alias", "")
    source_column = field_rec.get("source_column", "")
    source_table = field_rec.get("source_table", "")
    target_column = field_rec.get("target_column", "")

    # design_logic + transform_type：根据规则角色 + designer 是否写了 logic 共同决定
    # 装配/merge 规则：designer 没写 logic 的字段 = 从临时表搬运（直取），transform_type 改 direct
    #                 designer 写了 logic 的字段 = 二次加工，transform_type 保持原值
    if logic:
        design_logic = logic
        # designer 显式写了口径 → 按原 transform_type（加工）走，不改
    elif transform_type == "direct":
        design_logic = f"直取 {alias}.{source_column}" if alias else f"直取 {source_table}.{source_column}"
    elif transform_type == "assign":
        design_logic = "固定赋值"
    elif is_assembly:
        # 装配/merge 规则的加工字段没写 logic → 默认从临时表直取（前面步骤已加工）
        # transform_type 也改成 direct（跟 design_logic 的"直取"一致，避免 coder 看到矛盾）
        transform_type = "direct"
        src_tbl = reads_tables[0] if reads_tables else "临时表"
        design_logic = f"直取 {src_tbl}.{target_column}（前序步骤已加工，本步搬运）"
    else:
        # 加工类字段没写 logic 是个问题, 但先给个占位, 校验层会警告
        design_logic = f"[需补充] 加工逻辑未写, transform_detail: {field_rec.get('transform_detail', '')}"

    return {
        "target_field": field_rec.get("target_column", ""),
        "field_type": field_rec.get("target_type", ""),
        "field_comment": field_rec.get("target_column_cn", ""),
        "transform_type": transform_type,
        "source_fields": [
            {
                "table": source_table,
                "field": source_column,
                "alias": alias,
            }
        ],
        "design_logic": design_logic,
    }


def build_rule(rule_dec, field_map, rs_source_tables):
    """组装一个规则对象。字段定义不在此产出（由 build_tables 按表汇总）。"""
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

    # ★ 装配/merge 规则（reads 非空）：把 reads 的临时表也加进 source_tables
    # 临时表不在 rs_input 的 source_tables 里（它是前序步骤产出的），但要作为伪源表声明，
    # 否则下游 coder/slice_ts 拿不到该规则读的临时表信息。
    reads = rule_dec.get("reads") or []
    existing_tables = {src["table"].split(".")[-1].lower() for src in rule_sources if src.get("table")}
    for r in reads:
        r_short = _table_short(r) if "." in str(r) else str(r)
        if r_short and r_short.split(".")[-1].lower() not in existing_tables:
            rule_sources.append({
                "schema": "",           # 临时表无 schema（或同 schema，coder 推断）
                "table": r_short,
                "alias": "",            # 临时表别名 coder 按表名推
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
        "reads": rule_dec.get("reads", []) or [],  # 装配/merge规则填：读哪些中间表
        "incremental": rule_dec.get("incremental", {}),  # 增量设计（key/filter/init_time_range/init_strategy）
        "source_tables": rule_sources,
        "ctes": rule_dec.get("ctes", []),
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

        # 跳过已处理的表（多 rule 写同表，只建一次字段集）
        if tbl_short in tables:
            continue

        # 判断表类型
        is_final = (tbl_short == final_table_short)
        tbl_type = "target" if is_final else "intermediate"

        # 字段定义：从 field_map 按 field_targets 组装（design_logic 取规则 field_logics）
        rule_logics = rule.get("field_logics", {})
        rule_reads = rule.get("reads") or []
        # reads 的表短名（用于装配规则字段的"直取 tmp.xxx"默认 logic）
        reads_short = [_table_short(r) if ("." in str(r)) else r for r in rule_reads]
        is_asm = bool(rule_reads)  # 装配/merge 规则
        fields = []
        for tname in rule.get("field_targets", []):
            rec = field_map.get(tname)
            if not rec:
                continue
            f = build_field(rec, rule_logics.get(tname), rule.get("source_aliases"),
                            is_assembly=is_asm, reads_tables=reads_short)
            fields.append(f)

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
        config_path = str(Path.home() / ".config" / "opencode" / "schedule_config.json")
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
        dq_path = _resolve_task_path("dq")
        tasks["dq"] = {
            "task_name": f"task_{f_table_short}_dq",
            "job_name": f"Pjob_{f_table_short}_dq",
            "cron": cron,
            "upstream": [{"table": i_view_short, "task": f"task_{i_view_short}", "dep_type": "宽依赖"}],
            "project_name": dq_path["project_name"],
            "task_group": dq_path["task_group"],
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
        rule_obj, missing_logic = build_rule(rule_dec, field_map, rs_input.get("source_tables", []))
        rules[code] = rule_obj
        if missing_logic:
            all_missing_logic.append((code, missing_logic))

    # 组装 tables 段（表实体：字段定义 + 物理属性）
    f_table_full = meta.get("target", {}).get("f_table", {}).get("table", "")
    tables = build_tables(rules, decisions, field_map, rs_input, f_table_full)

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

    # §7 DQ（从 RS L06 搬入，类型跟 RS 保持一致）
    lines.append("## 7. 数据质量检查(DQ)")
    lines.append("")
    dq = ts.get("dq_rules", [])
    if dq:
        lines.append("| 检查范围 | 检查类型 | 规则名称 | 规则描述 |")
        lines.append("|----------|----------|----------|----------|")
        for d in dq:
            lines.append(f"| {d.get('scope', '')} | {d.get('check_type', '')} | {d.get('rule_name', '')} | {d.get('rule_desc', '')} |")
    else:
        lines.append("*(本表无 DQ 要求)*")
    lines.append("")

    # §8 增量设计（条件出现：只有有增量规则的资产才显示）
    incremental_rules = {
        code: r for code, r in rules.items()
        if r.get("load_mode", "truncate_table") != "truncate_table" and r.get("incremental")
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

    # 3a. 五层校验（含存量 C7-C13 + 新增 N1-N27）
    vr = run_all_validations(decisions, rs_input, field_map)
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
