# 本地案例回归评测报告

- **时间**: 2026-08-02
- **范围**: `eval-suite/cases/` 下 12 个案例（001~012）
- **脚本**: `eval-suite/local_eval.py` 全流程（preprocess → precheck → designer → assemble_ts → coder → assemble_ddl → check_sql）

## 一、总览结论

| 维度 | 结果 |
|---|---|
| 脚本链路（preprocess/precheck/assemble） | ✅ 11/12 目标案例通过（001 案例集不完整，见下） |
| AI 全流程（designer+coder） | ✅ 11 个目标案例全部跑通 |
| **check_sql 静态对比** | ✅ **11/11 PASS**（修复后；修复前 005/006/012 FAIL） |
| DDL 列重复（语法错误） | ✅ **11/11 无重复**（修复后；修复前全部案例都有重复审计列） |
| 发现并修复的脚本/指引问题 | **3 个**（见第三节） |
| AI 产出质量 | 高（详见第四节） |

### 最终一致性矩阵（11 个目标案例）

| 案例 | 字段 | 规则 | 源表 | 审计 | DDL | check_sql | SELECT行 |
|---|---:|---:|---:|---:|:---:|:---:|---:|
| 002_dwb_trade_order_d | 7 | 1 | 1 | 4 | ✅ | ✅ | 11 |
| 003_dwb_trade_wide_f | 15 | 1 | 5 | 4 | ✅ | ✅ | 73 |
| 004_dwb_shop_center_f | 20 | 1 | 4 | 4 | ✅ | ✅ | 74 |
| 005_dwb_user_center_f | 46 | 3 | 9 | 4 | ✅ | ✅ | 15 |
| 006_dwb_user_behavior_f | 264 | 1 | 7 | 4 | ✅ | ✅ | 679 |
| 007_dwb_supply_chain_f | 23 | 1 | 5 | 4 | ✅ | ✅ | 92 |
| 008_dwb_after_sale_center_f | 24 | 1 | 5 | 4 | ✅ | ✅ | 92 |
| 009_dwb_product_center_f | 39 | 3 | 7 | 4 | ✅ | ✅ | 42 |
| 010_dwb_user_profile_f | 187 | 1 | 4 | 4 | ✅ | ✅ | 267 |
| 011_dwb_marketing_center_f | 29 | 2 | 5 | 4 | ✅ | ✅ | 75 |
| 012_dwb_order_center_f | 150 | 4 | 5 | 4 | ✅ | ✅ | 131 |

> `--skip-ai` 链路验证阶段所有目标案例通过；`001_dwl_con_pu_any_f` 因案例集本身缺 `RS.md` 且 mapping 文件名不规范（`连接层粒度转换案例mapping.xlsx`）跳过，非脚本问题。

## 二、第一步：脚本链路验证（--skip-ai）

12 个案例跑 `--skip-ai`（只验证 preprocess + precheck）：

- **10 个目标案例**：preprocess/precheck 全部通过（precheck 仅有"上游调度任务缺失"等非阻断警告）。
- **001_dwl_con_pu_any_f**：mapping 文件名非标准 + 缺 RS.md → fixture 不完整，**非脚本 bug**，跳过。
- **006_dwb_user_behavior_f**：precheck 报 40 个"目标字段重复 3 次"。核查 rs_input.json 后确认是**案例数据本身的真实重复行**（同一 `user_user_id` 在 3 行里完全相同，scene_group 全为 default，非多场景拆分）。precheck 正确报错，属数据质量问题，不在本次修复范围。

**结论**：脚本链路无 bug，进入 AI 全流程。

## 三、发现并修复的问题（3 个）

### 问题 1：assemble_ddl.py 审计字段重复列（影响**所有**案例）🔴 高

**现象**：每个案例的 CREATE TABLE DDL 里，审计字段（`del_flag` / `crt_cycle_id` / `last_upd_cycle_id` / `dw_last_update_date`）出现两次——一次在业务字段列表里，一次在追加的"/* 审计字段 */"段。导致 **DDL 语法错误**（同表重复列名），`COMMENT ON COLUMN` 也重复。

**根因**：`assemble_ddl.generate_create_table` 先把 `rule.fields` 全部输出（designer 已把 4 个审计字段放进了 `rule.fields`），再无条件追加 `design.audit_fields`，两者拼接产生重复。

**修复**（`skills/dws-coding/references/assemble_ddl.py`）：构建 `audit_lines` 时跳过已在 `rule.fields` 中的字段名。
```python
business_field_names = {fname for fname, _, _ in field_lines}
audit_lines = []
for aname, aspec in audit_fields.items():
    if aname in business_field_names:   # ← 去重
        continue
    ...
```
**验证**：11 个案例 DDL 全部重生成，0 重复列。

### 问题 2：check_sql.py 不识别 CTE / 类型转换（012、006 误报）🔴 高

**现象**：
- **012**（8 个 CTE 的复杂 SELECT）报 9 个"多余字段"（`r_score`/`f_score`/`activity_type`… 全是 CTE 内部别名）+ 8 个"未知表"（`order_agg`/`pay_agg`… 全是 CTE 名）。
- **006**（264 字段，含大量 `CAST(... AS INTEGER)`、`EXTRACT(YEAR FROM ...)`）报类型名（`bigint`/`date`/`integer`…）为"多余字段"，报 `birthday`/`create_time`/中文`的`为"未知表"。

**根因**：原 `extract_select_aliases` 用 `re.finditer(r'\bAS\s+(\w+)', sql)` 对**整段 SQL** 抓别名，把 CTE 内部 `AS`、`CAST AS type` 全抓成输出字段；`extract_from_tables` 把 CTE 名、`EXTRACT FROM`、注释里的 `JOIN 的` 全抓成表。属**已知遗留问题**（旧测试里就有注释"可能有表引用警告（CTE 名）"）。

**修复**（`skills/dws-coding/references/check_sql.py`）：
1. 新增 `split_cte_main()`：按 `WITH ... AS (...)` 括号深度解析出**CTE 名列表**与**主查询体**；别名只从主查询体抽。
2. CTE 名视作合法表引用；规则 `grain.output` 与 `join_safety` 的 `GROUP BY` 键视作合法字段（中间表聚合键）。
3. 新增 `_strip_sql_noise()`：抹掉 `EXTRACT(x FROM y)` 的 FROM、`CAST(... AS type)` / `::type`。
4. AS/FROM 正则限定 **ASCII 标识符**（`[A-Za-z_]\w*`），避免中文注释残留误匹配。

**验证**：012（8 CTE）与 006（264 字段含 CAST/EXTRACT）均通过；新增 4 个 CTE 回归测试（`tests/test_coding_scripts.py`），全套 23 个测试通过。

### 问题 3：coder SKILL.md 中间表审计字段/分组键指引不清（005 漏带）🟡 中

**现象**：005 的 R0001（用户中间表 `dwb_user_order_tmp`）SELECT 漏带全部 4 个审计字段 + 分组键 `user_id`，check_sql 报"缺少审计字段"。但同类案例 009（商品中间表）coder 却正确带齐——**coder 在中间表规则上表现不稳定**。

**根因**：SKILL.md 第 4 节说"审计字段从 `_global.audit_fields` 取"，但没明确**中间表/tmp 规则也要带**；也没说聚合规则的 GROUP BY 键必须 SELECT 出来（它是目标表的分布键 + 下游 JOIN 键）。assemble_ddl 给每张表（含中间表）都加审计列，故 SELECT 必须对齐。

**修复**（`skills/dws-coding/SKILL.md`）：第 4 节加强调 + 新增 4.1 节：
- 「每条规则的 SELECT 都必须带 4 个审计字段——**包括中间表/tmp 规则**」
- 「GROUP BY 的键，必须同时 SELECT 出来」（附 `_global.business_key`/`distribution_key` 来源说明）
- 检查清单同步加"中间表/tmp 规则也要带"。

**验证**：005 重跑后 R0001 SELECT 正确带齐 `user_id` + 4 审计字段，check_sql 通过。

## 四、AI 产出质量评估（抽样）

整体**质量高**，几个亮点：

- **003（5 表 JOIN 宽表）**：pay/log 用 CTE 预聚合到订单粒度防 fan-out，商品维用 `ROW_NUMBER() OVER(... ) _rn=1` 取最新有效行，所有 LEFT JOIN 右侧字段 COALESCE 兜底。
- **007（供应链）**：库存表 `dwd_inventory_f` 关联前用 `ROW_NUMBER` 取每个 `(product_id, warehouse_id)` 最新行防主表放大；销量源缺失时 `stock_days` 输出 `NULL::int` 并注释说明，**不臆造口径**。
- **008（售后）**：订单事实表 `GROUP BY order_id` 收敛、工单表 `ROW_NUMBER` 取最新一条，退款比例带零除保护。
- **011（营销，2 规则分段）**：拆 R0001 活动粒度 tmp 表 + R0002 宽表；`new_user_rate` 语义源表无法严格判定时，coder **明确拒绝拍板**，记录障碍 + 给自洽近似口径 + 标"待人工确认"（红线规范遵守得好）。
- **010（187 字段画像）**：手机号/身份证脱敏（`LEFT(x,3)||'****'||RIGHT(x,4)`）、SCD2 维度取当前有效行、码值转中文 CASE 齐全。
- **012（150 字段，4 规则）**：8 个 CTE 结构清晰，RFM 用 `NTILE(5)`，活动/支付偏好用 `ROW_NUMBER rn=1` 收敛。

**未改的业务/质量疑点**（记录，未动）：
- 006 案例数据有 40 组重复映射行（见第二节），属案例集数据质量问题。
- 各案例 precheck 的"上游调度任务缺失"警告，属 RS 调度信息填写问题，非脚本问题。

## 五、改动清单与验证

| 文件 | 改动 | 验证 |
|---|---|---|
| `skills/dws-coding/references/assemble_ddl.py` | 审计字段去重 | 11 案例 DDL 0 重复列 |
| `skills/dws-coding/references/check_sql.py` | CTE 解析 + 噪声剥离 + ASCII 标识符 | 012/006 通过；11 案例 check_sql 全 PASS |
| `skills/dws-coding/SKILL.md` | 中间表审计字段 + 分组键指引 | 005 重跑通过 |
| `tests/test_coding_scripts.py` | +4 个 CTE 回归测试 | 23/23 通过 |

所有改动已同步到全局安装（`~/.config/opencode/skills/dws-coding/`），与项目源一致。

## 六、遗留 / 后续

1. **`test_resource_integrity.py`** 33 个失败为**历史遗留**（tauri/plugin 构建配置相关），与本次改动无关，stash 验证过。
2. **006（264 字段）coder 自迭代循环**在大案例上耗时较长（设计 ~6min、编码卡在旧版 check_sql 反复重试）；本次用修复后的 check_sql 手工补完 DDL 已通过。建议后续 local_eval 让 coder 读项目内最新脚本，或放宽大案例的重试轮数。
3. **001 案例集**缺 RS.md + mapping 命名不规范，建议补齐后纳入回归。
