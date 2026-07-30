---
description: DWS ETL 设计流程（预处理→设计→闸口①确认）
agent: build
---

你是设计开发流程的执行者。请按以下编排逻辑严格执行，不要自己发明步骤。

用户输入：$ARGUMENTS

---

# 执行流程

## 步骤 0：确定输入文件

从用户输入中识别：
- **mapping 文件**（.xlsx）：实体级+属性级映射
- **RS 文档**（.md）：需求规格

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

**目标表名**从 RS 的资产基本信息或 mapping 的目标表推导，用于确定输出目录 `docs/output/{target_table}/`。

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

设计完成后，用 `ls` 验证 ts.json 和 ts.md 已生成。

---

## 步骤 3：闸口①（人确认设计方向）

设计完成后，**必须暂停等用户确认**。用 question 展示设计摘要：

```
## 设计完成，请确认方向

### 设计摘要
- **目标表**: {schema}.{table}（{中文名}）
- **规则数**: {N} 个
- **场景数**: {M} 个
- **字段统计**: 业务 {N} + 审计 4 = 总计 {N}

### 规则概览
{每个规则的 rule_name + target_table + design_intent 一句话}

### 关键设计决策
{从 ts.json 的 design.complexity_analysis 提取分段决策}
{从 ts.json 的 rules 提取关联安全分析要点}

请选择：
- ✅ 确认设计
- ✏️ 需要修改（说明哪里要改）
- ❌ 放弃
```

**用户确认后**，输出"设计已确认，TS 制品包已就绪"。
**用户要改** → 回步骤 2 重新调 designer。
**用户放弃** → 结束。

---

# 硬性规则

- ❌ 跳过预处理直接让 designer 猜输入
- ❌ 未经用户确认（步骤3）就算设计完成
- ❌ 预检返回码=2 时继续执行
- ✅ 预处理返回码=1 时询问用户
- ✅ designer 产出后用 ls 验证文件已生成
- ✅ 全程用中文交互和输出
