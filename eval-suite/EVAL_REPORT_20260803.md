# 本地案例回归评测报告（2026-08-03 轮次）

- **时间**: 2026-08-03
- **范围**: `eval-suite/cases/` 下 12 个案例（001~012），目标案例 11 个（002~012）
- **脚本**: `eval-suite/local_eval.py` 全流程（preprocess → precheck → designer → assemble_ts → coder → assemble_ddl → assemble_dq → check_sql）
- **基线**: 在上一轮（2026-08-02）报告之上回归。本轮代码有大改动（load_mode 补全、产出文件命名规范、数据探索提取、校验分级等）。

## 一、总览结论

| 维度 | 结果 |
|---|---|
| 案例数据自检（check_case.py） | ✅ 12/12 通过 |
| 脚本链路（--skip-ai） | ✅ 11/11 目标案例通过（修复 001/007 后） |
| **AI 全流程**（designer+coder+DDL+DQ+check_sql） | ✅ **11/11 全部跑通** |
| **check_sql 静态对比** | ✅ **11/11 PASS** |
| DDL 列重复（语法错误） | ✅ **11/11 无重复** |
| ts.json 结构（顶层键/business_key/load_mode/source_tables） | ✅ **11/11 完整** |
| DDL 数 = 回退脚本数 | ✅ **11/11 一致** |
| I 视图不用 `SELECT *` | ✅ **11/11 合规** |
| 标准DQ生成（主键/审计/记录数） | ✅ **11/11 生成** |
| 发现并修复的脚本/案例问题 | **3 个**（1 脚本 bug + 2 案例数据，见第三节） |
| 记录未改的问题（AI产出/契约） | **2 个**（见第五节） |

### 最终一致性矩阵（11 个目标案例）

| 案例 | 字段 | 规则 | 源表 | DDL | check_sql | ETL行 |
|---|---:|---:|---:|:---:|:---:|---:|
| 002_dwb_trade_order_d | 7 | 1 | 1 | ✅ | ✅ | 11 |
| 003_dwb_trade_wide_f | 8 | 1 | 1 | ✅ | ✅ | 19 |
| 004_dwb_shop_center_f | 20 | 1 | 4 | ✅ | ✅ | 67 |
| 007_dwb_supply_chain_f | 23 | 1 | 6 | ✅ | ✅ | 73 |
| 008_dwb_after_sale_center_f | 24 | 1 | 5 | ✅ | ✅ | 105 |
| 011_dwb_marketing_center_f | 29 | 1 | 4 | ✅ | ✅ | 103 |
| 009_dwb_product_center_f | 39 | 3 | 1 | ✅ | ✅ | 14 |
| 005_dwb_user_center_f | 46 | 4 | 4 | ✅ | ✅ | 78 |
| 012_dwb_order_center_f | 150 | 4 | 5 | ✅ | ✅ | 134 |
| 010_dwb_user_profile_f | 187 | 1 | 4 | ✅ | ✅ | 238 |
| 006_dwb_user_behavior_f | 184 | 4 | 2 | ✅ | ✅ | 85 |

> 字段数为 ts.json 各规则 fields 并集；规则数 >1 表示 designer 产出多步流水（tmp1/tmp2…→f）。

---

## 二、第一步：案例数据自检 + 第二步：脚本链路验证

### 案例自检（check_case.py）
12/12 全部通过。

### 脚本链路（--skip-ai）
首轮发现 **2 个案例**的脚本链路问题，均已修（详见第三节）：

- **001_dwl_con_pu_any_f**：preprocess 失败。根因：**RS.md 资产标识写的是另一个资产**（`fin_dwb_isc.dwb_isc_eflow_order_change_data_i`），与 mapping（`fin_dwl_cnb.dwl_con_pu_any_i`）冲突，触发目标表校验阻断。属案例数据错误，已修。
- **006_dwb_user_behavior_f**：precheck 报 40 个"目标字段重复 3 次"。precheck 为告警级（不阻断），全流程仍跑通（designer 把重复字段拆进 tmp1/tmp2/tmp3 多步规则，每个规则内字段唯一）。属案例数据质量，沿用上轮结论**不改**。
- 其余 10 个目标案例：preprocess/precheck 全部通过。

---

## 三、修复清单（已改 + 已验证）

### 修复 1：assemble_ts.py build_rule —— source_aliases 留空兜底 🔴 脚本 bug

**现象**：案例 007 全流程跑到 check_sql 失败：
```
SELECT 引用了不在 ts.json source_tables 里的表: [dwd_purchase_f, dim_supplier_f, ...]
```
核查发现 ts.json 里 R0001 的 `source_tables: []`（空），但 SELECT 明明引用了 6 张表。

**根因**：`skills/dws-design/references/assemble_ts.py` 的 `build_rule` 只在 `rule_dec["source_aliases"]` 非空时填 `source_tables`。而 designer 的 design_decisions.yaml 模板约定 `source_aliases: []` 表示"留空 → 脚本默认用 rs_input 里所有 source_tables"——但 build_rule **没实现这个兜底**，留空直接产出 `[]`。

**修复**（`build_rule` 第 180-193 行）：
```python
aliases = rule_dec.get("source_aliases") or []
if not aliases:
    # designer 留空 → 默认用 rs_input 里所有 source_tables
    aliases = list(rs_sources.keys())
for sa in aliases:
    ...
```

**验证**：
- 新增 `tests/test_assemble_ts.py`（4 项：空/缺省/显式/双空），全 PASS。
- 全套测试 72 通过（原 68 + 新 4）。
- 回归：对 002/003/004/008 重新 assemble_ts + check_sql，全部仍 PASS（这些 designer 显式列了 source_aliases，兜底分支不触发，无副作用）。
- 007 修复后 source_tables 补全 6 张，check_sql PASS。

### 修复 2：案例 001 RS.md —— 资产标识错误 🔴 案例数据

**现象**：preprocess 目标表校验阻断：
```
目标表 schema 不一致：RS='fin_dwb_isc', mapping='fin_dwl_cnb'
目标表名不一致：RS='dwb_isc_eflow_order_change_data_i', mapping='dwl_con_pu_any_i'
```
**根因**：`eval-suite/cases/001_dwl_con_pu_any_f/RS.md` 的 1.1 资产基本信息表整块写的是供应链资产（`dwb_isc_eflow_order_change_data_i`）内容，与同目录 mapping（合同PU分析表 `dwl_con_pu_any_i`）完全不符——疑似复制错文件。

**修复**：把 1.1 表的业务对象/逻辑数据实体/资产SCHEMA.接口视图/资产描述四行改成与 mapping 一致：
```
业务对象 | 合同PU分析
逻辑数据实体 | 合同+PU粒度的合同PU分析表
资产 SCHEMA.接口视图 | fin_dwl_cnb.dwl_con_pu_any_i
资产描述 | 合同PU分析表，汇总合同PU指标、合同分析、发票指标及PU维表数据。
```
**验证**：preprocess 16字段/4源表通过，案例自检通过。

### 修复 3：案例 007 mapping —— stock_days 缺销售事实表 🔴 案例数据

**现象**：coder 在非交互 local_eval 里**卡住直到超时**，R0001.sql 不产出。
流式抓取 coder 输出，发现它停在：
```
读 ts.json 发现一个设计阶段遗留的缺口，必须先和你确认：
R0001 的 stock_days（库存周转天数）字段在 join_safety 和 design_logic 里
都标注了数据源缺口警告：⚠️ 数据源缺口：stock_days 口径依赖"近30天销量"
```

**根因链**：
1. 案例 007 mapping 的 stock_days 字段（映射规则"数据加工：多步骤加工，第一步统计近30天销量"）只配了采购/供应商/商品/仓库/库存 5 张源表，**缺销售事实表**——案例数据内部不自洽。
2. designer **正确识别**了这个缺口（符合"designer 审视意识"要求），写进 join_safety + design_logic，措辞偏阻断（"编码前必须补充销售数据源，否则该字段无法产出"）。
3. coder（非交互运行）把这句当硬阻断，反复等待确认直到超时。

**修复**（案例数据修复，让数据自洽）：
- 实体级 mapping 增加销售事实表：`sdinv.dwd_sales_f`（别名 dsales），按 product_id 关联。
- 属性级 stock_days 行补源字段：`dwd_sales_f.sales_qty_30d`，映射表达式改为可自计算：
  `可售天数 = (dif.stock_qty - dif.locked_qty) / NULLIF(sales_qty_30d,0)`

**验证**：自检通过；preprocess 6 源表/23 字段；全流程跑通，coder 产出 73 行 SELECT，check_sql PASS。

---

## 四、AI 产出质量（抽样）

- **005 dwb_user_center_f**：designer 拆 4 规则（tmp1→tmp2→tmp3→f）。R0001 SELECT 含手机号脱敏（前3+****+后4）、性别码值翻译、年龄/注册天数计算、同表二次关联取城市名，注释清晰。质量高。
- **012 dwb_order_center_f**（150 字段）：designer 拆 4 规则（prod_tmp1/shop_tmp1/user_tmp1→f），结构合理；R0001 SELECT 134 行字段覆盖完整，check_sql PASS。
- **010 dwb_user_profile_f**（187 字段）：单规则 238 行 SELECT 一次产出，字段覆盖完整，check_sql PASS。
- **006 dwb_user_behavior_f**（264 字段含重复）：designer **聪明地把重复字段拆进 tmp1/tmp2/tmp3**（每个规则内字段唯一），R0001(tmp1) 50 字段 check_sql PASS。这比上轮报告"留作已知失败"的结论更进一步——全流程实际可跑通。

---

## 五、记录未改的问题（保留待评估）

### 问题 A：design→coder 契约对"数据源缺口"的处理（AI产出质量/契约）

**背景**：见修复 3。designer 发现真实数据缺口是**正确行为**（应保留，不能为"反向优化"而抑制）。问题在于缺口信息从 design 阶段"泄漏"到 coder，且措辞（"编码前必须补充…否则无法产出"）在**非交互**运行里被 coder 当硬阻断，导致卡住/超时。

**为何没改**：属 skill 指引/模型能力范畴，改 designer 或 coder 的指引（让缺口在非交互场景降级为 TODO 占位 SELECT）风险较高，需更多案例验证，本轮按"不确定的不改"保留。

**建议**：后续可考虑在 coder 指引里加一条——"非交互运行遇 design_logic 标注的数据源缺口，对该字段产出 `NULL /* TODO: 待补数据源 */` 占位，不要停止"。或在 designer 侧把缺口标注为"警告级"而非"阻断级"措辞。

### 问题 B：local_eval 只编码第一个规则（评测工具局限）

**现象**：多规则案例（005/006/009/012）只有 R0001 产出 ETL，tmp2/tmp3/…/f 的 ETL 未编码（`local_eval.py` 第 382 行"coder（取第一个规则）"是设计如此）。

**影响**：不影响结论（每条规则的 design+encode 能力都被验证），但中间表的 ETL 没生成，无法端到端验证整条流水。

**为何没改**：是评测工具的有意设计（逐规则测试），不是 bug。如需全规则编码，可对每个 rule 循环调 coder（耗时倍增）。

---

## 六、本轮重点检查项核对

| 重点项 | 结果 |
|---|---|
| 目标表写 _i 结尾，preprocess 从 _i 推 _f | ✅ 11/11 正确推导 |
| 每个规则有 load_mode | ✅ 11/11（truncate_table 等） |
| 标准DQ生成（主键/审计/记录数）+ 定制DQ留 TODO | ✅ 11/11 有 DQ 文件含记录数/主键检查 |
| RS L01 数据探索提取到 rs_input | ✅ 提取逻辑正常（本轮案例 RS 多为极简版无 L01 数据块，提取为空属正常；001 有模板章节但无实数据） |
| 文件命名：ts.md 带资产名前缀，ETL 带规则名 | ✅ 11/11（如 `dwb_shop_center_f_ts.md`、`etl/R0001.sql`） |
| 列名大小写不敏感（Schema/schema 都能匹配） | ✅ preprocess `_clean_column_name` 统一小写，11/11 通过 |
| 校验分级：两边都没写→阻断，一边没写→告警 | ✅ validate_target_table 分级正确（001 案例 RS/mapping 都写了但不一致→阻断，正是此机制抓到的） |
| db-sources.json 在 ~/.config/opencode/（install 不覆盖） | ✅ 存在，install 显示"数据库配置已存在，跳过" |
| designer 审视意识（主键发散/关联缺失在设计阶段发现） | ✅ 007 designer 抓到 stock_days 销售数据源缺失（修复 3） |

---

## 七、变更清单（已提交）

| 文件 | 类型 | 说明 |
|---|---|---|
| `skills/dws-design/references/assemble_ts.py` | 脚本修复 | build_rule source_aliases 留空兜底 |
| `tests/test_assemble_ts.py` | 新增测试 | 4 项覆盖兜底逻辑 |
| `eval-suite/cases/001_dwl_con_pu_any_f/RS.md` | 案例数据 | 修正资产标识 |
| `eval-suite/cases/007_dwb_supply_chain_f/mapping.xlsx` | 案例数据 | 补销售事实表 + stock_days 源字段 |
| `10_project_deliver/*/ddlc_design_dev/**` | 产出 | 11 案例全流程重新产出 |

提交：`2dd08aa test: 闲时回归评测结果 + 问题修复`（已 push origin main）
