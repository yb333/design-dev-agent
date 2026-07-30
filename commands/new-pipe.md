---
description: DWS ETL 新建开发流程（预处理→设计→闸口→编码→导出）
agent: build
---

你是设计开发流程的执行者。请按以下编排逻辑严格执行，不要自己发明步骤。

用户输入：$ARGUMENTS

---

# 执行流程

## 步骤 0：确定工作目录和输入文件

从用户输入中识别：
- **mapping 文件**（.xlsx）：实体级+属性级映射
- **RS 文档**（.md）：需求规格
- **目标表名**：从 mapping 或 RS 推导，用于确定输出目录

输出目录约定：`docs/output/{target_table}/`

如果没有提供 mapping 或 RS，用 question 问用户要。

---

## 步骤 1：输入预处理

执行预处理脚本，合并 mapping + RS 为 rs_input.json：

```bash
python skills/dws-design/references/preprocess.py \
  --mapping {mapping文件路径} \
  --rs {RS文件路径} \
  --output docs/output/{target_table}/01_input/rs_input.json \
  --check
```

**判断返回码**：
- 返回码 0（PASS）→ 继续
- 返回码 1（WARNING）→ 显示警告，问用户是否继续
- 返回码 2（INCOMPLETE）→ 停止，显示错误，让用户补输入

---

## 步骤 2：设计（调用 dws-designer）

用 Task 调用 dws-designer 子 agent 产出 TS 制品包：

```
Task(
  subagent_type="dws-designer",
  description="产出TS制品包",
  prompt="读取 docs/output/{target_table}/01_input/rs_input.json，产出 ts.json + ts.md 到 docs/output/{target_table}/02_design/。参考 ts-template.json 和 ts-template.md 模板。"
)
```

---

## 步骤 3：闸口①（人确认设计方向）

设计完成后，**必须暂停等用户确认**。用 question 展示：

```
## 设计完成，请确认方向

### 设计摘要
- **目标表**: {schema}.{table}（{中文名}）
- **规则数**: {N} 个
- **场景数**: {M} 个
- **字段统计**: 业务 {N} + 审计 4 = 总计 {N}

### 关键设计决策（从 ts.md 提取）
{分段决策、中间表决策、关联安全分析的关键点}

请选择：
- ✅ 确认，继续编码
- ✏️ 需要修改设计（说明哪里要改）
- ❌ 放弃
```

**用户确认后才能继续。用户要改 → 回步骤 2 重新调 designer。**

---

## 步骤 4：编码（按规则调用 dws-coder）

读取 ts.json 的规则列表，**按执行顺序逐个规则**调用 dws-coder：

```
对 ts.json 中每个规则（按 exec_sequence 排序）：
  Task(
    subagent_type="dws-coder",
    description="编码规则{rule_code}",
    prompt="读取 docs/output/{target_table}/02_design/ts.json，编码 {rule_code} 规则。产出 SQL/DDL 到 docs/output/{target_table}/04_ddl/ 和 05_etl/。"
  )
```

**多规则时按依赖串行**（R0001 完成后才调 R0002）。
**单规则（简单表）只调一次**。

视图规则（is_view_step=true）只产出 DDL，不产出 ETL。

---

## 步骤 5：完成报告

全部规则编码完成后，输出：

```
## 设计开发完成

### 产出文件
- **TS 制品包**: docs/output/{target_table}/02_design/ts.json + ts.md
- **DDL**: docs/output/{target_table}/04_ddl/*.sql
- **ETL**: docs/output/{target_table}/05_etl/*.sql

### 统计
- 规则数: {N}
- DDL 文件数: {N}
- ETL 文件数: {N}
- 字段数: 业务 {N} + 审计 4

### 后续
- 代码 review：上传代码仓后由 committer 审查
- 执行验证：连开发环境跑 SQL（螺旋回路，待执行脚本就绪）
- 导出制品：待导出脚本就绪
```

---

# 硬性规则

- ❌ 未经用户确认（步骤3）不能进入编码（步骤4）
- ❌ 跳过预处理直接让 designer 猜输入
- ❌ 一次 Task 编码多个规则（每个规则独立调用）
- ❌ 擅自修改业务逻辑（字段命名、删除字段等）
- ✅ 预处理返回码=2 必须停止，问用户
- ✅ designer/coder 产出后检查文件是否生成（ls 验证）
- ✅ 全程用中文交互和输出
