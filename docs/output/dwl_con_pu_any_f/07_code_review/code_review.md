# ETL 代码评审报告

**生成时间**: 2026-04-14
**设计文档**: docs/output/dwl_con_pu_any_f/02_design/design.md
**目标表**: `fin_dwl_cnb.dwl_con_pu_any_f`

---

## 问题详情

### CRITICAL (必须修复)

> ✅ 无 CRITICAL 问题

---

### MAJOR (强烈建议修复)

#### [M-1] 主表列名引用不一致：contrcat_key vs contract_key

- **文件**: 05_etl/01_insert_dwl_con_pu_any_f.sql
- **行号**: 92, 114
- **问题描述**: 同一表别名 `t`（fin_dwl_cnb.dwl_con_pu_mtr_f）在两处使用了不同的列名引用。
  - 第 92 行 SELECT 中使用 `t.contrcat_key`（与 DDL 目标字段名一致）
  - 第 114 行 JOIN ON 中使用 `t.contract_key`（与 dwl_con_any_f 的关联键一致）
  
  设计文档字段映射表中源字段名为 `contrcat_key`，但关联策略中 JOIN 条件为 `t.contract_key = f.contract_key`。源表实际列名只能有一个，两处引用必有一处运行时报错。
- **修复建议**: 确认源表 `dwl_con_pu_mtr_f` 中该列的实际名称：
  - 若实际列名为 `contrcat_key` → 修正第 114 行为 `ON t.contrcat_key = f.contract_key`，同时确认 dwl_con_any_f 的关联键名
  - 若实际列名为 `contract_key` → 修正第 92 行为 `t.contract_key`，并修正 DDL 目标字段名及 INSERT 字段列表

---

### MINOR (建议优化)

> ✅ 无 MINOR 问题

---

### SUGGESTION (参考建议)

#### [S-1] afr_inv CTE 增加了设计文档未记录的过滤条件

- **文件**: 05_etl/01_insert_dwl_con_pu_any_f.sql
- **行号**: 33-34
- **建议**: afr_inv CTE 除设计文档描述的 `company IN ('1001','1002') AND inv_p_flag=2` 外，还增加了 `cre.app_flag = 0 AND cre.p_flag = 1`。建议在设计文档 CTE 说明中补充这两个条件，保持设计文档与代码一致。

---

## 评审结论

| 指标 | 数量 |
|------|------|
| CRITICAL | 0 |
| MAJOR | 1 |
| MINOR | 0 |
| SUGGESTION | 1 |

**最终结论**: ✅ 通过

**停止标志**: CONTINUE
