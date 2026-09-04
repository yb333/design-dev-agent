---
status: active
last_reviewed: 2026-09-04
depends_on: [../specs/opt/00-总纲与范围.md]
edition: 实现版 v4（2026-09-04 本质重审重写：三条不变式/围栏四层矩阵/刀与守护分级/
工具同构矩阵/档案=本源集合——设计过程版见 git 历史与 specs/opt 系列）
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
| **回归零差异** | 老列行为与基线完全一致 | 双跑对比 + 行数对账 |

**每个工具进体系必须回答：守哪条不变式、边界在哪、不守什么。** 检查范围只限新增子集（存量不预检——围栏和双跑兜底）；UT 的双重使命 = 测需求（新列正确性）+ 测影响（回归零差异）。

## 三、刀与守护分级（架构一等概念，2026-09-04 定调）

**"刀"（change type）= 一个声明 schema + 一个冻结/自由矩阵。** 围栏引擎不预设刀——加刀 = 加 `SUPPORTED_CHANGE_TYPES` 枚举 + 加一个矩阵函数（fence_check 现状形态即契约），引擎主流程不动。守护强度跟变更的**可声明性**挂钩，总量守恒、形态随刀配置：

| 刀 | 可声明性 | 围栏形态 | 输出对比形态 |
|---|---|---|---|
| **add_field**（已实现） | 完全可声明 | **满围栏**：四层恰好等于 | 冻结列零差异 + 行数相等 + 新列人审 |
| modify_field（未来） | 变更点可声明、SQL 形态开放 | **定位围栏**：只有声明字段的投影/血缘可变 | 差异只许落在声明字段，语义变化人审 |
| 重设计/性能优化（未来） | 不可声明 | **围栏退位**：只冻 tables/load_mode | **全列零差异 + 行数相等**——行为等价是唯一守护 |

声明性越弱，围栏越弱、输出对比越强（双跑引擎复用，改比对面配置）。性能优化场景"围栏做不了"不是缺陷，是守护换了形态。

## 四、围栏四层矩阵（恰好等于的展开）

| 层 | 越界方向（多了/动了） | 漏改方向（少了） | 载体 |
|---|---|---|---|
| L1 ts | diff 每项被声明罩住 | 声明每项有落点 | fence_check |
| L2 SQL | 老列 AST 结构等价（**等价改写也拦**——笨标准不做语义推断）+ JOIN/WHERE/GROUP BY/CTE 冻结 | 声明新列必须出现 | sql_fence_check（结果落盘 `_internal/sql_fence_result.json`） |
| L3 DDL | 全量字段增量恰好=声明（ts tables diff）+ ALTER 生成器只产 ADD | 同左 | assemble_ddl_opt 的 audit |
| L4 数据 | 双向 MINUS：冻结列零差异 + **行数对账**（裸 COUNT 相等——MINUS 集合语义看不见重复数，发散的行级硬信号） | 新列空值/全 NULL 信号 | ut_opt |

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

N 系校验适用性：新字段适用的等价物已补（N36→引用门禁 / N_JOIN2→键类型比对 / N5→design_logic 必填）；不适用的不跑（N_DQ* 第一刀无 DQ / N_INIT* 存量不补 / N14-N28 增量类——基线语义空位豁免，双跑兜底）。

## 六、目录与档案（本源集合，2026-09-04 收缩）

**资产标识** = mapping 声明的目标表（铆定 I 视图；只存 F 的资产即 F 名——按人写的算）。

```
10_project_deliver/{appid}/{schema}/{资产=I名}/ddlc_design_dev/
├── archive/         ← ★资产档案（入 git，gitignore 白名单）：
│                       ts.json/ts.md/etl/{rule}.sql/dq//export//decisions.yaml
│                       （export=平台制品包：运行配置物化形态+opt patch 链底本——平台侧有
│                        ts 外的状态，非纯投影；DDL 不入档——tables 是 DDL 唯一源，
│                        全量 DDL 为 ts 可再生投影。演进史=git 提交历史，提交由人管理）
├── （new-pipe 平铺产出/交付现场——首优收档后 ts/etl/dq/export 移入档案，ddl 留现场）
└── opt/             ← 本次优化更新（每次开工重建；目录树开工即建=进度看板）
    ├── ts_v2.json / ts.md / etl/{rule_code}.sql（与档案同名=规则当前版）
    ├── ddl/（ALTER 变更单 + create_or_replace_view——I 视图镜像是语法结构决定的真交付物）
    ├── export/（patched/ + patch_notes.md）/ ut_report_opt.md
    └── _internal/（baseline_v1.json / baseline_view.md[三条入口路径全有：档案路径由
                    preprocess_opt 从 ts 渲染简化版] / exemptions.json / change_request.json
                    / design_decisions_opt.yaml / schema_cache.json / sql_fence_result.json
                    / type_risk_decision.yaml / join_type_decision.yaml / diagnose/）
```

**回归能力**：确认前档案零改动（工作产物只进 opt/），放弃 = 扔现场；确认后 advance 推进（覆盖），反悔 = git revert。数据库层回归（ALTER 已应用）不承诺，开发库重建。

## 七、流程详解（{ddlc}=ddlc_design_dev，{arc}={ddlc}/archive，{opt}={ddlc}/opt）

0. **入口**：check_env 探针（跨剧本引用 new-pipe）→ `preprocess --probe` 定位 → 建 opt/ 目录树 → 三段式查基线（`{arc}/ts.json` 有档直接用 / 无档有平铺 new-pipe 产出 → `archive_writer adopt` 首优收档 / 都没有 → baseline_v1.json 入料建档：`assemble_ts_baseline --archive-dir {arc} --internal-dir {opt}/_internal`，provenance 落 ts._baseline）。
1. **preprocess_opt**（`--mapping/--rs` 契约参数直传，分拣器已退役）：版本锚定 → 备注标记提取 → 校验（冲突/别名悬空/资产一致 I/F 镜像归一）→ change_request.json + baseline_view 补产。
1b. **precheck_opt**（只检新增子集）：命名规范 / 连库存在性+类型对账（以库为准回填）/ 类型风险决策（人三选，回写 fields『decision』）/ 值域探测 / 新来源 JOIN 键对账。PENDING → question → fill（shared）→ 重跑放行；返源端/改关联键 = 本轮终止。
2. **designer**（dws-design-opt skill）：读 baseline_view + change_request → 落位/新 JOIN safety/回刷 → design_decisions_opt.yaml → assemble_ts_opt 组装 ts_v2+ts.md（validate 含引用门禁 + 新 JOIN 键类型比对）。
3. **fence_check**（ts 级恰好等于）→ `gate_summary_opt` 产闸口材料（确定性产出）→ **闸口①'三问**（落位/回刷/建议追加；分场景模板，检出过问题必含"退 BA"一等选项）。
4. **coder 并行**（dws-coding-opt：底稿加列，落盘 {rule_code}.sql）→ pipe 跑 **sql_fence_check**（AST 等价 + 漏改拦，结果落盘）。
5. **assemble_ddl_opt**（ALTER 变更单 + I 视图重建 + ts diff 审计）→ check_db → **ut_opt**（围栏时效闸门 → ALTER → 每规则 EXPLAIN ANALYZE 两门槛 → 行数对账 + 双向 MINUS → INSERT → 新列空值检查）。失败分流表见 SKILL；对比 FAIL/行数漂移先跑 diagnose_fanout_opt 产证据再人定根因。
6. **artifact_patcher**（--source 首选 `{arc}/export/` 档案制品当前态[patch 链底本] → provenance → 问人）。
7. **闸口②'**（新列合理性/交付清单/资产健康）→ `archive_writer advance`（档案推进，DDL 不入档）→ 人拿交付物执行。

## 八、组件清单

**command**：`commands/opt-pipe.md`（薄壳）。**skills**：opt-pipe（剧本）、dws-design-opt / dws-coding-opt（薄，知识与工具路径引用 dws-design/dws-coding）。**agents**：两 agent 各加 opt skill 指针 + opt 目录写权限。

**脚本**：opt-pipe/scripts（preprocess_opt / precheck_opt / gate_summary_opt / fence_check / sql_fence+sql_fence_check / ut_opt / assemble_ddl_opt / assemble_ts_baseline / baseline_contract / artifact_patcher / archive_writer / diagnose_fanout_opt + schemas/）；dws-design/scripts（assemble_ts_opt）；design-dev-shared/scripts（检测原语 risk_checks / schema_cache / explain_check + fill 两脚本——与 new-pipe 共用，搬体留名下沉）。

**契约**：baseline_v1（权威在 analyzer 仓 v1.1；本仓 vendor schema + 校验器）。

## 九、已知限制与预留

1. 回刷：backfill 仅记录意向，无脚本产出；实现时回刷 SQL 是第五围栏对象。2. `load_mode_pending` 三类 kind 待词表扩展。3. yml patch 丢注释。4. baseline 语义空位 by design（双跑兜底）。5. change.dq 预留未接。6. sync_to_team 对 deliver 深处 archive/ 的同步待内网验证。7. **UT 双重使命（测需求 + 测影响）的体系化构建**是独立议题（2026-09-04 记）——行数对账是第一刀，后续回归验证体系（如快照对比/统计对账）另议。8. UT 断言深度：MINUS+行数对账守护集合与多重集；列值分布漂移（同集合不同值频率）暂不覆盖。

## 文档地图

| 文档 | 角色 |
|------|------|
| 本文（v4） | 现状手册 + 不变式推导基准 |
| specs/opt/00-08 | 设计定稿过程（归档参考） |
| specs/opt/09+10 | baseline_v1 契约（消费侧/逆向侧） |
| specs/opt/11-测试指引 | 端到端测试入口（命令以 opt-pipe SKILL 为准） |
