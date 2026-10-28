---
status: active
last_reviewed: 2026-10-23
depends_on: [../specs/opt/00-总纲与范围.md]
edition: 实现版 v5.1（2026-10-27 §十一逆向 v2 方向定稿：契约=最终形态[ts 草稿]/装配北移/恢复声明进本体/档案幂等——方向落册待实施，v1 现状仍以 §十为准；此前 v5 两定稿：①统一 UT 双跑退役②§十 designer 认知链）
---

# 优化场景架构与操作手册（opt，实现版）

> 本文是优化场景的**单一现状参考**。v4 的重写动机（2026-09-04）：内网实测暴露的
> fetch_all/baseline_view 等 bug 说明工具集曾是"对齐 new-pipe"堆出来的而非从不变式
> 推导——本文把推导链显式化，作为后续演进的基准。设计推演过程在 `docs/specs/opt/00-08`。

---

## 一、这是什么

存量资产之上的**精确变更交付**：外部或自建的 ETL 资产 + 变更需求 → 精确修改 → 回归验证 → 变更制品 → 档案推进。与新建场景（new-pipe）并列，共用 designer / coder 两个 agent 岗位与全部设计知识。

**三条红线落法**：围栏三段机器审计 = 重写不自主；闸口①'/②' + 输出对比人审 = 语义判断不自主；制品只生成 patch 副本不执行 = 推生产不自主。

## 二、三条不变式（一切工具的推导起点）

| 不变式 | 一句话 | 守护形态 |
|---|---|---|
| **存量零接触** | 存量的语义/结构/数据一个字节不许动 | 冻结层比对（围栏） |
| **恰好等于** | 变化集 ⊆ 声明集 且 声明集 ⊆ 变化集 | 双向判定（围栏 + 审计） |
| **回归零差异** | 老列行为与基线完全一致 | SQL 围栏 AST 等价（老列结构等价）+ UT 资产质检全集（2026-10-26 统一 UT：双跑对比退役） |

**每个工具进体系必须回答：守哪条不变式、边界在哪、不守什么。** 检查范围只限新增子集（存量不预检——围栏兜底）；UT = **资产质量门**（对着资产全集：行数/主键唯一/审计非空/merge 幂等——新建优化同一套，豁免已移除）。

## 三、变更类型与守护分级（架构一等概念，2026-09-04 定调；「刀」为历史俗称）

**变更类型（change type）= 一个声明 schema + 一个冻结/自由矩阵。** 围栏引擎不预设变更类型——新增类型 = 加 `SUPPORTED_CHANGE_TYPES` 枚举 + 加一个矩阵函数（fence_check 现状形态即契约），引擎主流程不动。守护强度跟变更的**可声明性**挂钩，总量守恒、形态随类型配置：

| 变更类型 | 可声明性 | 围栏形态 | 回归守护形态 |
|---|---|---|---|
| **add_field**（已实现） | 完全可声明 | **满围栏**：四层恰好等于 | SQL 围栏 AST 等价 + UT 资产质检全集 + 新列人审 |
| modify_field（已实现：类型修改/口径修改） | 变更点可声明、SQL 形态开放 | **定位围栏**：只有声明字段的投影/血缘/口径可变（cast 包裹/桶迁移） | 同上——差异只许落在声明字段，语义变化闸口①'人审 |
| 重设计/性能优化（未来） | 不可声明 | **围栏退位**：只冻 tables/load_mode | 行为等价是唯一守护（若做：输出对比引擎需重建——双跑已退役，2026-10-26） |

声明性越弱，围栏越弱、回归守护越依赖行为等价验证。性能优化场景"围栏做不了"不是缺陷，是守护换了形态。

## 四、围栏四层矩阵（恰好等于的展开）

| 层 | 越界方向（多了/动了） | 漏改方向（少了） | 载体 |
|---|---|---|---|
| L1 ts | diff 每项被声明罩住 | 声明每项有落点 | fence_check |
| L2 SQL | 老列 AST 结构等价（**等价改写也拦**——笨标准不做语义推断）+ JOIN/WHERE/GROUP BY/CTE 冻结 | 声明新列必须出现 | sql_fence_check（结果落盘 `_internal/sql_fence_result.json`） |
| L3 DDL | 全量字段增量恰好=声明（ts tables diff）+ ALTER 生成器只产 ADD | 同左 | assemble_ddl_opt 的 audit |
| L4 数据 | UT 资产质检全集（行数/主键唯一/审计非空——豁免移除：UT 是资产质量门不是 diff 门）+ merge 幂等第二遍 | 新列空值/新类型 NULL 抽查 | ut_opt（统一 UT 内核=shared run_ut） |

**执行序（回路铁律，已机器化）**：围栏永远在 UT 之前；SQL 晚于围栏结果 = ut_opt 拒跑（exit 2）。回刷实现时是第五个围栏对象（只许 UPDATE 新列）。

## 五、工具同构（与 new-pipe 的关系）

三层同构：**原语层**（检测算法——risk_checks/schema_cache/explain_check 已下沉 shared 两边共用）→ **协议层**（退出码 0过/1warn/2阻断/3环境归人、PENDING+fill+回写决策流）→ **语义层**（结论标签词典/报告骨架/证据样例/`[围栏]` 导航——内容跟场景、格式跟统一）。保留差异：检查范围（opt 只检增量）、opt 特有段（ALTER/双跑/新列空值）。

| 能力 | new-pipe | opt | 共享原语 |
|---|---|---|---|
| 预检 | precheck（全量） | precheck_opt（增量子集） | risk_checks + schema_cache |
| 类型/JOIN 风险决策 | 1b PENDING 流 | 1b 同款（回写 change_request『decision』） | 骨架/校验 + fill 两脚本 |
| 计划两门槛 | ut_precheck 内联 | ut_opt 内联 | explain_check |
| SQL 检查 | check_sql（对账） | sql_fence（AST 等价——更强，opt 特有） | sql_parse |
| 闸口材料 | gate_summary | gate_summary_opt | — |
| 发散定位 | diagnose_fanout | diagnose_fanout_opt（轻量：无声明对照——opt 新 JOIN 本来就是 designer 声明） | sql_parse/type_compat |

N 系校验适用性：新字段适用的等价物已补（N36→引用门禁 / N_JOIN2→键类型比对 / N5→design_logic 必填 / **断言三空硬拦——批2**）；不适用的不跑（N_DQ* 走 dq.json / N_INIT* 存量不补 / N14-N28 增量类——基线语义空位豁免，SQL 围栏+UT 资产质检兜底）。

## 六、目录与档案（本源集合，2026-09-04 收缩）

**资产标识** = mapping 声明的目标表（铆定 I 视图；只存 F 的资产即 F 名——按人写的算）。

10_project_deliver/{appid}/{schema}/{资产=I名}/ddlc_design_dev/
├── archive/        ← ★资产档案=可信基线（git 合入对象）：ts.json/ts.md/etl/{rule}.sql/dq/
│                      ddl/（完整可用资产形态——重建环境一目录全搞定，ts 落位同产保一致）/
│                      export/（制品包，patch 链底本）/decisions.yaml/MANIFEST.md（版本索引）
├── build/          ← 增量现场（本次变更产出；开工清场只留最新、不进 git——与 new-pipe 的
│                      {deliver} 同一目录同一语义：新建=特殊优化场景，其增量=全部产出）
└── archive_tmp/    ← 临时档案（档案副本起步；优化过程 ts/DDL/新 SQL/patched 落位于此=
                       进度态全量随时可用；最终确认后三步全量替换上位；中止留存=保存进度）
```

**回归能力**：确认前档案零改动（工作产物只进 build/ 与 archive_tmp/），放弃 = tmp 留存保存进度；确认后三步全量替换，反悔 = git revert。数据库层回归（ALTER 已应用）不承诺，开发库重建。

## 七、流程详解（{ddlc}=ddlc_design_dev，{arc}={ddlc}/archive，{opt}={ddlc}/opt）

0. **入口**：check_env 探针（跨剧本引用 new-pipe）→ `preprocess --probe` 定位 → 三段式查基线（opt_{version}/ 由步骤 1 自建）（`{arc}/ts.json` 有档直接用 / 无档有平铺 new-pipe 产出 → `archive_writer adopt` 首优收档 / 都没有 → baseline_v1.json 入料建档：`assemble_ts_baseline --archive-dir {arc} --internal-dir {opt}/_internal`，provenance 落 ts._baseline）。
1. **preprocess_opt**（`--mapping/--rs` 契约参数直传；`--opt-root`）：**现场就绪**（清场重建 build/ + cp archive→archive_tmp/）→ 版本锚定 → 备注标记提取 → 校验（冲突/别名悬空/资产一致 I/F 镜像归一）→ change_request.json + baseline_view 补产。
1b. **precheck_opt**（只检新增子集）：命名规范 / 连库存在性+类型对账（以库为准回填）/ 类型风险决策（人三选，回写 fields『decision』）/ 值域探测 / 新来源 JOIN 键对账。PENDING → question → fill（shared）→ 重跑放行；返源端/改关联键 = 本轮终止。
2. **designer**（dws-design-opt skill）：读 baseline_view + change_request → 落位/新 JOIN safety/回刷 → design_decisions_opt.yaml → assemble_ts_opt 组装 **{arc_tmp}/ts.json+ts.md**（全量态直产临时档案；validate 含引用门禁 + 新 JOIN 键类型比对）→ `assemble_ddl --ts {arc_tmp}/ts.json` DDL 同产落位。
3. **fence_check**（ts 级恰好等于）→ `gate_summary_opt` 产闸口材料（确定性产出）→ **闸口①'三问**（落位/回刷/建议追加；分场景模板，检出过问题必含"退 BA"一等选项）。
4. **coder 并行**（dws-coding-opt：底稿加列，落盘 build/etl/{rule_code}.sql）→ pipe 跑 **sql_fence_check**（AST 等价 + 漏改拦，结果落盘）→ 围栏过 → 新 SQL cp 进 {arc_tmp}/etl/（进度态全量）。
5. **assemble_ddl_opt**（ALTER 变更单 + I 视图重建 + ts diff 审计）→ check_db → **ut_opt**（统一 UT 编排壳：围栏时效闸门 → ALTER 逐句判定 → 每规则 EXPLAIN ANALYZE 两门槛 → 写路径 execute_write_path[merge 拼真 MERGE+幂等第二遍] → UT 资产质检全集 → 新列/新类型抽查 → DQ 段）。失败分流表见 SKILL；数据质量 FAIL 先跑 diagnose_fanout_opt 产证据再人定根因。
6. **artifact_patcher**（--source 首选 `{arc}/export/` 档案制品当前态[patch 链底本] → provenance → 问人）。
7. **闸口②'**（新列合理性/交付清单/资产健康）→ `archive_writer advance`（**三步全量替换**：archive_tmp 整体上位+MANIFEST 追加）→ 人拿交付物执行。

## 八、组件清单

**command**：`commands/opt-pipe.md`（薄壳）。**skills**：opt-pipe（剧本）、dws-design-opt / dws-coding-opt（薄，知识与工具路径引用 dws-design/dws-coding）。**agents**：两 agent 各加 opt skill 指针 + opt 目录写权限。

**脚本**：opt-pipe/scripts（preprocess_opt / precheck_opt / gate_summary_opt / fence_check / sql_fence+sql_fence_check / ut_opt / assemble_ddl_opt / assemble_ts_baseline / baseline_contract / artifact_patcher / archive_writer / diagnose_fanout_opt + schemas/）；dws-design/scripts（assemble_ts_opt）；design-dev-shared/scripts（检测原语 risk_checks / schema_cache / explain_check + fill 两脚本——与 new-pipe 共用，搬体留名下沉）。

**契约**：baseline_v1（权威在 analyzer 仓 v1.1；本仓 vendor schema + 校验器）。

## 九、已知限制与预留

1. 回刷：backfill 仅记录意向，无脚本产出；实现时回刷 SQL 是第五围栏对象。2. `load_mode_pending` 三类 kind 待词表扩展。3. yml patch 丢注释。4. baseline 语义空位 by design（SQL 围栏+UT 资产质检兜底；增量路径踩到的空位按需点亮——§十）。5. change.dq 预留未接。6. sync_to_team 对 deliver 深处 archive/ 的同步待内网验证。7. **UT 统一已落地**（2026-10-26：双跑退役，优化与新建同一套资产质量门——UT 双重使命议题关闭）。8. 列值分布漂移（同集合不同值频率）暂不覆盖——SQL 围栏 AST 等价+口径人审兜底。9. **C 类全新结构（新增规则/新中间表）= 当前变更类型边界**：存量规则不够用需全新结构时不支持（opt coder 以 baseline SQL 为底稿加列、围栏以 placed_rules 为边界无"新增规则"许可维度）——真出现时按 delta 词汇扩展（new_rules），不为假设场景预建。

## 十、designer 认知链与输入面（2026-10-23 定稿——五轮架构讨论收敛）

> 〔2026-10-27 补注：本节描述 v1 现状。§十一 v2 方向已定稿——「facts 中间层」「装配在我方（assemble_ts_baseline 解析）」将被取代（装配北移逆向、契约=最终形态）；view 消费时投影/输入面纪律/territory 禁读等结论不受影响、原样继承。〕

### 10.1 三层模型：材料 / 判断 / 装配

| | 材料（确定性，脚本域） | 判断（designer 域） | 装配（确定性，脚本域） |
|---|---|---|---|
| 新建 | rs_input（人话抽取） | **全量**判断 | 材料＋判断 → ts |
| 优化 | **baseline ts（已装配的冻结结构）**+ change_request（增量人话） | **增量**判断 | 冻结结构＋增量判断 → ts_v2（全量态） |

设计层的动作（翻译/路径/断言）、纪律（有据/歧义上报）、门禁（N36/N38）两边一字不差；装配方式不同只因**材料形态不同**（opt 的材料已是装配产物，装配自然从"合成"变"合并"）。

### 10.2 两链分离，在 merge 汇合

- **权威链锚 ts**：制品→ts_baseline（逆向=同构映射，结构对结构）→merge→ts_v2。ts 是已交付记录的完整快照（含装配产物：三桶/审计/tasks/init），不是可再生产物（同"ts 不是制品再生源"下推一层：交付后的 decisions 也不是 ts 的再生源）。制品→decisions→ts 的"穿语义层往返"被否决——判断位填不了（校验契约分叉）、装配器演进漂移、authorship 混写。
- **认知链用 decisions 语言**：ts→baseline_view（decisions 语言投影）→designer→delta decisions（decisions 词汇）→merge 时翻译成结构变更。**"由 designer 还原存量设计"塌缩为脚本合并**：还原=誊写（归工具）+判断（无据=编造），designer 在环零价值纯风险。

**产物完整·判断增量**：ts_v2 全资产覆盖（完整性由合并保证）；判断的 authorship 分属时点——存量判断冻结在档案（adopt 档有值=真意图随档可见）或诚实空位（逆向档），本次判断只写 delta。优化 designer = **变更的作者 + 存量的读者**。

### 10.3 输入面契约（territory 禁读）

输入面四件：baseline_view（decisions 语言地图：锚点/规则拓扑[源/JOIN·safety/读中间表]/别名对照[SQL 实际别名=落笔权威]/语义空位▢）+ change_request（增量料：变更行/新字段/modify 含 baseline 内联参考/placement_hints 落位预判/eval_worksheet 工作单）+ 模板 + playbook。**禁读**：archive/ts.json、archive/etl/*.sql、全量 mapping、全量 RS（与新建"rs_input.json 不 Read"同构）。

**实测账本**（eval-suite 真实语料+148 字段合成场景）：守纪律输入 ≈13K token（常驻件 9K + 料 4K），**与资产规模基本解耦**；128K 压缩根因=territory 泄漏（读 ts 25-100KB/SQL 3-15K×规则数/全量 mapping 132KB），非输入天然大。确定性判断位预计算（别名对照/落位预判）是禁读的配套——不是压缩技巧。

### 10.4 断言对齐新建（先取证后断言·maker-checker 闭环）

与新建"评估层 --eval+闸口① diagnose --all"同构：①取证——eval_context.json 切片（最小 rs_input 形态只含新来源表，探针引擎零改动）+工作单预填，实测数字直贴 join_safety.reason；②组装器断言三空硬拦（strategy/join_key_unique/reason）；③闸口①' `diagnose_fanout_opt --placed`——**按需点亮**：只测增量血缘路径规则（新字段落位∪中间表产出∪口径修改所在），其余存量冻结不测。逆向档错误风险由此从信任问题变实证问题（audit 一致性审→断言对照→UT 三层各管一段）。

### 10.5 逆向的边界（认识论）

逆向能做到且做全：结构事实（规则/读写拓扑/写入类型/血缘/置信度 warnings）。做不到：语义依据（为什么这样设计/键唯一性/口径理解/business_key 论证）——制品里物理没有，这是"语义空位"的存在理由而非逆向失败。**本领域事实从制品来不从设计文档来**（源码>二进制的软件直觉在此倒置）；语义只对增量建立，踩到哪个空位点亮哪个。〔2026-10-27 精化见 §11.3：制品记载的设计声明（调度/分布/写入/口径）属"恢复"非"解析"——恢复进本体，本节"做不到"收窄为依据/论证类。〕

## 十一、逆向 v2 方向定稿（2026-10-27 多轮收敛——方向与判据落册，实施排期见 11.5；实施前 v1 现状以 §十与实际代码为准）

### 11.1 框架判据

- **子模块框架**：面向本场景，逆向是我们的子模块——组织边界不进架构（逆向的多消费方[契约B=RS spec 重建]是它的内部事务）。契约方向=**最终形态**（可直接建档的 ts 草稿），不是生产方中间形态——**子模块跟随契约所有者**（ts 契约所有者=我方）。
- **v1 的 facts 中间层是历史路径依赖**：assemble_ts_baseline 内的解析/装配（kind 词典/桶装配/DDL 拆解）v2 北移逆向；建档不再含解析（理论上=审核+复制）。v1 实证支撑：facts 已带 is_distribute_key 而装配丢弃（信息丢失点恰在 v2 要砍的环节）；逆向产 view 的否决理由也在此——view 是消费时投影，渲染点全在我方时间线上（逆向只在首优出现一瞬）。

### 11.2 能力分界

| 能力 | 归属 | 依据 |
|---|---|---|
| 制品解析+装配（→ts 草稿+自检） | 逆向（子模块） | 解析知识内聚；建档零解析 |
| 审核（草稿→确认） | 我方 | 对账**我方输入域**（mapping 台账/资产/变更记录）——审核者必须持有对账的另一边 |
| 建档（守门+audit+copy+MANIFEST） | 我方 | 信任转换+档案动作；复制不含变换 |
| view 渲染 | 我方，消费点（preprocess_opt 每轮） | 消费时投影（I 视图类比）；单实现单时机（v1 的建档渲染退役） |

### 11.3 产物形态与 doctrine

- **ts 草稿 = ts 本体 + `_reverse` 审核材料段**（自检结论/warnings/五类交叉——下划线键=非资产语义，`_baseline` provenance 先例）。
- **恢复声明进本体（逆向的本职=恢复存量设计声明，不只是解析）**：制品记载的设计结果直接回填槽位——调度→meta.schedule、分布/分区/存储→tables、写入→load_mode/write_condition、口径表达式→桶。三层判据：**恢复**（制品显式记载的设计→回填本体；DQ 主键判重条件=显式的主键设计记录，可回填 business_key 带 provenance）/**推断不冒充声明**（MERGE ON 回填 write_condition，business_key 仅其强旁证不冒充）/**依据类留空**（join_safety 依据/粒度论证——制品物理没有）。
- **分布键≠业务主键**（单向蕴含：业务主键⇒好分布键[高基数防倾斜]；**不可逆**——分布键无唯一性语义，一键多行是常态；且第4层优先级 JOIN 字段在前，按维度键分布常见）。business_key 旁证强度：MERGE ON/DQ 主键条件=强；分布键=弱。〔SKILL 第4层"事实表=业务主键"表述待修——批0〕
- **档案幂等**：逆向+一轮优化后的档案与新建档同构（ts/etl/**ddl**/export/MANIFEST 全保留——DDL 原文随档：消费端权威归 ts.tables，原文=出生证明证据件）。
- **档案单文件自足**：view 从档案单文件可渲染（别名/拓扑/旁证/warnings 全在档；v1 的 asset_facts 随档演化为 `_reverse` 段并入草稿）。
- **工具服务模型**：草稿/档案本体=脚本域 territory；**模型唯一读面=view**（§10.3 输入面纪律原样继承——v2 产物变大只大在脚本域，模型面更薄）。

### 11.4 v1 过渡期已知缺陷（批0 顺手修，不等 v2）

distribution_key/table_props 回收（facts 已带 is_distribute_key，v1 装配丢弃+gap 错定性"语义空位：物理设计决策"——物理事实被当语义判断扔）。

### 11.5 实施排期（2026-10-27 批2 契约定稿后更新）

批0 v1 顺手修 ✅（4ae0a9f）→ 批1 体检报告 ✅（d14d50c）→ **批2 v2 契约定稿 ✅**（ts_draft_v2.schema.json 权威 schema+`_reverse` 定形+调度映射表——**逆向侧可即刻按 12 章 v4 动工，不待案例**；案例校准的是 v1 运行体验与 v2 联调，不是契约形态）→ 批3 双仓实施（逆向装配实现+我方切换）→ 批4 v1 退役时间表。

**批3 消费侧切换设计要点**（预设计，实施时展开）：audit_ingest 消费草稿（对账输入域不变，读 ts 形态字段）；assemble_ts_baseline 瘦身=守门+audit+copy+MANIFEST（解析装配整体退役）；view 渲染归一（别名对照改 ts.joins/source_tables 直读——SQL 重解析仅作 legacy v1 档兜底；建档渲染退役，preprocess_opt 单渲染点）；preprocess_opt/fence/UT 对 v1 档 v2 草稿双支持（按产物自描述版本路由）。

## 文档地图

| 文档 | 角色 |
|------|------|
| 本文（v5） | 现状手册 + 不变式推导基准（§十=designer 认知链定稿） |
| specs/opt/00-08 | 设计定稿过程（归档参考） |
| specs/opt/09+10 | baseline_v1 契约（消费侧/逆向侧） |
| specs/opt/11-测试指引 | 端到端测试入口（命令以 opt-pipe SKILL 为准） |
