# ETL 技术规格(TS)

> 目标表: `slscc.dwb_supply_chain_center_f`(供应链中心宽表) - 生成 2026-08-02T22:46:50

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
| 3 | dim.dim_product_f | 商品维度表 | dpf4 |
| 4 | dim.dim_warehouse_f | 仓库维度表 | dwf |
| 5 | sdinv.dwd_inventory_f | 库存事实表 | dif |

---

## 2. 表模型设计

- **F表**: `dwb_supply_chain_center_f`(存数据)
- **I视图**: `dwb_supply_chain_center_i`(F表镜像, 对外查询)
- **分布键**: purchase_id

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 4 |
| 粒度变化 | 无 (无（输出粒度=采购记录，与主表一致）) |
| 多步骤加工字段 | 1 |
| 聚合后关联 | 是 |

**分段结论**: 不分段
**理由**: JOIN 表数 4(<12)、多步骤加工字段 1(<5)、表级粒度无变化；单条 INSERT + 内联 CTE 即可覆盖，无需物理中间表

---

## 4. 规则详情

### R0001 - 供应链中心宽表主加工

| 项目 | 内容 |
|------|------|
| 场景 | default |
| 执行序 | 1 |
| 产出表 | `dwb_supply_chain_center_f` |
| 设计意图 | 以采购事实表为主表，左关联供应商/商品/仓库维度及库存事实表，加工状态/等级/类型映射与金额/周转天数，产出供应链中心宽表 F 表 |
| 字段数 | 23 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| dpf | main | 主表（采购事实表） |
| dsf | LEFT JOIN | dpf.supplier_id = dsf.supplier_id |
| dpf4 | LEFT JOIN | dpf.product_id = dpf4.product_id |
| dwf | LEFT JOIN | dpf.warehouse_id = dwf.warehouse_id |
| dif | LEFT JOIN | dpf.product_id = dif.product_id AND dpf.warehouse_id = dif.warehouse_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dpf | 是 |  |
| dsf | 是 |  |
| dpf4 | 是 |  |
| dwf | 是 |  |
| dif | 否 | GROUP BY (product_id, warehouse_id) 收敛，取当前有效库存行 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 14 |
| aggregate | 5 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `purchase_status_name`: 采购状态码转中文：DRAFT→草稿、SUBMITTED→已提交、APPROVED→已审批、RECEIVED→已入库、CLOSED→已关闭，其余归'其他'（源字段 dpf.purchase_status）
- `supplier_level_name`: 供应商等级码转中文：A→A级供应商、B→B级供应商、C→C级供应商，其余归'其他'（源字段 dsf.supplier_level）
- `purchase_amount`: 采购金额 = 采购数量 × 采购单价（dpf.purchase_qty × dpf.purchase_price）
- `warehouse_type_name`: 仓库类型码转中文：SELF→自营仓、THIRD_PARTY→第三方仓，其余归'其他'（源字段 dwf.warehouse_type）
- `stock_days`: 【多步骤·待补源】第一步：统计商品近30天销量（需销量/销售事实表，当前 rs_input 未提供，列为上游缺口）；第二步：库存可售天数 = 当前库存 ÷ 近30天日均销量。⚠️ 该字段依赖的销量源表不在 source_tables 中，coder 编码前需补全上游销量表，否则该字段无法落地
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
| 调度任务 | dw_slscc_dwb_supply_chain_center_f |
| 调度周期 | 0 30 3 * * ? |
| 任务组 | - |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
