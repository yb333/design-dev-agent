---
name: dws-design
description: >-
  DWS ETL 设计方法论。被 dws-designer agent 加载。
  指导 designer 如何从 rs_input_view.json（紧凑视图，唯一人读输入）产出设计决策(design_decisions.yaml),
  再由 assemble_ts.py 组装成 TS 制品包(ts.json + ts.md)。
---

## ⚠️ 文件路径规则

所有附属文件（scripts/ .py、assets/ 模板、references/ 指导文档）在 **skill 安装目录**下——用加载注入的 `location`（SKILL.md 绝对路径）拼 `{location所在目录}/...`，不按工作目录或 `~` 猜路径。skill_files 清单是采样（上限 10，本 skill 17 个附属文件），清单没有 ≠ 不存在，以本文件提到的路径为准。read 被拒（内网权限 bug）→ fallback `Get-Content -Encoding UTF8 '<绝对路径>'`；再失败上报，禁换变体试错。

---

# DWS ETL 设计 Skill

> 本 skill 被 **dws-designer** agent 加载，提供设计方法论。
> TS 制品包的 ts.json 结构权威定义见 `assets/ts-template.json`（字段含义见文件内注释）。

---

## 1. 设计的核心任务

> **把一个资产的加工，划分成多个步骤（规则），清晰表达加工逻辑。** 规则是核心实体（一条 INSERT=产出一个表），场景是规则属性。

**designer 只产设计判断（design_decisions.yaml），不写 ts.json**——确定性数据由 assemble_ts.py 从 rs_input 自动搬。

---

## 2. 设计流程：评估层 + 五层决策骨架（★ 思考主线）

> 设计是从目标表**倒推**的过程。评估层在前把关输入合理性（设计得下去吗），五层是设计本体。
> 每层有明确的"想清楚什么 + 产出什么 + 闭合条件"。前一层没闭合就不该进下一层——闭合条件由 assemble_ts 校验兜底，没过会被 fail-loud 拦回。

先读 `rs_input_view.json`（**唯一人读输入，不读 rs_input.json**——那是脚本域文件，只在工具参数里用它的路径）：
- `评估清单`：评估层工作单（`?` 行填空后一次 `--eval`，见「评估层」）
- `tables`：源表清单（哪些表、规模、关联、输入存疑标记）→ 理解全貌、判断数据源缺口
- `direct`：直取/赋值字段按源表分块（src/tgt/type 目标类型/stype 源类型/note/val）→ 批量搬运字段扫一眼过
- `processed`：加工字段逐个平铺（含完整多步骤口径/多表来源合并；sources 五元组 [schema,table,alias,col,源类型]）→ 逐个拆解加工链
- `schedule`：RS 调度方案（策略/频率/SLA/湖表上游）→ 填 decisions.schedule 的输入
- `scenes`（如有）：场景分组清单（多场景按场景拆规则；某场景字段清单调 pick_targets --scenario 取）
- `incremental_tables`（如有）：增量驱动表清单
- view 缺了你需要的信息 → 上报调用方报缺口（view 改进反馈），不回读原文

### 问题上报（贯穿评估层与五层）

你的问题一律**上报调用方（engineer）**——唯一通道=回复文本（你无 question 工具：它会绕开调用方，两种结局都坏）。你眼里只有调用方——它怎么路由、之后问谁，不是你的认知范围。

**唯一规则：有疑点/问题 → 停手上报，不带着疑点继续设计**。本轮回复=已得结论+问题清单，首行 `⚠ 阻塞上报：<问题>`；调用方能自答的恢复会话带答案续跑，语义类它问身后的人后带回。上报内容带：事实 + 影响 + 你需要的答案形态；**上报里不设"改输入"类建议**（源头修/改 mapping 的完整后果权衡归调用方），也**不自行猜口径顶过去**——那是把源端语义改成你的语义（红线）。

### 评估层（第0层之前）— 输入评估：这份输入设计得下去吗

**想清楚**：三问——①每张源表什么粒度（明细还是汇总）？②每条 join_condition 的键唯一性有依据吗（输入声明 / 实测 / 疑点）？③输入存疑标记各是什么？依据优先级：已核标记与免实测声明（直接用）→ 实测 → 疑点上报。

**产出**：join_safety 事实行（含依据，实测数字直贴 decisions）+ 疑点清单（随回复上报，各补一句疑似方向——上报疑点是合格交卷的一部分，不是失败。疑点答案若改输入，手头设计作废，所以先报再做）。

**用法**：view「评估清单」段是预填好的工作单——`?` 行填空（从 mapping 中文名对物理名，对不出就留空=自动进疑点），一次 `--eval` 收口（stdin 只给 `?` 行答案，预填行自动跑；自设关联=加一行同跑）：

```
python {location所在目录}/scripts/explore.py --rs {deliver}/_internal/rs_input.json --eval <<'EOF'
c2|cust_code|status=1 and del_flag='N'
EOF
```

（bash heredoc 引号免疫；PowerShell 先 `$OutputEncoding=[Text.Encoding]::UTF8` 再 `@'…'@ | python …`）

**闭合**：每条 join_condition 落到"有依据 / 进疑点清单"二态之一，疑点已随回复上报；**疑点清（无疑点，或上报后答复已带回）才进五层**。join_safety 条目有据（N_JOIN3 拦漏条目）兜底。

**判断纪律**：判定标准=实测不是推断（现在不发散≠未来不发散，含"与主表关联后当前数据不发散、设计不受影响"情形——不影响设计≠无风险）；字段引用精确一致（物理名/中文名；相近名是给调用方核实的线索，不是替换依据）；疑点全量不筛选不排序。

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

**产出**：每个规则 `field_targets`（它管哪些目标字段；mapping 备注标"审计字段"的也要含，审计不用写 field_logics——自动处理）
**闭合条件**：每个 target_column 归属且仅归属一个规则；目标表规则 field_targets 并集 = rs_input 所有字段（中间表字段不算）

**类型风险字段的安全处理**：视图中 processed 条目带『决策』标记的字段（原始输入='直接复制'，类型风险已决策回写加处理），译成守卫式转换 design_logic——常规风险（长度超长/精度收窄）按目标长度/精度截取或 CAST，跨大类加转换函数（TO_DATE/TO_CHAR/CAST）。**无标记字段照常直取，绝不加多余处理**（决策内容已回写进视图，不读 `_internal/type_risk_decision.yaml`）。

### 第2层 加工路径 — 组织成路网

**想清楚**：把字段血缘组织成加工路径。核心是两个决策：**要不要拆多步** + **拆了用什么承载（CTE/物化）**。

- **拆分决策**：综合权衡正确性/性能/可维护性/扩展友好/存储，不套默认。倾向扩展友好的设计（不管未来变不变，扩展友好本身合理）。复杂度信号（异质聚合/JOIN>12/聚合后关联/关联链实质加工/CTE依赖链≥3）触发考虑拆。
  → 完整拆分框架 + 案例分析见 `references/complexity-playbook.md` §一/§二/§四
  → **在 `complexity_analysis.design_approach` 写清为什么这样拆/不拆（进 ts 文档，闸口①要看）**
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

**产出**：每个规则 `step_type` + `target_role` + 依赖声明（`produces_for` / `reads`）；规则需排除部分行时填规则级 `filter`；tmp 表名 = 目标表主体+_tmp+序号（"本来就不要"，如 del_flag='N'；冲突让位才用 `dedup_strategy`，两者别混）
**闭合条件**（assemble_ts 校验）：step_type/target_role 合法且不矛盾；中间表有消费者；依赖声明闭合（无悬空、无循环、顺序合法）；规则内别名一别名一表（N31）

### 第3层 时间属性（含场景横切）— 先识别资产增量性，再设计增量管道

**第一步（强制前置，不可跳过）**：看 `rs_input_view` 的 `incremental_tables`——**非空即增量资产**。此时本层的问题不是"选增量还是全量"，而是"**增量管道怎么设计**"——全量直灌不在选项里。

**想清楚**：增量资产的管道结构固定：增量取数 + 终态增量更新，驱动表是谁、增量字段是什么
- **第一铁律（结构）**：至少两个规则——增量取数（incremental_extract→tmp，加工可并入此步）+ 终态规则以增量写入方式更新目标表（merge_into 等）。**绝不 full + truncate_table 直灌增量数据**（每次跑清空历史，低级错误高发区）。单规则直灌被 N28/N_INIT2 硬阻断——校验锚在 RS 增量声明上，忘标增量段一样被拦
- **增量范围由谁决定**——单一驱动表 / 多源独立取增量 / 多表 JOIN 并集重建，三种模式选哪种见 incremental-playbook §二
- **核心铁律（覆盖）**：凡是进了驱动表清单的表，它的变化都要被增量范围覆盖（驱动表之间没有主次，都是变化源）。最容易出错的是漏掉某张驱动表的变化条件
- 场景在这层也是横切：不同来源路径可能增量/全量不同

→ 增量设计的完整决策（三种模式/load_mode/初始化/累积共建排重）见 `references/incremental-playbook.md`

**产出**：增量规则的 `incremental` 段（key/filter/init_*）；merge 规则的 `load_mode`
**增量参数**：filter 用标准参数 `${P_START_DATE}` / `${P_END_DATE}`（脚本对增量资产自动注入，designer 不声明，详见 incremental-playbook §七）
**闭合条件**（assemble_ts 校验）：完全没增量处理（N14 硬阻断）；规则数≥2 且终态非 truncate（N28/N_INIT2 硬阻断）；extract 的 incremental 填全（N15）；每张驱动表的增量字段是否在增量范围里（N16 warn，语义判断由 designer + 闸口①保证）

### 第4层 工程保障 — 分布键 + 关联安全 + 调度

**想清楚**：
- **分布键**：按业务主键 / 关联使用频率（减少重分布）/ 离散程度选，与数据量无关。多表 JOIN 时各表分布键必须一致。
  → 详见 `references/design-guide.md` §1.1
- **关联安全（每个声明的 JOIN：⓪条件可信 + 三维判断，都要有结论）**：
  - ⓪ **条件语义（先于三维）**：join_condition 里"取一/最新/去重"类过滤（如 rn=1）= 从表按业务键不唯一的强信号——①方向必须有对齐结论（GROUP BY 收敛 / 取最新有效行），开窗口径业务语义源端给，designer 不编。存在性/出处已由 precheck+评估层把关，此处兜底语义。
    **开窗列（rn 等设计产物字段）的合法通道（N30 拦你没声明时照此补）**——三形态按场景选，物化层级是设计自由度：
    - **拆中间表物化**（多规则复用/开窗重/需独立验证键唯一性）：R1 产 tmp——field_targets 加该列 + `tables.{tmp}.fields` 声明类型（int8）+ field_logics 写开窗口径，下游规则 reads 该 tmp 关联；
    - **规则内子查询**（单规则消费、开窗简单）：joins 声明 `derived_fields: {rn: "row_number() over(partition by org.org_id order by org.upd_time desc)"}`——coder 翻译成 WITH/内联子查询（文法自选），条件里 `org.rn = 1` 照写；
    - 声明了才放行；mapping 没给"取最新"语义（疑似 copy 残留）→ 不自行还原开窗定义，闸口①退回问源端
  - ① **方向（键唯一性）**：消费评估层事实底座做设计结论——键唯一 → 直接关联；不唯一/存疑 → 对齐策略（GROUP BY 收敛 / 取最新有效行，口径业务语义源端给）＋ join_safety 记 strategy 与依据。评估层未覆盖的（如你自设的新关联）同纪律补取证：`--eval` 加一行同跑（判定纪律/疑点上报见「评估层」）。
  - ② **类型可比**：两边键类型大类必须可比（字符=数值这种等式本身就是错的）。视图里有类型直接判；
    没有 → 用 check_field 查双侧（返回类型，两边各查一次对比）：
    `python skills/dws-design/scripts/check_field.py --rs {deliver}/_internal/rs_input.json --field t1.order_id`
    不可比但内容兼容 → joins 里声明 cast（显式转换表达式，如 `a.prod_code::numeric`，coder 按声明写不自己发挥）；
    不可比且内容对不上 → 关联键选错了，上报调用方确认。紧凑视图 `join_type_risk` 段是 precheck 的
    前置检出（处置=转换的必须声明 cast，N_JOIN1 校验核对）；**precheck 没检出的（自然语言条件等）
    靠这一维判断兜住——不写 cast 就是签了"可比"**。
  - ③ **内容语义**：类型全兼容但值域可能对不上（'1' vs '01'——不报错只静默空关联）。存疑时 explore.py `--check-overlap`（双侧 schema/table/key 各一组）重叠率试算取证。
  三维（①②③）都要有结论——①的事实底座来自评估层；②③存疑才取证（工具按需调，不逐 JOIN 机械跑）。
- **调度**：schedule_type（从 RS 调度频率推导）、cron（Quartz 6 段标准表达式）、依赖类型（默认宽依赖）
  → 依赖类型选择见 `references/design-guide.md` §二

**产出**：`tables.{表}.distribution_key`、`join_safety`、`schedule`
**闭合条件**（assemble_ts 校验）：schedule_type 合法；cron 格式合法；distribute_type 合法；distribution_key 字段在所属表存在；joins 引用的字段在源表/tmp 表真实存在（N30，有 schema_cache 时硬校验——⓪的产物兜底）；join_type_risk 检出对的 cast/豁免核对（N_JOIN1）；自设关联的键两侧类型可比（N_JOIN2，跨大类须声明 cast）

### 字段加工逻辑（贯穿第1-2层）

- **写 yaml 用取料器，不手抄字段清单**（誊写归工具、判断归你；落盘 write 初版短头 + 逐规则粘贴，修改用 edit 不全量重写）：
  `python {skill目录}/scripts/pick_targets.py --rs {deliver}/_internal/rs_input.json --rule --scenario {场景}`
  → 完整规则条目骨架（field_targets 预填、判断位留空），贴进 rules 后填口径/拆分；
  `--alias 别名` 拆多步骤时按来源挑字段；`--audit` 附审计4字段（多步骤规则 targets 需含）。
  输出即最终格式，贴入零调整；禁 python/powershell 拼 yaml 写文件（编码坑）。
- **field_logics 只写加工类字段**（数据加工/赋值/序列）的 design_logic。**design_logic 的产出形态统一为：可执行 SQL 表达式 + 简短口径说明**，说明**一律放全角括号（）里**（表达式只用半角括号——这是形态契约：N36 门禁剥全角括号段后检查，说明里提到的字段名不会被当成未限定引用误拦），例如 `case when nvl(a.del_flag,'N')='N' then 'N' else 'Y' end（三标识均非删除且无 NULL 为 N；空串按 else 走 Y）`：
  - **mapping 原文是 SQL 表达式**（case when/函数调用等）→ **审查后原样保留**，只在括号里写你的理解句（理解与原文有出入=原文有问题——修正并注明，或标"需业务确认"）。**不转述表达式**——人话表达不了 NULL/空串边界（实证：del_flag 转述后语义反转）。方言不管（nvl/decode DWS 兼容；真不兼容 UT 暴露归 coder 机械转写）
  - **mapping 原文是自然语言** → 翻译成 SQL 表达式（这才是真正的"翻译者职责"）；歧义点当场做决定并写进括号（如"'空'按 NULL 处理"），业务语境也定不了的标"需业务确认"
  - **宁可输出带假设标注的表达式，绝不退回纯人话**——纯人话把不确定性隐式传给 coder 自由发挥（漂移源头）；带标注的表达式把不确定性显式传给闸口①裁决
  - 空值口径禁用裸"空"字（歧义源）：写 NULL 或空串，二选一明确
  - 纯照抄原文不附说明句会被 N29 warn 提示（缺审查证据）
- **★ 口径里的源字段引用一律 `别名.字段` 两段**（a.del_flag），不能只写列名，也不能写 `schema.table.field` 三段式（表引用 schema.table 只出现在 coder 的 FROM/JOIN 位置，N36/N30 硬拦）——**未限定字段归属哪个表是你的设计判断，脚本不猜**（view 的 refs 只列未限定词与"多表有此列名"的事实，归属自查：rs_input 源表清单/check_field，多义 question）。产出过**引用门禁**三查：未限定标识符（N36 硬拦）/ 限定引用查表存在（N38 硬拦，未连库降提示）/ 与原文对差疑似丢引用（N37 提示）。**口径引用集就是规则 fields 桶的真来源**（mapping 源字段单元格对加工字段只是提示，脚本按你的引用自动补全）——引用写全 = coder 的字段清单对。ts 两视图：tables=表元数据（DDL），rules.fields 三桶=加工（coder 唯一源；你的 field_logics 装配展开成桶，不落 ts）
- **直取字段不写**——脚本自动填 "直取 {alias}.{column}"
- **★ 类型转换字段是加工字段**：precheck 决策回写后 transform_detail 会标"类型转换"——照常写 field_logic（转换口径），**改 ETL 不改 DDL**。字符收窄守卫=按目标类型长度语义截取（varchar/varchar2 字节→`SUBSTRB(x,1,n)`；nvarchar 系字符→`SUBSTR(x,1,n)`；尾部丢失闸口①披露）。守卫防脏值炸批**不兜数值值域**——精度/长度装不下正常源数据是模型问题（precheck 拦），禁写"超长置空"除非 SE 闸口①拍板（源输入定窄退 BA——菜单见 new-pipe 1b）
- **聚合类字段必拆解**（拼接/汇总，"对同一 X 的多个值拼接/合计"类描述），表达式+括号说明至少答四件事：
  - **收敛时机**：一对多侧**先预聚合收敛、再回连主表**（先 join 再聚合会让其他字段发散→主键重复）；多字段共用同一收敛（只拼接值不同）→ 声明共用同一子查询产出
  - **过滤**：聚合前提条件（如 del_flag='N'）
  - **去重**：组内值是否先 DISTINCT
  - **拼接序**：聚合函数必须带 ORDER BY 保产出确定性——**工程补全，可合理推理**（默认按拼接值排序，写明即可），业务对顺序有真实要求才问源端。（对照：开窗取哪条的分组/排序口径是业务语义，必须源端给——见第4层⓪）
- **check_field=引用确认器**（写加工口径时确认引用字段的存在/类型；第4层②类型兜底；用法：只给别名=紧凑全表[一行 6 个防截断]，`--like 关键词` 模糊找[如 --like date 找日期类]）——按需不是必经，评估层例行不走它（作业台已含存在性）。**查无给相近建议=找准确名的帮手；确认引用要精准，相近名不是替换依据**（字段精准原则见评估层）。引用 rs_input 完全未声明的**全新表**不用工具绕，正路=补 mapping（闸口①确认）
- 加工字段没写 design_logic 会被硬校验拦住（不允许占位继续跑）

### 产出 + 组装

- **先读模板再写**：`assets/design-decisions-template.yaml` 是格式的唯一源——落盘前必须先读到它（read 被拒走 Get-Content fallback），**禁止凭印象手写 yaml 结构**（编的格式必然被 assemble_ts 拦，反复空转）。读不到模板=停+上报，不是自己编。
- 写 `design_decisions.yaml`（骨架按模板）
- 调 `assemble_ts.py` 组装出 ts.json + ts.md
- 校验失败 → 看报错的 `[第X层]` 标识定位到对应 playbook 修正后重跑；warn 不是你的行动项（闸口①人审材料）——不为消 warn 改设计

### 路由段：什么时候读哪个 playbook

| 触发条件 | 读哪个 |
|---------|--------|
| RS 标了增量（L07 增量识别方式 ≠ "不涉及"）| `references/incremental-playbook.md` |
| 第2层评估复杂度 / 要拆步骤 / 要建中间表 | `references/complexity-playbook.md` |
| 累积共建场景（多规则写同一中间表）| `references/incremental-playbook.md` §三/§四 |
| 分布键/分区/依赖类型 | `references/design-guide.md`（每次都薄，直接读）|
| 组装目标参照（ts.json/ts.md 结构）| `assets/ts-template.json` / `ts-template.md` |
| 理解 RS 输入格式 | `references/rs-input-format.md` |

> 简单全量单表资产：五层很快走完，第2层不拆中间表（走 full 单规则），第3层全量，只读 design-guide.md 就够。

### DQ 已迁出（2026-09-14）

DQ 与你无关：独立岗位 dws-dq-producer 在 assemble_ts 后并行完成（不读你的 design_logic）。view 无 dq 段、模板无 dq_rules——你只管加工主线。

---

## 3. 数据流图

在 design_decisions 的 `data_flow` 定义 dependencies + schedule_groups（节点=规则，多场景并行=schedule_groups）。

---


## 6. 交卷自检

各层"产出+闭合条件"就是自检清单（上文已逐层列出，不在此重复）——评估层产物=`--eval` 结果（随回复上报），其后各层过了就调 assemble_ts：报错带 `[第X层]` 导航按报错修（fail-loud 是预期工作流，不预防性读工具源码对齐校验）；warn 不是你的行动项（闸口①人审材料），不为消 warn 改设计。
