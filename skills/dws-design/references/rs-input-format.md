# RS 输入规范

> 本文定义设计开发段的**输入格式**：RS（需求规格）+ mapping 如何组织、如何被 designer 消费。
> **RS 模板（`docs/templates/RS模板.md`）是项目仓维护的外部对接基准**——不在 skill 安装目录内，agent 不需要读取它，仅作为理解上下文。模板若变更，需同步更新本文件和同目录的 `preprocess.py`。

---

## 一、输入结构：两个源 + 一步预处理

designer 不直接读原始输入，而是消费预处理后的机读文件：

```
用户输入                      预处理                    designer 输入
┌─────────────────┐          ┌──────────────┐          ┌──────────────┐
│ mapping.xlsx    │          │              │          │              │
│ (2 sheet)       │──┐       │  输入预处理   │──校验──→ │ rs_input.json│
│ 表级+字段级     │  ├──→──→│  (脚本)       │  通过?   │ (机读、已校验)│
└─────────────────┘  │       │              │          └──────────────┘
┌─────────────────┐  │       └──────┬───────┘
│ RS文档.md       │──┘              │ 不通过
│ (BA写的markdown)│                  ↓
│ 调度/DQ/上游等  │          [拦住，让人补输入]
└─────────────────┘
```

### 1.1 mapping.xlsx —— 机读，纯数据结构

**只剩 2 个 sheet**：

| Sheet | 内容 | 说明 |
|------|------|------|
| 实体级 mapping | 源表关联关系 | schema/table/cn/alias/join_condition |
| 属性级 mapping | 字段映射 | 源字段→目标字段/类型/转换规则 |

### 1.2 RS文档.md —— BA 写的纯 markdown，从表格提取

RS 是 BA（业务分析师）写的 markdown 文档，有**固定模板**（RS 模板是项目仓维护的外部对接基准，不在 skill 内）。

**不要求 BA 写 YAML 或标记块**——RS 保持纯 markdown（表格+文字），BA 友好。

**预处理脚本从 RS 的 markdown 表格提取结构化信息**：
- 按**章节标题**定位（§1.1 资产基本信息、§L07 调度设计、§L06 DQ 等）
- 按**表头列名**匹配提取（不依赖列顺序）
- 提取失败/数据不全 → **预检报错，要求重新输出 RS**

> RS 模板是项目仓维护的对接基准。如果 RS 模板修改了（章节标题/表头变了），需同步更新同目录 `preprocess.py` 的 header_map + 本文件的表头匹配表。

**需要从 RS 表格提取的信息**（其余叙述性内容 designer 靠 AI 理解读取，不提取）：

| RS 章节 | 提取什么 | 表格类型 |
|---------|---------|---------|
| §1.1 资产基本信息 | 目标表 schema/table/描述/owner/粒度 | 键值表（属性|内容） |
| §L07 调度设计 | 调度策略/频率/SLA/增量键 | 键值表（配置项|内容） |
| §L07 湖表调度 | 上游任务（表→任务名） | 列表表（多行） |
| §L06 DQ 规则 | 质量检查规则 | 列表表（多行，驱动 DQ 产出：有则 designer 翻译产、无则不产） |

### 1.3 输入预处理（脚本）

**职责**：把 mapping.xlsx + RS.md 合并提取为 `rs_input.json`，并做预检校验。

**为什么独立**：
1. **职责不同**：预处理是解析+校验（确定性），designer 是设计判断（智能性）
2. **失败处理不同**：预处理不过→拦住让人补输入；designer 拿不准→闸口问人
3. **可复用**：rs_input.json 多方消费（designer/优化场景/eval-suite）

**脚本位置**：`skills/dws-design/scripts/preprocess.py`
- 复用 excel_parser 解析 mapping.xlsx
- 解析 RS.md 的 markdown 表格（按章节+表头）
- 合并成 rs_input.json + 预检

---

## 二、RS 表格提取约定

预处理脚本从 RS.md 提取时的章节定位和表头匹配规则：

| RS 章节 | 定位关键词 | 表头匹配（RS列名→rs_input字段） |
|---------|-----------|-------------------------------|
| §1.1 资产基本信息 | "资产基本信息"/"资产概述" | SCHEMA→target_full, 资产描述→description, 业务对象→business_object, 逻辑数据实体→grain, owner 部门→owner_dept, owner 人员→owner_person |
| §L07 调度设计 | "初始化及调度"/"L07" | 调度方案→strategy, 调度频率→frequency, 调度完成时间→sla, 增量识别→incremental_key |
| §L07 湖表调度 | "湖表调度" | 湖表→table, 任务名→task, 环境→env, 项目→project, 任务组→group |
| §L06 DQ规则 | "数据质量检查"/"L06" | 检查范围→scope, 检查类型→check_type, 规则名称→rule_name, 规则描述→rule_desc |

> **维护约定**：RS 模板（项目仓维护）是基准。模板改了 → 同步更新同目录 `preprocess.py` 的 header_map + 本表的表头匹配列。

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
| RS 表格可解析 | §1.1/§L07 等章节的表格存在且表头可匹配 | 报错，指出哪个章节表格缺失 |
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
| 2 | **RS 保持纯markdown表格，预处理解析提取** | BA友好（不要求YAML）；有固定模板保证解析稳定；提取失败则校验报错要求重出 |
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

1. **RS 模板同步**：别人的 RS 模板修改了（章节标题/表头变化），需同步更新同目录 `preprocess.py` 的 header_map + 本文件的表头匹配表。
2. **预处理是脚本组还是独立 skill**：先脚本组（扩展 excel_parser+precheck），跑通后评估。
3. **RS @explore 数据探索是否必填**：当前可选（辅助设计判断），待实战验证价值。

---

*本文档随实践演进。RS 模板是项目仓维护的外部对接基准。*
