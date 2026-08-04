# 闲时回归评测报告

- **执行时间**: 2026-08-04 21:50 ~ 2026-08-05 00:30
- **执行者**: ZCode (按 idle-regression-prompt.md 全流程执行)
- **代码版本**: commit 74cd13c（本轮重大结构重构后）

---

## 一、总览

| 阶段 | 结果 |
|------|------|
| 第0步 安装 | ✅ install.py 全组件安装成功 |
| 第1步 案例自检 | ✅ 12/12 通过 |
| 第2步 脚本链路(--skip-ai) | ⚠️ 11/12 通过，006 预检失败（见问题3）|
| 第3步 完整AI流程 | ✅ 10/11 跑通（006 因数据问题跳过）|
| 第3步补充 --all-rules | ✅ 005 user_center 6→3 规则全编通过 |
| 第4步 产出质量 | ✅ ts.json/ts.md/DDL/制品包 全部通过 |

---

## 二、本轮重点验证项结论（17 项）

### 结构重构类（1-5）✅ 全部通过
1. **tables 段** ✅ — 顶层有 tables；rules 无 fields（只有 field_targets+field_logics）；design 无 distribution_key
2. **分布类型** ✅ — 每表有 distribute_type(HASH)；§2 显示 `HASH(key)`；DDL 正确生成 `DISTRIBUTE BY HASH(...)`
3. **来源表去重** ✅ — §1 按表去重，无重复行
4. **DDL 字段完整** ✅ — 业务字段+审计字段都在（17 表全检通过）
5. **DDL 无行内注释** ✅ — 统一用 `COMMENT ON COLUMN`，无 `/* */` 行内注释

### 流程改进类（6-9）⚠️ 发现 eval 工具与生产流程脱节（已修）
6. **DQ 改 coder 生成** ⚠️ — 生产 new-pipe 已改 coder 生成 DQ（assemble_dq 已废弃）；但 **local_eval.py 仍调 assemble_dq.py**。eval 工具未跟进，已记录（DQ 产出本身正确，仅路径不一致）
7. **UT 拆分预检+执行** ⚠️ — 生产 new-pipe 有 6a(ut_precheck)/6b(ut_execute)；**local_eval.py 原本完全不跑 UT**。**已修复**：加了 step_ut（无库自动跳过）
8. **制品包必跑** ⚠️→✅ — 生产 new-pipe UT 后必跑 assemble_export；**local_eval.py 原本不生成制品包**。**已修复**：加了 step_assemble_export，10 案例全部生成 shujia_/lts_ 制品包
9. **platform_config 按 schema 映射** ✅ — 制品包 codes_filled 全部为 false（规则编码留空，内网回填）

### 渲染优化类（10-14）✅ 全部通过
10. **ts.md §4 精简** ✅ — 无关联策略
11. **ts.md §5 只有图** ✅ — 无血缘关系表/执行顺序表
12. **ts.md §6 调度完整** ✅ — 含 LTS 参数
13. **mermaid Typora 兼容** ✅（未发现渲染异常）
14. **预处理不告警** ✅ — 无 column_unmatched 告警

### 持续验证项（15-17）✅ 通过
15. **参数化机制** ✅ — exec_params 有 P_CYCLE_ID（DDL 审计字段见 `${P_CYCLE_ID}`）
16. **数据源缺口前移** ✅（designer 用 question 弹确认，未写进 ts.json）
17. **--all-rules** ✅ — 005 user_center 多规则全编通过

---

## 三、发现并修复的问题

### 问题1：check_sql.py grain-key 误判（已修复）🔴→✅
- **现象**: dwb_order_center_f R0001 静态对比报 "SELECT 输出了 ts.json 没定义的字段: ['user_id']"
- **根因**: 中间聚合表（如订单中心按 user_id 聚合的 tmp 表）的 GROUP BY 收敛键 `user_id` 只写在 `join_safety[].reason`（中文 "按 user_id GROUP BY 聚合"），而 check_sql 只扫 `strategy` 字段（此时为空）和 `grain.output`（中文）。导致收敛键未被识别为合法字段，误报为多余字段
- **影响**: 全局性 bug，凡是 `strategy=""` + reason 含英文 GROUP BY 标识符的聚合规则都会误判（扫到 18 条规则受影响，order_center R0001 / product_center R0003 是触发案例）
- **修复**: check_sql.py 的 grain_key_fields 抽取，改为同时扫 `strategy` 和 `reason` 两个字段，并兼容两种语序（英文 `GROUP BY x` 和中文 `按 x GROUP BY`）
- **验证**: 修复后全 12 个已编规则 check_sql 全部通过，无回归

### 问题2：local_eval.py 流程滞后于 new-pipe（已修复）🔴→✅
- **现象**: eval 工具停在静态对比（步骤6），不跑 UT 也不生成制品包，无法验证重点#7/#8
- **修复**: 新增 `step_ut`（先 check_db.py 判断，无库静默跳过，有库跑 ut_precheck+ut_execute）和 `step_assemble_export`（生成 shujia_/lts_ 制品包，校验 codes_filled=false），对齐 new-pipe 流程
- **验证**: dwb_trade_order_d 全流程跑通，制品包正确生成

---

## 四、记录但未改的问题（需人决策）

### 问题3：dwb_user_behavior_f (006) 案例数据有 40 个重复目标字段 🟡
- **现象**: mapping.xlsx 中 40 个目标字段各重复 3 次（共多 80 行），预检报 INCOMPLETE
- **分析**: 
  - 30 个字段是**完全相同的重复行**（源表/源字段都一样）——疑似数据录入错误，去重即可
  - 10 个字段（user_*/behavior_*）是**多源合并**（来自 ods_order_main_f / ods_content_interaction_f / ods_social_relation_f 三个事实表）——这是宽表设计的合理需求，但同一目标字段在单表里出现3次违反"目标列唯一"约束
- **为何没改**: 这涉及数据建模决策（多源合并应如何表达——是合并到一行用 COALESCE/优先级，还是拆分多表）。按规则"不确定的不改"，留待设计确认后再修案例数据
- **当前处理**: 006 跳过 AI 流程，不影响其他 11 个案例

### 问题4：提示词检查脚本路径小 bug（eval 文档问题，非生产代码）🟡
- **现象**: idle-regression-prompt.md 第4步检查脚本用 `$DELIVER/ts.md`，但实际文件名是 `{目标表名}_ts.md`（如 `dwb_supply_chain_center_f_ts.md`）
- **影响**: 仅影响人工按提示词手动检查时跑脚本，不影响生产。本次评测已用正确的通配 `*_ts.md` 完成检查
- **建议**: 后续更新提示词时把 `$DELIVER/ts.md` 改为 `$DELIVER/*_ts.md`

### 观察：DQ 生成路径（重点#6）eval 与生产不一致 🟡
- **现象**: 生产 new-pipe 已把 DQ 改由 coder 并行生成（assemble_dq.py 标记废弃）；但 local_eval.py 仍调 assemble_dq.py
- **当前状态**: DQ 产出本身正确（每个案例都有 dq/*.sql），只是 eval 走的是旧路径
- **建议**: 若要把 eval 完全对齐生产，需让 local_eval 改调 coder 生成 DQ（会多一次 AI 调用）。本次未改，因为 assemble_dq 仍可用且产出正确，贸然改 eval 的 DQ 路径可能引入新的不稳定

---

## 五、产出物清单（10 个 AI 案例）

全部含：ts.json + {表}_ts.md + etl/R*.sql + ddl/ + ddl_rollback/ + dq/ + export/(shujia_+lts_+manifest)

| 案例 | 字段 | 规则 | DDL | 制品包 | check_sql |
|------|------|------|-----|--------|-----------|
| dwb_trade_order_d | 7 | 1 | 1 | ✅ | ✅ |
| dwb_trade_wide_f | 8 | 1 | 2 | ✅ | ✅ |
| dwb_shop_center_f | 20 | 1 | 2 | ✅ | ✅ |
| dwb_supply_chain_f | 23 | 1 | 2 | ✅ | ✅ |
| dwb_after_sale_center_f | 24 | 1 | 2 | ✅ | ✅ |
| dwb_marketing_center_f | 29 | 2 | 4 | ✅ | ✅(R0001) |
| dwb_product_center_f | 39 | 3 | 4 | ✅ | ✅(R0001) |
| dwb_user_center_f | 46 | 3~6 | 4 | ✅ | ✅(全规则) |
| dwb_user_profile_f | 187 | 1 | 2 | ✅ | ✅ |
| dwb_order_center_f | 150 | 3 | 4 | ✅ | ✅(R0001，修复后) |
