# ETL 测试报告

**测试时间**: 2026-04-14 12:51:41
**测试对象**: dwl_con_pu_any_f

---

## 1. 测试概览

| 指标 | 数量 |
|------|------|
| DDL文件数 | 2 |
| ETL文件数 | 1 |
| 通过项 | 22 |
| 失败项 | 0 |
| 警告项 | 0 |

**测试结果**: ✅ 全部通过

---

## 2. 测试详情

### 2.1 通过项 ✅

| 括号平衡 - create_table_dwl_con_pu_any_f_zhangsan.sql | 括号匹配正确 |
| 引号平衡 - create_table_dwl_con_pu_any_f_zhangsan.sql | 引号匹配正确 |
| 关键字拼写 - create_table_dwl_con_pu_any_f_zhangsan.sql | 无拼写错误 |
| 内联COMMENT检查 - create_table_dwl_con_pu_any_f_zhangsan.sql | 未使用内联COMMENT |
| 字段重复检查 - create_table_dwl_con_pu_any_f_zhangsan.sql | 无字段重复 |
| DDL建表规范 - create_table_dwl_con_pu_any_f_zhangsan.sql | 使用CREATE IF NOT EXISTS，无DROP TABLE |
| TO GROUP逻辑集群 - create_table_dwl_con_pu_any_f_zhangsan.sql | TO GROUP指定正确 |
| 括号平衡 - create_view_dwl_con_pu_any_i_zhangsan.sql | 括号匹配正确 |
| 引号平衡 - create_view_dwl_con_pu_any_i_zhangsan.sql | 引号匹配正确 |
| 关键字拼写 - create_view_dwl_con_pu_any_i_zhangsan.sql | 无拼写错误 |
| 内联COMMENT检查 - create_view_dwl_con_pu_any_i_zhangsan.sql | 未使用内联COMMENT |
| 字段重复检查 - create_view_dwl_con_pu_any_i_zhangsan.sql | 无字段重复 |
| DDL建表规范 - create_view_dwl_con_pu_any_i_zhangsan.sql | 使用CREATE IF NOT EXISTS，无DROP TABLE |
| TO GROUP逻辑集群 - create_view_dwl_con_pu_any_i_zhangsan.sql | TO GROUP指定正确 |
| 括号平衡 - 01_insert_dwl_con_pu_any_f.sql | 括号匹配正确 |
| 引号平衡 - 01_insert_dwl_con_pu_any_f.sql | 引号匹配正确 |
| 关键字拼写 - 01_insert_dwl_con_pu_any_f.sql | 无拼写错误 |
| INSERT字段匹配 - 01_insert_dwl_con_pu_any_f.sql | 字段数量匹配 |
| CASE WHEN完整性 - 01_insert_dwl_con_pu_any_f.sql | 所有CASE都有ELSE分支 |
| JOIN ON条件 - 01_insert_dwl_con_pu_any_f.sql | 所有JOIN都有ON条件 |
| SELECT * 检查 - 01_insert_dwl_con_pu_any_f.sql | 未使用SELECT * |
| DDL-ETL一致性 | DDL与ETL字段一致 |

### 2.2 失败项 ❌

无

### 2.3 警告项 ⚠️

无

---

## 3. 测试文件清单

### 3.1 DDL 文件

- `create_table_dwl_con_pu_any_f_zhangsan.sql`
- `create_view_dwl_con_pu_any_i_zhangsan.sql`

### 3.2 ETL 文件

- `01_insert_dwl_con_pu_any_f.sql`

---

## 4. 测试项目说明

| 测试项 | 描述 |
|--------|------|
| 括号平衡检查 | 检查 SQL 语句中括号是否正确闭合 |
| 引号平衡检查 | 检查字符串引号是否正确闭合 |
| 关键字拼写检查 | 检查 SQL 关键字是否存在拼写错误 |
| INSERT字段匹配 | 检查 INSERT 和 SELECT 字段数量是否一致 |
| DDL-ETL一致性 | 检查 ETL 写入字段与 DDL 定义是否一致 |

---

*报告生成完毕*
