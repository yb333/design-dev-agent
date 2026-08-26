---
name: dws-dq
description: >-
  DQ 检查 SQL 生成。被 dws-coder 加载（DQ 任务时）。
  契约：DQ SELECT = 违规行探测器——0 行=通过，非 0 行=告警。
  ETL 规则编码不在此（dws-coding）；优化不在此（dws-coding-opt）。
---

# DQ 检查 SQL 生成 Skill

> 收到 DQ 生成任务时你（dws-coder）加载本 skill。**契约一句话：
> DQ SELECT = 违规行探测器——0 行=通过，非 0 行=告警。**

## 1. 拿 DQ 切片（不整读 ts.json）

```bash
python {dws-coding 的 scripts 目录}/slice_ts.py --ts {ts路径} --dq
```

slice_ts 住在**同级 dws-coding skill** 的 `scripts/` 下（用注入的 location 推同级路径——工具共享，边界在 SKILL）。切片含：契约 / `target_table`（检查对象，schema 全名）/ `business_key`（输出业务键列）/ `dq_rules` 全量。

## 2. 逐条生成

每条 dq_rule 一个文件 `dq_{check_type}.sql`（UT 按此确定名找文件，缺失即发现项）：

- **方向**：rule_desc 已写明什么情况算违规，照口径定 WHERE——查空值就 `WHERE col IS NULL`（有空值=告警行），别写反
- **阈值/比例逻辑全收进 WHERE/HAVING**，SQL 只负责吐违规行
- **输出列 = 业务键（切片 business_key）+ 违规值字段**——不 SELECT *，不带审计字段（DQ 是探测不是装载）
- 参数直接写 `${参数名}`（UT 执行前替换测试值）
- 检查对象是切片的 target_table——UT 灌数后执行验证，上线后平台按调度跑同一份 SQL
- SQL 规范同 dws-coding 的 coding-standards（同级 `references/dws-coding-standards.md`）：方言 §0（CAST 首选/类型转换细则）、注释一律 `/* */`、对象引用 schema 全限定

## 3. 边界

- 不跑 check_sql——它按 rule_code 查 ts.rules，DQ 不是规则；DQ 的执行验证归 UT 的 DQ 阶段（0 行=过，非 0 行=告警阻断闸口② 人判）
- 不做 ETL 规则编码（那是 dws-coding 的活）；任务混了两者 → question 回报调用方
