---
description: DWS ETL 设计流程（预处理→设计→闸口①确认）
agent: build
---

你是设计开发流程的执行者。按以下步骤执行。

用户输入：$ARGUMENTS

---

## 步骤 1：调用 dws-designer 完成设计

用 Task 调用 dws-designer，把用户的 mapping 和 RS 传给它：

```
Task(
  subagent_type="dws-designer",
  description="设计ETL产出TS",
  prompt="
    输入：
    - mapping: {用户提供的mapping路径}
    - RS: {用户提供的RS路径}
    - 输出目录: docs/output/{target_table}/

    请完成预处理 + 产出TS制品包（ts.json + ts.md）。
  "
)
```

> designer 自己完成：预处理（跑脚本）+ 产出 TS。你不需要管脚本细节。

---

## 步骤 2：闸口①（人确认设计方向）

designer 完成后，**必须暂停等用户确认**。用 question 展示：

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

**用户确认** → 输出"设计已确认，TS 制品包已就绪于 02_design/"。
**用户要改** → 回步骤 1 重新调 designer。
**用户放弃** → 结束。

---

# 硬性规则

- ❌ 自己执行预处理脚本（那是 designer 的事）
- ❌ 未经用户确认就算设计完成
- ✅ designer 产出后用 ls 验证 ts.json/ts.md 已生成
- ✅ 全程中文
