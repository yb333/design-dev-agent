# ETL 技术规格(TS)

> 目标表: `slscc.dwb_supply_chain_center_f`(供应链中心宽表) - 生成 2026-08-03T22:58:00

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `slscc.dwb_supply_chain_center_f`(供应链中心宽表) |
| **I 视图** | `slscc.dwb_supply_chain_center_i`(F表镜像) |
| **目标粒度** | 每行一个供应链记录 |
| **写入策略** | 全量调度 |
| **分布键** | purchase_id |
| **字段统计** | 业务 19 + 审计 4 = 总计 23 |
| **审计字段来源** | 全部来自 RS/mapping |
| **规则数** | 1 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | sdinv.dwd_purchase_f | 采购事实表 | dpf |
| 2 | dim.dim_supplier_f | 供应商维度表 | dsf |
| 3 | dim.dim_product_f | 商品维度表 | dpf2 |
| 4 | dim.dim_warehouse_f | 仓库维度表 | dwf |
| 5 | sdinv.dwd_inventory_f | 库存事实表 | dif |
| 6 | sdinv.dwd_sales_f | 销售事实表 | dsales |

---

## 2. 表模型设计

- **F表**: `dwb_supply_chain_center_f`(存数据)
- **I视图**: `dwb_supply_chain_center_i`(F表镜像, 对外查询)
- **分布键**: purchase_id

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 6 |
| 粒度变化 | 无 (输入=采购单（dpf），输出=采购单（宽表），无聚合/展开。) |
| 多步骤加工字段 | 1 |
| 聚合后关联 | 否 |

**分段结论**: 不分段
**理由**: JOIN 表数量 6（< 12 阈值）、多步骤加工字段 1（< 5 阈值）、无粒度变化。 虽命中 design-guide §4.1 的"聚合后关联"指标（dsales 需先按 product_id 聚合销量再 JOIN）， 但该聚合逻辑简单（单一 GROUP BY 求和）、且仅 stock_days 一处使用、无需独立校验 → 按 design-guide §4.2 用 CTE(sales_agg) 内联处理即可，建物理中间表属过度设计。 单条规则 R0001 一次性产出目标 F 表，I 视图由后续脚本/规则镜像 F 表。

---

## 4. 规则详情

### R0001 - 供应链中心宽表全量加工

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_supply_chain_center_f` |
| 设计意图 | 以采购事实表(dpf)为主表，左联供应商/商品/仓库维度表与库存/销售事实表，单条 INSERT 一次性产出宽表；销售表(dsales)因 sales_product_id 多行会发散，必须经 CTE 按 product_id 聚合收敛后再 JOIN，保障产出粒度=采购单。 |
| 字段数 | 23 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dpf | main | 主表 |
| dsf | LEFT JOIN | p.supplier_id = s.supplier_id |
| dpf2 | LEFT JOIN | p.product_id = prd.product_id |
| dwf | LEFT JOIN | p.warehouse_id = wh.warehouse_id |
| dif | LEFT JOIN | p.product_id = inv.product_id AND p.warehouse_id = inv.warehouse_id |
| sales_agg | LEFT JOIN | p.product_id = sales_agg.product_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dsf | 是 |  |
| dpf2 | 是 |  |
| dwf | 是 |  |
| dif | 是 |  |
| dsales | 否 | CTE(sales_agg) 先按 product_id 聚合 sales_qty_30d 再 JOIN，聚合后 product_id 唯一。 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 14 |
| aggregate | 5 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `purchase_status_name`: 把采购单状态英文码值翻译成中文：DRAFT→草稿、SUBMITTED→已提交、APPROVED→已审批、RECEIVED→已入库、CLOSED→已关闭，其余码值归为'其他'。
- `supplier_level_name`: 把供应商等级 A/B/C 翻译成中文等级名：A→A级供应商、B→B级供应商、C→C级供应商，其余码值归为'其他'。
- `warehouse_type_name`: 把仓库类型码值翻译成中文：SELF→自营仓、THIRD_PARTY→第三方仓，其余码值归为'其他'。
- `purchase_amount`: 采购金额 = 采购数量 × 采购单价（取主表 dpf 的 purchase_qty 与 purchase_price 相乘）。
- `stock_days`: 库存周转天数。先用 CTE(sales_agg) 把 dsales 按 product_id 聚合统计近30天销量(sales_qty_30d)，再用 (当前库存 - 锁定库存) ÷ 近30天销量计算周转天数；当近30天销量为 0 时返回 NULL（防除零）。
- ...(共 9 个加工字段)

---

## 5. 数据流向

**执行顺序**:

| 顺序 | 规则 |
|------|------|
| 1 | R0001 |

---

## 6. 调度配置

| 配置项 | 值 |
|--------|-----|
| 调度任务 | dwb_supply_chain_center_f_全量 |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | supply_chain |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
