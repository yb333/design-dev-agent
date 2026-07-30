# 合同pu分析表 映射文档

**目标表**: `fin_dwl_cnb.dwl_con_pu_any_f`
**解析时间**: 2026-04-14 12:31:56

## 1. 实体级映射

| 源表 | 别名 | 中文名 | 目标表 | 关联条件 |
|------|------|--------|--------|----------|
| `fin_dwl_cnb.dwl_con_pu_mtr_f` | t | 合同pu指标表 | `fin_dwl_cnb.dwl_con_pu_any_f` | 主表，需要将表中的rpt_code进行行转列，将对应金额打到列上 |
| `fin_dwl_cnb.dwl_con_any_f` | f | 合同分析表 | `fin_dwl_cnb.dwl_con_pu_any_f` | left join on t.contract_key = f.contract_key |
| `fin_dwb_cnb.dwb_inv_head_i` | inv | 发票头表 | `fin_dwl_cnb.dwl_con_pu_any_f` | - |
| `fin_dwb_cnb.dwb_inv_cre_i` | cre | 发票核销表 | `fin_dwl_cnb.dwl_con_pu_any_f` | - |
| `fin_dwl_cnb.dwl_inv_mtr_i` | inv_mtr | 发票指标表 | `fin_dwl_cnb.dwl_con_pu_any_f` | left join on t.contract_id =s.contract_id and t.pu_id=s.pu_id and s.inv_flag in('inv_in','inv_out') and not exists(select 1 from afr_inv app where s.inv_id=app.inv_id and s.contract_no =app.contract_no) |
| `dwrdim_dw1.dwr_dim_pu_d` | pu | pu维表 | `fin_dwl_cnb.dwl_con_pu_any_f` | left join on pu_id=pu_id ,纬度取最新 |

## 2. 属性级映射

| 目标字段 | 目标类型 | 目标中文名 | 来源表 | 来源字段 | 映射规则 | 转换逻辑 |
|----------|----------|------------|--------|----------|----------|----------|
| `contract_no` | nvarchar(500) | 合同号 | `t` | `contract_no` | 直取 | - |
| `contract_id` | numeric | 合同id | `t` | `contract_id` | 直取 | - |
| `contrcat_key` | numeric | 合同key | `t` | `contrcat_key` | 直取 | - |
| `pu_id` | numeric | pu的id | `t` | `pu_id` | 直取 | - |
| `tc_code` | nvarchar(30) | 交易币种 | `t` | `currency_code` | 直取 | - |
| `equip_org_amt_usd` | numeric(38,10) | 设备订货usd金额 | `t` | `rpt_value_usd` | 数据加工 | 选择prt_code='fbt_0001'的行的rpt_value_usd，然后sum（这里sum是更安全的） |
| `equip_org_amt_rmb` | numeric(38,10) | 设备订货rmb金额 | `t` | `rpt_value_rmb` | 数据加工 | 选择prt_code='fbt_0001'的行的rpt_value_usd，然后sum（这里sum是更安全的） |
| `equip_cfm_amt_rmb` | numeric(38,10) | 设备收入rmb金额 | `t` | `rpt_value_rmb` | 数据加工 | 选择prt_code='fbt_0002'的行的rpt_value_usd，然后sum（这里sum是更安全的） |
| `equip_cfm_amt_usd` | numeric(38,10) | 设备收入usd金额 | `t` | `rpt_value_usd` | 数据加工 | 选择prt_code='fbt_0002的行的rpt_value_usd，然后sum（这里sum是更安全的） |
| `proj_key` | numeric | 项目key | `f` | `proj_key` | 直取 | - |
| `inv_tol_amt_usd` | numeric(38,10) | 开票usd金额 | `inv_mtr` | `inv_inst_amt_usd` | 数据加工 | 按照contract_no,pu_id,contract_id，收敛后，sum(inv_inst_amt_usd) |
| `inv_tol_amt_rmb` | numeric(38,10) | 开票rmb金额 | `inv_mtr` | `inv_inst_amt_rmb` | 数据加工 | 按照contract_no,pu_id,contract_id，收敛后，sum(inv_inst_amt_rmb) |
| `pu_key` | numeric | pu的key | `pu` | `pu_key` | 直取 | - |
| `del_flag` | nvarchar(1) | 删除标识 | `（无）` | `` | 赋值 | 'N' |
| `crt_cycle_id` | bigint | 创建批次ID | `（无）` | `` | 赋值 | ${P_CYCLE_ID} |
| `last_upd_cycle_id` | bigint | 最后更新批次ID | `（无）` | `` | 赋值 | ${P_CYCLE_ID} |
| `dw_last_update_date` | timestamp(0) without time zone | 数仓最后更新时间 | `（无）` | `` | 赋值 | CURRENT_TIMESTAMP |

## 3. 统计信息

| 项目 | 数量 |
|------|------|
| 设计模式 | single_source |
| 源表数量 | 6 |
| 字段数量 | 17 |
| 直取字段 | 7 |
| 数据加工字段 | 6 |
| 赋值字段 | 4 |
| 去重字段数 | 17 |

## 4. 调度配置

| 配置项 | 值 |
|--------|-----|
| 项目名称 | SRP_DAILY |
| 任务组名称 | GROUP_SPRD |
| 调度周期 | 0 26 0 * * ? |
| 责任人 | zhangsan |

### 源表调度任务映射

| 源表 | 调度任务名称 | 执行路径 |
|------|-------------|----------|
| `fin_dwl_cnb.dwl_con_pu_mtr_f` | task_dwl_con_pu_mtr_f | - |
| `fin_dwl_cnb.dwl_con_any_f` | task_dwl_con_any_f | - |
| `fin_dwb_cnb.dwb_inv_head_i` | task_dwb_inv_head_i | - |
| `fin_dwb_cnb.dwb_inv_cre_i` | task_dwb_inv_cre_i | - |
| `fin_dwl_cnb.dwl_inv_mtr_i` | task_dwl_inv_mtr_i | - |
| `dwrdim_dw1.dwr_dim_pu_d` | task_dwr_dim_pu_d | - |

## 5. 执行平台配置

| 配置项 | 值 |
|--------|-----|
| 项目编码 | SRP_ETL |
| 项目中文名 | 商品中心 |
| 项目英文名 | ProductCenter |
| 子项目编码 | SRP_GRP01 |
| 子项目中文名 | 商品中心组 |
| 子项目英文名 | ProductCenterGroup |
| 数据源 | SRP_DWS |
| 业务责任人 | zhangsan |

## 6. 设计配置

| 配置项 | 值 |
|--------|-----|
| 封装视图 | 是 |
| 目标表粒度 | 合同+pu粒度 |
| 写入策略 | 全量 |

## 7. 数据处理步骤

### 获取非洲发票范围

| 步骤 | 说明 |
|------|------|
| 1 | dwb_inv_head_i限制 where inv.company in ('1001,'1002') and inv_p_flag =2 内关联 dwb_inv_head_i 关联条件是 on inv.inv_id =cre.inv_id and cre.app_flag =0 and cre.p_flag=1 ; 这步操作结果集afr_inv ，获取非洲发票，后续在加工开票金额时，计算过程中排除这些数据 |
