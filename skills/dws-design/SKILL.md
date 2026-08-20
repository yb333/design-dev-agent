---
name: dws-design
description: >-
  DWS ETL 设计方法论。被 dws-designer agent 加载。
  指导 designer 如何从 rs_input.json 产出设计决策(design_decisions.yaml),
  再由 assemble_ts.py 组装成 TS 制品包(ts.json + ts.md)。
---

## ⚠️ 文件路径规则（必须遵守）

本 skill 的所有文件（scripts/ 下的脚本、assets/ 下的模板、references/ 下的指导知识）都在 **skill 安装目录** 下，不在你的工作目录下。

### 怎么拿到 skill 安装目录的真实路径

加载 skill 后，opencode 会注入 skill 的 `location`（SKILL.md 的绝对路径）和 `<skill_files>` 文件列表。**用这些注入的路径**找文件——location 的同级目录下分三类：
- `scripts/`：脚本（.py）
- `assets/`：模板（骨架、example 配置，带 template/example 后缀）
- `references/`：指导知识（规范、方法论、格式说明等文档）

### 读取文件

用注入的 location 路径拼目录，例如：
- `{location所在目录}/assets/design-decisions-template.yaml`（模板骨架）
- `{location所在目录}/references/design-guide.md`（规范文档）
- `{location所在目录}/scripts/assemble_ts.py`（脚本）

**绝对不要**按当前工作目录或 `~` 去拼路径——跨平台会出错。

---

# DWS ETL 设计 Skill

> 本 skill 被 **dws-designer** agent 加载，提供设计方法论。
> TS 制品包的 ts.json 结构权威定义见 `assets/ts-template.json`（字段含义见文件内注释）。

---

## 1. 设计的核心任务

把需求（rs_input.json）转化为技术规格（TS），本质是：

> **把一个资产的加工，划分成多个步骤（规则），清晰表达加工逻辑。**

规则是核心实体（一条 INSERT = 产出一个表）。场景是规则的属性。

**关键：designer 只产设计判断（design_decisions.yaml），不直接写 ts.json。**
字段类型/来源/注释等确定性数据由 `assemble_ts.py` 脚本从 rs_input.json 自动搬移。
这避免了 AI 手写大 JSON 的格式错误和上下文爆炸。

---

## 2. 设计流程：五层决策骨架（★ 思考主线）

> 设计是从目标表**倒推**的过程。每一层有明确的"想清楚什么 + 产出什么 + 闭合条件"。
> 前一层没闭合就不该进下一层——闭合条件由 assemble_ts 校验兜底，没过会被 fail-loud 拦回。

先读 `rs_input_view.json` 的 compact 视图建立认知（不是 rs_input.json 全文）：
- `tables`：源表清单（哪些表、规模、关联）→ 理解全貌、判断数据源缺口
- `direct`：直取/赋值字段按源表分块 → 批量搬运字段扫一眼过
- `processed`：加工字段逐个平铺（含完整多步骤口径/多表来源合并）→ 逐个拆解加工链
- `incremental_tables`（如有）：增量驱动表清单
- 需要某字段精确细节（如完整 source_type）时再查 rs_input.json 的 field_mappings

### 第0层 锚点（强制闭合）— 产出表粒度 + 业务主键

**想清楚**：这张表"一行 = 什么业务实体"？业务主键（business_key）在产出粒度下能不能唯一框定一行？
- BA 在 mapping/RS 里标的主键是**业务视角**，designer 必须确认它在产出表的**物理粒度**下唯一
- 粒度变化（头行整合、聚合收敛）会让原主键发散 → 必须补字段让主键唯一
- 这层错，后面全错（主键发散 → UT 数据质量失败最高频根因）

**产出**：`grain.input/output`、`business_key`、`business_key_design`（input_key/adjusted/reason）
**闭合条件**（assemble_ts 硬校验）：grain 非空 + business_key 非空 + business_key_design 论证完整 + business_key 字段在目标表存在

### 第1层 字段血缘（含场景横切）— 逐字段定来源身份

**想清楚**：每个目标字段的值从哪来、怎么来？来源身份三种：
- **直取**：值直接从某源表字段复制 → 归该源表所在的规则
- **加工**：值由多字段加工算出 → 归执行该加工的规则
- **赋值**：值是固定值/序列 → 归目标表对应的规则

**场景是这层的横切属性**（不单列一层）：同一目标表的数据来自不同来源、需不同加工逻辑 → 多场景。判断依据是"来源不同/加工逻辑不同"，天然在分析字段血缘时识别。场景是规则的 `scenario` 属性。

**产出**：每个规则 `field_targets`（它管哪些目标字段）
**闭合条件**：每个 target_column 归属且仅归属一个规则；目标表规则 field_targets 并集 = rs_input 所有字段（中间表字段不算）

**类型风险字段的安全处理**：如果 `_internal/type_risk_decision.yaml` 存在（预检检测到"直接复制"字段有类型风险、经人决策），读它——对清单内字段的 design_logic 加类型安全处理，**不在清单的字段绝不加多余处理**：
- 批量"加安全处理" → 常规风险字段（长度超长/精度收窄）加对应处理（超长截取到目标长度、CAST 到目标精度）
- 跨大类"转换" → 加转换函数（如 TO_DATE/TO_CHAR/CAST）
- 跨大类"不加" → 正常设计，不加处理
- 跨大类"返源端" → 该字段标"需源端处理"，本资产不加工

### 第2层 加工路径 — 组织成路网

**想清楚**：把字段血缘组织成加工路径。核心是两个决策：**要不要拆多步** + **拆了用什么承载（CTE/物化）**。

- **拆分决策**：综合权衡正确性/性能/可维护性/扩展友好/存储，不套默认。倾向扩展友好的设计（不管未来变不变，扩展友好本身合理）。复杂度信号（异质聚合/JOIN>12/聚合后关联/关联链实质加工/CTE依赖链≥3）触发考虑拆。
  → 完整拆分框架 + 案例分析见 `references/complexity-playbook.md` §一/§二/§四
  → **在 `design_approach` 写清为什么这样拆/不拆**
- **物化 vs CTE 决策**：决定拆了之后——满足任一条件就物化（多次引用 / 估算偏差>10x / 数据量大 / 需要检查点 / 跨步骤传递），否则用 CTE 内联。
  → 完整决策标准见 `references/complexity-playbook.md` §三
- **中间表产出模式**：单一规则一次性产出（`build_mode: transform`，默认）/ 多规则累积共建（`build_mode: accumulate`，去重或 union）。
  → 累积共建的排重策略见 `references/incremental-playbook.md` §三/§四
- **关联决策**（从字段倒推 JOIN 结构）：
  - **从字段列表倒推**——哪些目标字段需要 JOIN 哪张维表？每个 JOIN 需要什么条件？不要只搬 RS 的关联定义。
  - **多字段引用同一维表 → 多次 JOIN**（各自别名），不能用一个关联覆盖所有字段。
  - **关联类型**：主表之间（mapping 实体级有多张主表）用 INNER JOIN（两张主表数据都要存在）；主表关联维表用 LEFT JOIN（保留主表数据）。不要默认全部 LEFT JOIN。
  - JOIN 键唯一性验证（关联安全）见第4层（调 explore.py）。
- **数据量因子**：RS data_exploration 或 explore.py 估档位（万/百万/亿），拿不到标"未知"，只影响物化决策，不阻断

**产出**：每个规则 `step_type` + `target_role` + 依赖声明（`produces_for` / `reads`）
**闭合条件**（assemble_ts 校验）：step_type/target_role 合法且不矛盾；中间表有消费者；依赖声明闭合（无悬空、无循环、顺序合法）

### 第3层 时间属性（含场景横切）— 每条路径单独定性增量/全量

**想清楚**：每条数据路径是增量还是全量？增量的话驱动表是谁、增量字段是什么？
- **增量范围由谁决定**——单一驱动表 / 多源独立取增量 / 多表 JOIN 并集重建，三种模式选哪种见 incremental-playbook §二
- **核心铁律**：凡是进了驱动表清单的表，它的变化都要被增量范围覆盖（驱动表之间没有主次，都是变化源）。最容易出错的是漏掉某张驱动表的变化条件
- 场景在这层也是横切：不同来源路径可能增量/全量不同

→ 增量设计的完整决策（三种模式/load_mode/初始化/累积共建排重）见 `references/incremental-playbook.md`

**产出**：增量规则的 `incremental` 段（key/filter/init_*）；merge 规则的 `load_mode`
**增量参数**：filter 用标准参数 `${P_START_DATE}` / `${P_END_DATE}`（脚本对增量资产自动注入，designer 不声明，详见 incremental-playbook §七）
**闭合条件**（assemble_ts 校验）：标了增量但不能完全没增量处理（硬阻断）；extract 的 incremental 填全；每张驱动表的增量字段是否在增量范围里（warn，语义判断由 designer + 闸口①保证）

### 第4层 工程保障 — 分布键 + 关联安全 + 调度

**想清楚**：
- **分布键**：按业务主键 / 关联使用频率（减少重分布）/ 离散程度选，与数据量无关。多表 JOIN 时各表分布键必须一致。
  → 详见 `references/design-guide.md` §1.1
- **关联安全（三维判断，每个声明的 JOIN 都要对三维度有结论）**：
  - ① **方向（键唯一性）**：JOIN 键在限定条件下是否唯一。不唯一 → 对齐策略（GROUP BY 收敛 / 取最新有效行）。
    不确定时调 explore.py 验证（只读单表，不 JOIN，不会发散；填 join_key_unique；连不上库静默跳过）：
    ```
    python {location所在目录}/scripts/explore.py --ts {deliver}/ts.json \
        --check-join-key --schema {sch} --table {tbl} --key {col} --where "{join_filter}"
    ```
  - ② **类型可比**：两边键类型大类必须可比（字符=数值这种等式本身就是错的）。视图里有类型直接判；
    没有 → 用 schema_query 查双侧（`--table schema.table --column 列名`，返回类型，两边各查一次对比）。
    不可比但内容兼容 → joins 里声明 cast（显式转换表达式，如 `a.prod_code::numeric`，coder 按声明写不自己发挥）；
    不可比且内容对不上 → 关联键选错了，回 mapping/人确认。紧凑视图 `join_type_risk` 段是 precheck 的
    前置检出（处置=转换的必须声明 cast，N_JOIN1 校验核对）；**precheck 没检出的（自然语言条件等）
    靠这一维判断兜住——不写 cast 就是签了"可比"**。
  - ③ **内容语义**：类型全兼容但值域可能对不上（'1' vs '01'、编码 vs 名称——不报错只静默空关联）。
    存疑时调 explore.py 重叠率试算取证：
    ```
    python {location所在目录}/scripts/explore.py --ts {deliver}/ts.json \
        --check-overlap --schema-a {sch1} --table-a {t1} --key-a {k1} \
        --schema-b {sch2} --table-b {t2} --key-b {k2}
    ```
  结论必答、取证按需（工具按需调，不逐 JOIN 机械跑）。
- **调度**：schedule_type（从 RS 调度频率推导）、cron（Quartz 6 段标准表达式）、依赖类型（默认宽依赖）
  → 依赖类型选择见 `references/design-guide.md` §二

**产出**：`tables.{表}.distribution_key`、`join_safety`、`schedule`
**闭合条件**（assemble_ts 校验）：schedule_type 合法；cron 格式合法；distribute_type 合法；distribution_key 字段在所属表存在；join_type_risk 检出对的 cast/豁免核对（N_JOIN1）

### 字段加工逻辑（贯穿第1-2层）

- **field_logics 只写加工类字段**（数据加工/赋值/序列）的 design_logic（自然语言口径，不含 SQL）
- **直取字段不写**——脚本自动填 "直取 {alias}.{column}"
- **★ 类型转换字段是加工字段**：precheck 类型风险决策通过后，会回写 rs_input 把转换字段改"数据加工"（transform_detail 标注如"类型转换：varchar→date"）。读到这类字段照常写 field_logic（转换口径），coder 翻译成 CAST/TO_DATE。**改 ETL 不改 DDL（目标类型不变）**
- **design_logic 引用 mapping 未列的同表字段、不确定是否存在时**，可调 design-dev-shared 的 `schema_query.py` 确认（在本 skill 上三级同目录的 design-dev-shared/scripts/ 下，读 precheck 产的 schema_cache，不连库，秒级）：
  `python .../schema_query.py --ts {deliver}/_internal/rs_input.json --table ods.ods_b --column col2`
  （--ts 是定位锚点，设计阶段传 rs_input.json——cache 就在它同级 _internal/；工具按需取用不是必经步骤，确定字段存在就不用查）
  —— 设计确认过的，coder 信任 design_logic。要引用 rs_input 完全未声明的全新表时不要用工具绕，正路是补 mapping（闸口①确认）
- 加工字段没写 design_logic 会被硬校验拦住（不允许占位继续跑）

### 产出 + 组装

- 写 `design_decisions.yaml`（骨架见 `assets/design-decisions-template.yaml`）
- 调 `assemble_ts.py` 组装出 ts.json + ts.md
- 校验失败 → 看报错的 `[第X层]` 标识定位到对应 playbook 修正后重跑

### 路由段：什么时候读哪个 playbook

| 触发条件 | 读哪个 |
|---------|--------|
| RS 标了增量（L07 增量识别方式 ≠ "不涉及"）| `references/incremental-playbook.md` |
| 第2层评估复杂度 / 要拆步骤 / 要建中间表 | `references/complexity-playbook.md` |
| 累积共建场景（多规则写同一中间表）| `references/incremental-playbook.md` §三/§四 |
| 分布键/分区/依赖类型 | `references/design-guide.md`（每次都薄，直接读）|

> 简单全量单表资产：五层很快走完，第2层不拆中间表（走 full 单规则），第3层全量，只读 design-guide.md 就够。

### DQ 规则（RS 驱动，designer 翻译）

DQ 不在五层里（五层是加工设计主线），但 DQ 产出有明确规则。**designer 是翻译者，不是搬运工，也不自主决定产不产**——类比 field_logics 写 design_logic：

- **RS 有 DQ 需求**（`rs_input_view.json` 的 `dq.requirements` 非空）→ designer **翻译**成 coder 可执行的 DQ 规格写进 `dq_rules`
  - `scope`/`check_type`/`rule_name` 跟 RS 保持一致（分类不变）
  - `rule_desc` 是**翻译后的技术口径**（检查哪个字段、什么条件、阈值、告警级），不是 RS 原文复制
  - 例：RS `rule_desc="订单金额不能为空"` → 翻译 `rule_desc="检查 dwb_order_f.order_amount IS NOT NULL，空值告警"`
  - 翻译后条数可增加（一条模糊需求拆多条），但不应少于 RS（assemble_ts 会 warn）
- **RS 无 DQ 需求**（`dq.requirements` 为空，标注"无 DQ"）→ `dq_rules` 留空，**不产任何 DQ**（coder 不调、无 DQ 调度任务）
- designer **不自主决定产不产**（DQ 是业务决策归 RS），RS 有就翻译、没有就不干
- 无"标准三项系统兜底"（主键唯一/审计非空/记录数不再无条件产）——UT 阶段 `ut_execute` 已查主键重复，上线后要不要持续监控是业务决策

> assemble_ts 硬校验 N_DQ1：RS 有 DQ 但 `dq_rules` 空 → fail-loud（漏翻译根因）；N_DQ2/N_DQ3 是 warn（条数偏少/RS 无但自加）。

---

## 3. 数据流图

- 节点 = 规则（产出表）
- 场景通过节点属性标记
- 多场景并行通过 schedule_groups 表达
- 在 design_decisions 的 data_flow 里定义 dependencies + schedule_groups

---

## 4. 参考文档

| 文档 | 内容 | 何时读 |
|------|------|--------|
| `assets/design-decisions-template.yaml` | **design_decisions 产出骨架**（含填写规则注释） | 写产出时 |
| `references/design-guide.md` | 物理设计决策（分布键/分区）+ 依赖类型 | 每次都读（薄） |
| `references/incremental-playbook.md` | 增量设计全集（数据流/累积共建/排重/初始化） | RS 标了增量时 |
| `references/complexity-playbook.md` | 拆分设计框架 + 复杂度信号 + CTE/物化决策 + step_type + 案例分析 | 拆步骤/复杂场景时 |
| `references/rs-input-format.md` | RS 输入格式（理解输入） | 需要时查 |
| `assets/ts-template.json` | TS 制品包 ts.json 结构定义 | 组装目标参照 |
| `assets/ts-template.md` | ts.md 渲染骨架 | 渲染参照 |

---

## 6. 产出检查清单（按五层）

写好 design_decisions.yaml 后自检，再调脚本（校验项对应 assemble_ts 的分层校验）：

**第0层 锚点**
- [ ] `grain.input/output` 非空（一行 = 什么业务实体）
- [ ] `business_key` 非空，且字段都在目标表存在
- [ ] `business_key_design` 论证完整（input_key / adjusted / reason；adjusted=false 时 reason 写"沿用输入主键，产出粒度未变"）

**第1层 字段血缘**
- [ ] rules 里每个规则有 rule_code / rule_name / field_targets
- [ ] 每个 target_column 归属且仅归属一个规则（目标表规则并集覆盖 rs_input 全字段）
- [ ] field_logics 只写加工类业务字段（直取字段不写，脚本自动填）
- [ ] design_logic 是自然语言口径，不含 SQL
- [ ] 如果 mapping 提供了审计字段（备注标"审计字段"），field_targets 要包含它们；审计字段不用写 field_logics（assemble 自动处理）

**第2层 加工路径**
- [ ] 拆分决策：综合权衡（性能/可维护/扩展/存储），不套默认（见 complexity-playbook §一/§二）
- [ ] **在 design_approach 写清为什么这样拆/不拆**（闸口①人要看）
- [ ] 每个规则有 step_type（full / aggregate / incremental_extract / merge，见 complexity-playbook §五）
- [ ] target_role 与 step_type 不矛盾（见 complexity-playbook）
- [ ] 多步骤时声明依赖：中间表填 produces_for，装配/merge 填 reads
- [ ] 累积共建表标了 `build_mode: accumulate`，排重场景填了 dedup_strategy

**第3层 时间属性**
- [ ] 增量场景：每张驱动表的变化都被增量范围覆盖（见 incremental-playbook 三种模式）
- [ ] extract 规则的 incremental.key/filter/init_filter 填全

**第4层 工程保障**
- [ ] distribution_key 选了高基数 JOIN 字段（参考 design-guide.md §1.1）
- [ ] schedule.schedule_type 合法（daily/hourly/realtime）
- [ ] schedule.cron 是 Quartz 6 段表达式
- [ ] 复杂度/分段决策写进 complexity_analysis.design_approach（进 ts 文档）

**DQ（RS 驱动）**
- [ ] `rs_input_view.dq.requirements` 有内容 → `dq_rules` 已翻译（条数 ≥ RS，rule_desc 是技术口径给 coder）
- [ ] `rs_input_view.dq` 标注"无 DQ" → `dq_rules` 为空（不自主补）

**组装**
- [ ] 调 assemble_ts.py 成功产出 ts.json + ts.md（无校验错误；失败看报错的 `[第X层]` 定位）
