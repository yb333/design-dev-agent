---
status: draft          # ⚠️ 草案，RS 格式待与需求 agent 责任人对接后定稿
last_reviewed: 2026-07-28
depends_on: [../architecture/architecture.md, ts-format.md]
---

# RS 输入规范

> 本文定义设计开发段的**输入格式**：RS（需求规格）+ mapping 如何组织、如何被 designer 消费。
> RS 文档模板见 `docs/templates/RS模板.md`。

> ## ⚠️ 待对接项（重要）
>
> **RS 的最终格式尚未确定**，本文描述的是**过渡方案**，需与**需求 agent 责任人**对接后定稿。
>
> 核心不确定性：
> - **RS 是否仍是 markdown 文档**？如果需求 agent 最终直接产出结构化数据（JSON/YAML），则 RS 不需要是 md，本文的"md + 标记块"方案可能被推翻，预处理环节也随之简化（无需从 md 提取）。
> - **当前方案（md + 标记块）**是基于"RS 由 BA 人工填写"的现实假设设计的过渡形态。
> - **对接时需确认**：需求 agent 产出的 RS 是 md / JSON / YAML / 其他？这直接决定本文档大半内容是否成立。
>
> **在对接定稿前，本文档的 RS 相关内容（标记块、md 提取）应视为草案，不要据此实现**。mapping 部分和 rs_input.json 的目标结构相对稳定。

---

## 一、输入结构：两个源 + 一步预处理

designer 不直接读原始输入，而是消费预处理后的机读文件：

```
用户输入                      预处理                    designer 输入
┌─────────────────┐          ┌──────────────┐          ┌──────────────┐
│ mapping.xlsx    │          │              │          │              │
│ (2 sheet)       │──┐       │  输入预处理   │──校验──→ │ rs_input.json│
│ 表级+字段级     │  ├──→──→│  (独立环节)   │  通过?   │ (机读、已校验)│
└─────────────────┘  │       │              │          └──────────────┘
┌─────────────────┐  │       └──────┬───────┘
│ RS文档.md       │──┘              │ 不通过
│ (半结构化)      │                  ↓
│ 调度/DQ/平台等  │          [拦住，让人补输入]
└─────────────────┘
```

### 1.1 mapping.xlsx —— 机读，纯数据结构

**只剩 2 个 sheet**：

| Sheet | 内容 | 说明 |
|------|------|------|
| 实体级 mapping | 源表关联关系 | schema/table/cn/alias/join_condition |
| 属性级 mapping | 字段映射 | 源字段→目标字段/类型/转换规则 |

**不再承载**（已移到 RS）：
- ~~调度配置~~（scheduling_config）→ RS §L07
- ~~执行平台配置~~（execution_platform_config）→ RS §L07
- ~~设计配置~~（design_config：wrap_view/grain/strategy）→ RS §1.1 + §L07
- ~~数据流~~（data_flow）→ RS §L03
- ~~源表的 schedule_task 等调度字段~~ → RS §L07 湖表调度信息

### 1.2 RS文档.md —— 半结构化，人写人看 + 标记块

RS 文档主体是给人读的（业务背景、数据探索叙述、方案描述）。

**需要机读的结构化部分，用标记块包裹**（YAML 代码块 + HTML 注释标记），脚本按标记提取，不猜格式。

标记块对人的影响：
- **渲染后不可见**（`<!-- @xxx -->` 是 HTML 注释），人读 md 不受干扰
- **YAML 代码块渲染成灰底框**，key:value 直观可读，比表格更紧凑
- **填表方式**：从"填表格"变"填 YAML 键值"，难度相当
- **未来 agent 产出 RS**：agent 写 YAML 比写 markdown 表格更可靠

### 1.3 输入预处理（独立环节）

**职责**：把 mapping.xlsx + RS.md 合并提取为 `rs_input.json`，并做预检校验。

**为什么独立于 designer**：
1. **职责不同**：预处理是翻译+校验（确定性），designer 是设计判断（智能性）
2. **失败处理不同**：预处理不过→拦住让人补输入；designer 拿不准→闸口问人。分开才清晰
3. **可复用**：rs_input.json 多方消费（designer/优化场景/eval-suite）

**形态**：先做成脚本组（扩展 excel_parser.py + precheck.py，新增 rs_extractor），跑通后考虑是否包装成独立 skill。

---

## 二、RS 文档的标记块约定

RS 中需要机读的部分，用固定标记包裹：

| RS 章节 | 标记 | 内容 | YAML 结构 |
|---------|------|------|-----------|
| §1.1 资产基本信息 | `<!-- @asset -->` | 目标表/owner/粒度 | target/owner/grain |
| §L03 数据流图说明 | `<!-- @dataflow -->` | 数据流描述（自然语言） | description |
| §L07 调度设计 | `<!-- @sched -->` | 频率/SLA/策略 | frequency/sla/strategy |
| §L07 湖表调度信息 | `<!-- @upstream -->` | 上游任务（表→任务名） | list of {table,task,...} |
| §L06 DQ 规则 | `<!-- @dq -->` | DQ 检查规则 | list of {scope,type,rule,desc} |
| §L01 数据探索 | `<!-- @explore -->` | 数据量/空值率/转维率（可选） | volume/null_rate/... |

**标记块格式**：

```markdown
##### L07 初始化及调度设计

<!-- @sched -->
```yaml
strategy: 全量调度
frequency: T+1，一天一调
sla: "3:30"
incremental_key: ""
```
<!-- /@sched -->
```

**提取规则**：脚本查找 `<!-- @xxx -->` 到 `<!-- /@xxx -->` 之间的 YAML 代码块，解析为结构化数据。正文格式漂移不影响提取。

---

## 三、rs_input.json 结构（designer 实际输入）

```jsonc
{
  "meta": {
    "target": {
      "schema": "...",           // ← RS @asset
      "table": "...",
      "cn": "...",
      "description": "..."
    },
    "owner": { "dept": "...", "person": "..." },
    "grain": "...",              // ← RS @asset（逻辑数据实体）
    "load_strategy": {           // ← RS @sched
      "strategy": "全量|增量",
      "incremental_key": "..."
    }
  },

  "source_tables": [             // ← mapping 实体级
    { "schema", "table", "cn", "alias", "join_condition" }
  ],

  "field_mappings": [            // ← mapping 属性级
    {
      "source_field", "source_table", "source_alias",
      "target_field", "target_type", "target_comment",
      "transform_rule"           // 转换规则（自然语言，不含业务术语）
    }
  ],

  "schedule": {                  // ← RS @sched + @upstream
    "frequency": "T+1，一天一调",
    "sla": "3:30",
    "strategy": "全量调度",
    "upstream": [                // 上游调度任务（原 source_tables.schedule_task）
      { "table": "...", "task": "task_xxx", "env": "...", "app": "...", "project": "...", "group": "..." }
    ]
  },

  "data_flow_hint": "...",       // ← RS @dataflow（自然语言，设计参考）

  "dq_requirements": [           // ← RS @dq
    { "scope": "字段级|表级|跨表级", "check_type": "...", "rule_name": "...", "rule_desc": "..." }
  ],

  "data_exploration": {          // ← RS @explore（可选，辅助设计判断）
    "volume": "...",
    "key_field_null_rate": "...",
    "transform_rate": "..."
  }
}
```

> **rs_input.json 是 designer 的唯一输入**。designer 不直接读 mapping.xlsx 和 RS.md。

---

## 四、预检规则（预处理环节校验）

预检不通过则拦住，让人补输入（呼应"待确认在输入阶段解决，不带到设计输出"）：

| 检查项 | 说明 | 失败处理 |
|--------|------|----------|
| mapping 完整性 | 实体级+属性级 sheet 都存在且非空 | 报错，要 mapping |
| RS 标记块完整 | @asset/@sched/@upstream 等必要标记块存在且可解析 | 报错，指出缺哪个标记块 |
| 目标表字段覆盖 | RS/mapping 定义的目标字段 ≥ 属性级 mapping 的目标字段 | 报错，缺哪些字段 |
| 转换规则无业务术语 | 属性级 mapping 的 transform_rule 不含业务术语（前置校验） | 警告，建议改写 |
| 上游任务完整 | 每个源表在 @upstream 有对应调度任务 | 警告，缺哪个源表的任务 |
| 调度信息完整 | @sched 的 frequency/sla 有值 | 警告 |

> 预检的返回码机制沿用现有 precheck（0=PASS / 1=WARNING / 2=INCOMPLETE）。

---

## 五、关键设计决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | **mapping 只剩表级+字段级** | 配置类信息（调度/平台/DQ）归 RS，mapping 纯数据结构 |
| 2 | **RS 用标记块承载机读部分** | 可靠且不脆（不猜格式）；渲染后不影响人读；未来 agent 产出更友好 |
| 3 | **合并成 rs_input.json 给 designer** | designer 只读一个机读文件，职责清晰 |
| 4 | **预处理独立于 designer** | 翻译校验≠设计；失败处理不同；可复用 |
| 5 | **预检拦在前面** | 待确认在输入阶段解决，不带到设计输出 |

---

## 六、与现状的迁移对照

| 现状 mapping.json 字段 | 去向 |
|------------------------|------|
| target_schema/table/cn | RS @asset → rs_input.meta.target |
| source_tables（含 schedule_task） | mapping 实体级（去 schedule_task）+ RS @upstream |
| field_mappings | mapping 属性级 → rs_input.field_mappings |
| scheduling_config | RS @sched → rs_input.schedule |
| execution_platform_config | RS @upstream → rs_input.schedule.upstream |
| design_config（grain/strategy） | RS @asset + @sched → rs_input.meta + schedule |
| design_pattern/scene_count/field_statistics | **删除**（是 designer 派生产出，不是输入） |
| data_flow | RS @dataflow → rs_input.data_flow_hint |

---

## 七、开放问题

1. **标记块的维护**：BA 填 RS 时可能破坏标记块结构，靠预检兜底。未来 agent 产出 RS 后此问题消失。
2. **预处理是脚本组还是独立 skill**：先脚本组（扩展 excel_parser+precheck），跑通后评估。
3. **RS @explore 数据探索是否必填**：当前可选（辅助设计判断），待实战验证价值。

---

*本文档随实践演进。RS 模板见 `docs/templates/RS模板.md`。*
