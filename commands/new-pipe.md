---
description: DWS ETL 设计流程（预处理→设计→闸口①确认）
agent: build
---

你是设计开发流程的执行者。按以下步骤执行。

用户输入：$ARGUMENTS

---

## 步骤 1：预处理（你来执行，不是 designer 的活）

从用户输入识别 mapping 文件（.xlsx）和 RS 文件（.md）。

运行预处理脚本（合并 mapping + RS → rs_input.json + 预检）：

```bash
python ~/.config/opencode/skills/dws-design/references/preprocess.py \
  --mapping {mapping路径} \
  --rs {RS路径} \
  --output docs/output/{target_table}/01_input/rs_input.json \
  --check
```

**目标表名**从 RS 资产信息或 mapping 目标表推导。

**判断返回码**：
- 0（PASS）→ 继续
- 1（WARNING）→ 显示警告，问用户是否继续
- 2（INCOMPLETE）→ 停止，显示错误，让用户补输入

---

## 步骤 2：调 dws-designer 产出 TS

预处理通过后，用 Task 调用 dws-designer：

```
Task(
  subagent_type="dws-designer",
  description="产出TS制品包",
  prompt="读取 docs/output/{target_table}/01_input/rs_input.json，产出 ts.json + ts.md 到 docs/output/{target_table}/02_design/。"
)
```

designer 完成后用 `ls` 验证 ts.json 和 ts.md 已生成。

---

## 步骤 3：闸口①（人确认设计方向）

**必须暂停等用户确认**。用 question 展示设计摘要：

```
## 设计完成，请确认方向

### 设计摘要
- **目标表**: {schema}.{table}（{中文名}）
- **规则数**: {N} 个
- **场景数**: {M} 个
- **字段统计**: 业务 {N} + 审计 4 = 总计 {N}

### 规则概览
{每个规则的 rule_name + design_intent}

### 关键设计决策
{分段决策 + 关联安全分析要点}

请选择：
- ✅ 确认设计
- ✏️ 需要修改（说明哪里要改）
- ❌ 放弃
```

**用户确认** → "设计已确认，TS 制品包已就绪于 02_design/"。
**用户要改** → 回步骤 2 重新调 designer。
**用户放弃** → 结束。

---

# 硬性规则

- ✅ 预处理由你（primary agent）执行，不是 designer 的活
- ❌ 不要让 designer 解析 Excel 或 RS
- ❌ 未经用户确认就算设计完成
- ✅ designer 产出后用 ls 验证文件已生成
- ✅ 全程中文
