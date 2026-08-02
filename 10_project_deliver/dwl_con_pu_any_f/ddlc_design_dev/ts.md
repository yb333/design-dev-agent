# ETL 技术规格(TS)

> 目标表: `fin_dwl_cnb.dwl_con_pu_any_f`(合同pu分析表) - 生成 2026-08-02T14:06:02

---

## 1. 概述

| 项目 | 内容 |
|------|------|
| **F 表** | `fin_dwl_cnb.dwl_con_pu_any_f`(合同pu分析表) |
| **I 视图** | `fin_dwl_cnb.dwl_con_pu_any_i`(F表镜像) |
| **目标粒度** |  |
| **写入策略** |  |
| **分布键** | contract_id, pu_id |
| **字段统计** | 业务 12 + 审计 4 = 总计 16 |
| **审计字段来源** | 全部来自 RS/mapping |
| **规则数** | 1 |

**来源表**:

| # | 表名 | 中文名 | 别名 |
|---|------|--------|------|
| 1 | fin_dwl_cnb.dwl_con_pu_mtr_f | 合同pu指标表 | t |
| 2 | fin_dwl_cnb.dwl_con_any_f | 合同分析表 | f |
| 3 | fin_dwl_cnb.dwl_inv_mtr_i | 发票指标表 | inv_mtr |
| 4 | dwrdim_dw1.dwr_dim_pu_d | pu维表 | pu |

---

## 2. 表模型设计

- **F表**: `dwl_con_pu_any_f`(存数据)
- **I视图**: `dwl_con_pu_any_i`(F表镜像, 对外查询)
- **分布键**: contract_id, pu_id

**中间表**:

| 规则 | 表名 | 粒度 | 用途 |
|------|------|------|------|
| R0001 | fin_dwl_cnb.dwl_con_pu_any_f | (contract_id, pu_id) — rpt_code 行转列后收敛为单行 | 主查询：将主表 rpt_code 指标行转列收敛为4个金额列，LEFT JOIN 合同分析表取项目key、 收敛后的发票指标表（排除非洲发票）取发票总额、pu维表（取最新有效行）取pu_key， 按合同+pu粒度写入分析宽表。 |

---

## 3. 复杂度分析与分段决策

| 因素 | 值 |
|------|-----|
| JOIN 表数量 | 3 |
| 粒度变化 | 有 (行转列：主表（合同,pu,rpt_code）→ 目标表（合同,pu），rpt_code维度展开为4个金额列) |
| 多步骤加工字段 | 6 |
| 聚合后关联 | 否 |

**分段结论**: 不分段
**理由**: JOIN≤12（3）、聚合后关联=否、复杂关联链≤2；行转列与发票收敛均为单步加工，满足CTE内联条件，不建物理中间表

---

## 4. 规则详情

### R0001 - 合同pu分析表写入

| 项目 | 内容 |
|------|------|
| 场景 | 默认场景 |
| 执行序 | 1 |
| 产出表 | `fin_dwl_cnb.dwl_con_pu_any_f` |
| 设计意图 | 主查询：将主表 rpt_code 指标行转列收敛为4个金额列，LEFT JOIN 合同分析表取项目key、 收敛后的发票指标表（排除非洲发票）取发票总额、pu维表（取最新有效行）取pu_key， 按合同+pu粒度写入分析宽表。 |
| 字段数 | 16 |

**关联策略**:

| 别名 | JOIN | 条件 |
|------|------|------|
| t | main | 主表（粒度锚点：合同+pu） |
| f | LEFT JOIN | t.contract_key = f.contract_key |
| inv_agg | LEFT JOIN | t.contract_id = inv_agg.contract_id AND t.pu_id = inv_agg.pu_id |
| pu | LEFT JOIN | t.pu_id = pu.pu_id |

**关联安全**:

| 表 | JOIN键唯一 | 对齐策略 |
|------|-----------|----------|
| dwl_con_any_f | 是 | 直接关联 |
| dwl_inv_mtr_i | 否 | GROUP BY收敛 |
| dwr_dim_pu_d | 否 | 取最新有效行 |

**字段概要**:

| 转换类型 | 数量 |
|----------|------|
| direct | 6 |
| aggregate | 6 |
| assign | 4 |
| assign(审计) | 4 |

**加工字段抽样**(完整字段见 ts.json):

- `equip_org_amt_usd`: 行转列：rpt_code='fbt_0001' 对应设备订货，取报表值USD，按合同+pu汇总
- `equip_org_amt_rmb`: 行转列：rpt_code='fbt_0001' 对应设备订货，取报表值RMB，按合同+pu汇总
- `equip_cfm_amt_rmb`: 行转列：rpt_code='fbt_0002' 对应设备收入，取报表值RMB，按合同+pu汇总
- `equip_cfm_amt_usd`: 行转列：rpt_code='fbt_0002' 对应设备收入，取报表值USD，按合同+pu汇总
- `inv_tol_amt_usd`: 对发票指标表发票瞬时金额USD求和，排除非洲发票，按合同+pu收敛后关联
- ...(共 10 个加工字段)

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
| 调度任务 | task_dwl_con_pu_any_f |
| 调度周期 | 0 0 1 * * ? |
| 任务组 | GROUP_SPRD |

---

## 7. 数据质量检查(DQ)

*(本表无 DQ 要求)*
