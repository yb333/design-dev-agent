---
status: active
last_reviewed: 2026-07-28
depends_on: [../architecture/architecture.md]
sample: [../output/dwl_con_pu_any_f/02_design/ts.json, ../output/dwl_con_pu_any_f/02_design/ts.md]
---

# TS 制品包格式定义

> 本文定义设计开发段的核心产出——**TS（技术规格）制品包**的格式。
> 样板见 `docs/output/dwl_con_pu_any_f/02_design/`（`ts.json` + `ts.md`）。

---

## 一、形态：制品包（ts.md + ts.json）

TS 不是单文档，是**制品包**：

| 文件 | 角色 | 谁消费 |
|------|------|--------|
| `ts.md` | 人读投影，宏观概要，闸口①确认用 | 人（闸口①）、归档 |
| `ts.json` | 机读权威源，完整字段映射，按规则分组 | coder（按规则切片读取）、orchestrator、tester |

**权威性**：`ts.json` 是权威源，`ts.md` 是其投影（单向渲染，避免不一致）。

**为什么是制品包而非单文档**：大表（300+字段、10+规则、3+场景）的完整字段映射放进 md 会爆炸（~50KB表格），人无法读；下沉 json 后，coder 按规则切片读取，实现真正上下文隔离。

---

## 二、核心理念：规则（rule）是核心实体

> **TS 的最终目的，是把一个资产的加工，划分成多个步骤（规则），清晰表达加工逻辑、实现加工。**

- **规则（rule）= 一条 INSERT 语句 = 产出一个表**（中间表或目标表）
- **场景是规则的属性**（不是独立结构层），通过规则的 `scenario` 字段标记
- **规则与规则的对应关系不固定**：简单时多来源合一规则（UNION ALL），复杂时一来源一规则，最后可能多场景收口在某一步规则
- 一切组织维度（场景、来源、收敛、依赖）都锚定在规则上

---

## 三、ts.json 结构定义

### 3.1 顶层结构

```jsonc
{
  "version": "1.0.0",
  "spec_type": "ts",
  "generated_at": "...",
  "generated_by": "dws-designer",

  "meta":       { ... },   // 元信息
  "design":     { ... },   // 设计分析
  "rules":      { ... },   // ★ 核心实体：规则集合
  "data_flow":  { ... },   // 规则间关系（参照 analyzer）
  "dq_rules":   [ ... ]    // DQ（可选）
}
```

### 3.2 `meta` —— 元信息

```jsonc
"meta": {
  "target": {
    "f_table": { "schema", "table", "cn" },   // F表（物理表，存数据）
    "i_view":  { "schema", "table", "cn" }    // I视图（F表镜像，对外消费，固定成对）
  },
  "grain": "目标表粒度",
  "load_strategy": { "strategy": "overwrite|partition|append", "label", "delete_mode" },
  "field_count": { "business": N, "audit": 4, "total": N },
  "source_tables": [ { "schema", "table", "table_cn", "alias" } ],

  "schedule": {
    "task_name": "...",              // designer命名（RS给大框架→designer细化）
    "cron": "...",                   // designer细化为标准表达式
    "task_group": "...",
    "project": "...",
    "owner": "...",
    "exec_params": { ... },
    "upstream": [                    // 上游依赖（RS给 + 中间表增量）
      { "table", "task", "source": "rs|designer" }
    ],
    "execution_platform": { "project_code", "datasource" }
  }
}
```

> **F表+I视图成对**：I视图是F表的稳定消费接口（`SELECT * FROM ..._f`），字段不变则F表逻辑变化不影响I。绝大多数场景I=F镜像。

### 3.3 `design` —— 设计分析

```jsonc
"design": {
  "complexity_analysis": {
    "join_count", "has_grain_change", "grain_change_detail",
    "multi_step_fields", "aggregation_after_join",
    "segmentation_decision": "不分段|分段",
    "segmentation_reason": "..."
  },
  "audit_fields": {                    // 审计字段模板（4个固定字段，不在rules.fields重复）
    "del_flag":            { "type", "default" },
    "crt_cycle_id":        { "type", "default" },
    "last_upd_cycle_id":   { "type", "default" },
    "dw_last_update_date": { "type", "default" }
  },
  "distribution_key": [...]            // 目标表+中间表统一管（分布键只在design层定义）
}
```

> **审计字段放模板**：4个审计字段每表固定，放 `design.audit_fields` 作为模板，不在每个规则的 fields 里重复（避免切片噪声）。

### 3.4 `rules` —— ★ 核心实体：规则集合

```jsonc
"rules": {
  "R0001": {                           // 按 rule_code 索引（可切片读取）
    "rule_name": "...",
    "scenario": "...",                 // ★ 场景是属性（单场景名 / 多场景合并标记）
    "exec_sequence": 1,
    "target_table": "...",             // 产出表（中间表 / 目标F表 / 视图I表）
    "is_view_step": false,
    "design_intent": "...",            // 该规则的设计意图（自然语言）

    "source_tables": [ { "schema", "table", "alias" } ],

    "grain": {                         // 输入→输出粒度变化
      "input": "...",
      "output": "...",
      "change": "..."
    },

    "joins": [                         // 关联策略
      { "alias", "type": "main|LEFT JOIN|...", "condition", "filter" }
    ],

    "join_safety": [                   // 关联安全分析（JOIN键唯一性→对齐策略）
      { "table", "join_key_unique": bool, "strategy": "...", "reason": "..." }
    ],

    "fields": [                        // ★ 该规则产出的字段（内嵌，天然按规则分组）
      {
        "target_field": "...",
        "field_type": "...",
        "field_comment": "...",
        "transform_type": "direct|pivot|aggregate|assign",
        "source_fields": [ { "table", "field", "alias" } ],
        "design_logic": "..."          // 自然语言口径，不含SQL表达式
      }
    ],
    "field_count": N
  }
}
```

**字段设计要点**：
- **字段内嵌规则**（`rules.R0001.fields`），不单独 `field_mappings`——天然按规则分组，切片=取一个规则
- **`design_logic` = 自然语言口径**（从RS拆出，不含业务术语，不含SQL表达式）；SQL由coder翻译
- **`transform_type` + `source_fields` = 结构化**（支撑机读校验：静态检查SQL是否与TS一致）
- **自建字段（中间表字段）= 规则的目标字段**，不区分层级，按所属规则组织
- **审计字段不在 fields 列出**（用 design.audit_fields 模板）

### 3.5 `data_flow` —— 规则间关系（参照 analyzer）

```jsonc
"data_flow": {
  "tables": [                          // 表节点（数据流图的节点之一）
    { "schema", "name", "role": "source|target", "layer": "ODS|DWB|DWL|DIM", "is_view": false }
  ],
  "dependencies": [                    // 规则间数据流向（数据流图的边）
    { "from": "R0001", "to": "R0002", "type": "data_flow", "intermediate_table": "..." }
  ],
  "schedule_groups": [                 // 执行顺序/并行（场景并行在此体现）
    { "sequence": 1, "rules": ["R0001"] },
    { "sequence": 2, "rules": ["R0002"] }
  ]
}
```

> **数据流图参照 analyzer**：analyzer 的 HTML 数据流图已定义清晰，节点=规则（产出表），场景通过节点属性标记。多场景并行通过 `schedule_groups` 表达。

### 3.6 `dq_rules` —— DQ（可选）

```jsonc
"dq_rules": [                         // 可选，预制占位（不是每表必须）
  {
    "rule_id": "DQ_001",
    "rule_name": "...",
    "check_type": "uniqueness|range|consistency|...",
    "target": "...",
    "threshold": "...",
    "alert_level": "high|medium|low"
  }
]
```

> DQ 只放**设计意图**（规则/类型/对象/阈值/告警级），DQ SQL 由 coder 生成。标准模板检查（主键唯一/非空/行数）在 tester skill 自动套用，不在此重复。

---

## 四、ts.md 章节结构（7章）

| 章节 | 内容 | 来源（ts.json节点） |
|------|------|---------------------|
| §1 概述 | F+I表/粒度/写入策略/分布键/字段统计/来源表 | meta |
| §2 表模型设计 | 目标表(F+I成对/分布键/分区) + 中间表骨架 | meta.target + design.distribution_key + rules中is_view_step=false的非目标表 |
| §3 复杂度分析与分段决策 | 复杂度指标 + 中间表/分段决策结论 | design.complexity_analysis |
| §4 规则详情 | 每规则: 意图/CTE/粒度/关联/关联安全 + 字段概要 | rules（完整字段在json，md只放统计+抽样） |
| §5 数据流向图 | mermaid图(节点=规则) + 血缘关系表 | data_flow |
| §6 调度配置 | cron细化 + 上游依赖(RS给+中间表增量) + 执行平台 | meta.schedule |
| §7 DQ | 可选预制，设计意图 | dq_rules |

> **md 的 §4 字段部分只放概要**（转换类型统计 + 复杂字段抽样），完整300+字段在 ts.json。

---

## 五、关键设计决策记录

| # | 决策 | 理由 |
|---|------|------|
| 1 | **制品包（md+json）**而非单文档 | 300+字段进md会爆炸；json按规则切片实现上下文隔离 |
| 2 | **规则是核心实体**，场景是属性 | 场景与规则对应不固定（一规则多场景/一场景一规则/收口），以规则为锚点 |
| 3 | **字段内嵌规则**，按rule_code分组 | 切片=取一个规则，真正上下文隔离 |
| 4 | **design_logic=自然语言口径**，不含SQL | SQL归coder翻译；自然语言便于闸口①人确认口径 |
| 5 | **transform_type+source_fields=结构化** | 支撑机读校验（静态检查SQL与TS一致性） |
| 6 | **自建字段=规则的目标字段** | 不区分中间表/目标表，按所属规则组织 |
| 7 | **审计字段放design模板** | 4个固定字段，不在每个规则fields重复 |
| 8 | **中间表螺旋式设计** | 先骨架(表名/粒度/用途)→字段逻辑→回填字段 |
| 9 | **调度是细化设计** | RS给大框架(日级)→designer细化cron+补中间表增量 |
| 10 | **DQ可选预制** | 不是每表必须，放设计意图，SQL归coder |
| 11 | **数据流图参照analyzer** | analyzer已定义清晰，节点=规则，场景=属性 |
| 12 | **F表+I视图成对** | I=F镜像，固定模式，稳定消费接口 |

**砍掉的章节及理由**：
- ~~关键设计决策章~~：前面章节已覆盖（§3分段/§4规则内部/§2表模型）
- ~~独立字段映射章~~：下沉ts.json，概要并入§4
- ~~待确认项章~~：不确定是输入补充非输出标注；过程处理留给agent行为设计
- ~~变更记录章~~：新建场景闸口后锁定；用git管版本

---

## 六、与 analyzer 的关系

| 维度 | 本TS（正向设计） | analyzer（反向工程） |
|------|------------------|---------------------|
| 方向 | 整体→拆分多规则 | 已拆分规则→串联看整体 |
| 产出 | ts.json + ts.md | knowledge_draft.json + asset_report.html |
| 场景 | 规则的属性 | 规则的属性（scenario_id） |
| 数据流 | data_flow（tables+dependencies+schedule_groups） | data_flow（同构） |
| 字段映射 | rules.RXXXX.fields（内嵌） | field_mappings.fields |

**拉通约定**：
- analyzer 反向生成的现状 spec，**逆向为我们这个 ts.json 格式**
- 优化场景：designer 在 analyzer 产出的 ts.json 基础上**叠加变更**
- data_flow 结构对齐 analyzer，数据流图样式参照 analyzer 的 HTML 渲染

---

## 七、开放问题（待后续验证/决策）

1. **designer 产出压力**：大表（多场景多规则）designer 单次产出撑不住，需按场景分段工作（先场景骨架→逐场景填充→回填）。这是 agent 行为设计，不影响 ts.json 终态结构。
2. **中间表来源表是否记录**：中间表骨架是否需要标"从哪些表聚合来"，待实战验证。
3. **md 投影渲染器**：ts.md 从 ts.json 自动生成（避免不一致），渲染工具实现待定。
4. **DQ 是否必须**：当前预制占位，后续看是否每表强制。
5. **场景间依赖/去重的结构化表达**：当前靠 data_flow.dependencies + schedule_groups 隐含，是否需要更显式的 scenario_relations，待多场景实战验证。

---

*本文档随实践演进。样板见 `docs/output/dwl_con_pu_any_f/02_design/`。*
