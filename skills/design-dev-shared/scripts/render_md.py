"""render_md —— ts.md 人读投影渲染器（render_md + 数据流 mermaid）。

2026-11-04 自 dws-design/assemble_ts.py 下沉 shared（归位章程：>1 消费者）——
消费者：dws-design/assemble_ts（新建 ts.md）、dws-design/assemble_ts_opt（优化 ts_v2）、
opt-pipe/assemble_ts_baseline（逆向首档 ts.md）。assemble_ts 保名 re-export（零破坏）。

形态容错（逆向/v2 草稿契约无 design 段——存量语义不补，渲染器降级不伪造）：
design 缺省渲染占位、business_key 回退表级、字段数/字段逻辑回退规则桶三形态、
DQ 段对无判定材料的中性文案；design.baseline_design（opt designer 存量设计还原）
有值则渲染设计思路段。
"""
import re

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
                    if "tmp" in target.lower():
                        cls = "intermediate"
                    else:
                        cls = "target"
                    lines.append(f'  {tgt_id}["{target}"]')
                    declared_targets.add(tgt_id)
                    node_classes[tgt_id] = cls
                edges.append((step_id, tgt_id, False))

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
def render_md(ts):
    """从 ts.json 渲染 ts.md(人读投影)。"""
    meta = ts.get("meta") or {}
    target = meta.get("target") or {}
    rules = ts.get("rules") or {}
    design = ts.get("design") or {}   # 逆向/v2 草稿无 design 段——降级渲染（存量语义不补）
    tables = ts.get("tables", {})
    f_table_short = target.get("f_table", {}).get("table", "")

    lines = []
    lines.append(f"# ETL 技术规格(TS)")
    lines.append("")
    lines.append(f"> 目标表: `{target.get('f_table', {}).get('schema', '')}.{target.get('f_table', {}).get('table', '')}`"
                 f"({target.get('f_table', {}).get('cn', '')}) - 生成 {ts.get('generated_at', '-')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # §1 概述
    lines.append("## 1. 概述")
    lines.append("")
    lines.append("| 项目 | 内容 |")
    lines.append("|------|------|")
    _ft = target.get("f_table", {}) or {}
    lines.append(f"| **F 表** | `{_ft.get('schema', '')}.{_ft.get('table', '')}`（{_ft.get('cn', '')}） |")
    i_view = target.get("i_view", {})
    if i_view and i_view.get("table"):
        lines.append(f"| **I 视图** | `{i_view.get('schema', '')}.{i_view.get('table', '')}`（F表镜像，对外查询） |")
    # 业务主键（替代原"目标粒度"——主键即粒度定义）
    # 表级回退（逆向档 design 空、tables.{F}.business_key 逆向恢复有值——2026-09-15 表级化）
    bk = design.get("business_key") or (tables.get(f_table_short, {}) or {}).get("business_key") or []
    lines.append(f"| **业务主键** | {', '.join(bk) if bk else '-'} |")
    # 写入策略：全量可重刷 / 增量（详见规则详情）
    all_truncate = all(r.get("load_mode") == "truncate_table" for r in rules.values())
    load_label = "全量（可随时重刷）" if all_truncate else "增量（详见规则详情）"
    lines.append(f"| **写入策略** | {load_label} |")
    fc = meta.get("field_count") or {}
    lines.append(f"| **字段统计** | {fc.get('total', len((tables.get(f_table_short, {}) or {}).get('fields', [])))} |")
    lines.append(f"| **规则数** | {len(rules)} |")
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
    i_view_short = target.get("i_view", {}).get("table", "")

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
        lines.append(f"| `{f_table_short}` | 目标F表 | {_dist_label(t)} | {part} | {fcount} | {(target.get('f_table') or {}).get('cn', '')} |")
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
    # 存量设计还原（2026-11-04 用户定调：opt designer 从 baseline_view 归纳"前人的设计"，
    # 与逆向已有的设计结果合成完整 ts 文档；首轮起随 advance 进档案——语义空位逐轮填实）
    bd = design.get("baseline_design") or {}
    if bd:
        lines.append("**存量设计还原**（designer 依档案归纳，推断处标「推测，需业务确认」）:")
        lines.append("")
        for k, label in (("grain", "粒度"), ("keys", "主键"),
                         ("topology", "数据流"), ("notes", "边界与存疑")):
            v = str(bd.get(k, "") or "").strip()
            if v:
                lines.append(f"- **{label}**: {v}")
        lines.append("")
    elif not approach and not seg:
        lines.append("> （设计思路待补——逆向建档无设计叙述，首轮优化由 designer 还原后随档累积）")
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
        _ftg = r.get("field_targets")
        if _ftg is None:   # 逆向 v2 草稿无 field_targets——回退三桶 target 并集计数
            _fb = r.get("fields") or {}
            _ftg = ([p.get("target") for p in (_fb.get("processed") or [])
                     if isinstance(p, dict) and p.get("target")]
                    + [a.get("target") for a in (_fb.get("assign") or [])
                       if isinstance(a, dict) and a.get("target")]
                    + [str(d).rsplit(" AS ", 1)[-1].strip() for d in (_fb.get("direct") or [])
                       if " AS " in str(d)])
        lines.append(f"| 字段数 | {len(_ftg)} |")
        lines.append("")

        # 关联派生字段（joins.derived_fields 声明——闸口①可见开窗口径）
        derived_joins = [j for j in r.get("joins", [])
                         if isinstance(j, dict) and j.get("derived_fields")]
        if derived_joins:
            lines.append("**关联派生字段**:")
            lines.append("")
            for j in derived_joins:
                for fname, expr in j["derived_fields"].items():
                    lines.append(f"- `{j.get('alias', '')}.{fname}` = {expr}")
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
        logics = r.get("field_logics") or {}
        if not logics:   # 现行三桶形态：processed 条目即口径（逆向档/新建装配产物同款）
            _pr = (r.get("fields") or {}).get("processed") or []
            logics = {p.get("target", ""): p.get("logic", "")
                      for p in _pr if isinstance(p, dict) and p.get("logic")}
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
        # 调度任务路径（项目/任务组，来自 lts_config，designer 可覆盖）
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
    # DQ 调度任务不在 ts.tasks（DQ 拆分后随 dq.json 产），不在此渲染

    lines.append("---")
    lines.append("")

    # §7 DQ（占位锚点——正文由 assemble_dq 追加渲染）
    # DQ 设计在 assemble_ts 之后由 dws-dq-producer 独立完成（读 RS+mapping+待审 ts），
    # 装配时 assemble_dq 定位本标题整段替换为完整章节。RS 无 DQ 需求（meta.dq_required=0，
    # 装配时从 rs_input 判定；旧档无该键按 ts.dq_rules 兜底——DQ 拆分前的形态）在这里
    # 终态渲染——不留占位（2026-09-22：无 DQ 资产 assemble_dq 不跑，占位会永远残留
    # 误导评审"还有一节没做"）。
    _dq_required = meta.get("dq_required")
    if _dq_required is None:
        _dq_required = len(ts.get("dq_rules") or []) if "dq_rules" in ts else None
    lines.append("## 7. 数据质量检查(DQ)")
    lines.append("")
    if _dq_required:
        lines.append("*(DQ 章节由 dws-dq-producer 独立设计后经 assemble_dq 追加；RS 无 DQ 需求则本资产无 DQ)*")
    elif _dq_required is None:
        lines.append("（DQ 元数据以档案 dq.json 为唯一源——本档不判定，见 dq.json/无则本资产无 DQ）")
    else:
        lines.append("本资产无 DQ 需求（RS dq_requirements 为空）——无 dq.json/无 DQ 调度任务，全程零 DQ。")
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
