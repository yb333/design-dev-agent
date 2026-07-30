---
name: dws-design
description: >-
  DWS ETL 设计方法论 + TS 产出规范。被 dws-designer agent 加载。
  指导如何从 rs_input.json 产出 TS 制品包（ts.json + ts.md）。
---

# DWS ETL 设计 Skill

> 本 skill 被 **dws-designer** agent 加载，提供设计方法论和 TS 产出规范。
> TS 格式权威定义见 `docs/specs/ts-format.md`。

---

## 1. 设计的核心任务

把需求（rs_input.json）转化为技术规格（TS），本质是：

> **把一个资产的加工，划分成多个步骤（规则），清晰表达加工逻辑。**

规则是核心实体（一条 INSERT = 产出一个表）。场景是规则的属性。

---

## 2. 设计流程（designer 的思考顺序）

### 步骤 1：理解需求
- 读 rs_input.json 的 meta（目标表 F+I、粒度、调度框架）
- 读 source_tables（源表关联关系）
- 读 field_mappings（字段映射 + 转换规则）
- 读 data_flow_hint（数据流描述）

### 步骤 2：场景识别
- 同一业务实质的数据，来自不同来源、需不同加工逻辑 → 分场景
- 场景的本质：同一目标表的多来源并行加工（类似 UNION，但有去重/依赖等变体）
- 场景是规则的属性，不是独立结构层

### 步骤 3：规则拆分
- 把整体加工拆成多个规则
- 一个规则 = 一条 INSERT = 产出一个表（中间表 / 目标F表 / 视图I表）
- 规则的粒度：简单时多来源合一规则（UNION ALL），复杂时一来源一规则
- 收口点：多场景可收敛到中间表后统一加工

### 步骤 4：字段分配
- 每个字段归属哪个规则（producing_step）
- 自建字段（中间表辅助计算）= 规则的目标字段，不区分层级
- 审计字段放 design.audit_fields 模板，不在 fields 里重复

### 步骤 5：复杂度评估与分段
详见 `references/optimization-rules.md` 的分段规则。核心指标：
- JOIN 表数量、粒度变化、多步骤加工字段数、聚合后关联、复杂关联链
- 分段结论 + 中间表决策（CTE 内联 vs 物理中间表）

### 步骤 6：字段加工逻辑
- 每个字段的 design_logic = **自然语言口径**（不含 SQL 表达式）
- 从 RS 的 field_mappings 拆出（多数口径一致，只是细化到字段级）
- 描述"算什么、什么口径"，不描述"SQL 怎么拼"
- transform_type 标注：direct / pivot / aggregate / assign

### 步骤 7：关联安全分析
- 每个被关联表：JOIN 键在限定条件下是否唯一
- 不唯一 → 对齐策略（GROUP BY 收敛 / 取最新有效行 / 等）

### 步骤 8：调度细化
- RS 给大框架（日级）→ 细化为标准 cron 表达式
- 补中间表新增的上游依赖

### 步骤 9：产出 TS
- ts.json（机读，按 `docs/specs/ts-format.md` 格式）
- ts.md（人读投影，从 ts.json 渲染）

---

## 3. 中间表设计（螺旋式）

中间表设计是螺旋的——先骨架后回填：
1. **先骨架**：复杂度评估后决定建几个中间表，定表名/粒度/用途
2. **字段逻辑**：确定每个字段加工逻辑时，识别哪些字段落在中间表
3. **回填字段**：从字段分配回填出每个中间表的完整字段清单

中间表的字段绝大多数与目标表字段同名同类型（透传/聚合），极少量 designer 自建字段（辅助计算中间产物）。

---

## 4. 数据流图

参照 analyzer 的数据流图样式：
- 节点 = 规则（产出表）
- 场景通过节点属性标记
- 多场景并行通过 schedule_groups 表达
- 详见 `docs/specs/ts-format.md` §3.5 data_flow 结构

---

## 5. 参考文档

| 文档 | 内容 |
|------|------|
| `references/ts-template.json` | **TS JSON 产出模板**（ts.json 骨架，含占位符说明） |
| `references/ts-template.md` | **TS MD 产出模板**（ts.md 骨架，7章结构，含占位符说明） |
| `references/naming-conventions.md` | 表/字段/规则命名规范 |
| `references/dws-best-practices.md` | DWS 物理设计标准（存储/分布/压缩/分区） |
| `references/optimization-rules.md` | 分段策略 + 分布键优化 + 中间表决策规则 |
| `docs/specs/ts-format.md` | TS 制品包格式定义（**产出必读**） |
| `docs/specs/rs-input-format.md` | RS 输入格式（**理解输入**） |

---

## 6. 产出检查清单

产出 ts.json/ts.md 前自检：
- [ ] ts.json 顶层：version / spec_type / meta / design / rules / data_flow / dq_rules
- [ ] rules 按规则分组，每个规则内嵌 fields
- [ ] 每个字段有 design_logic（自然语言）+ transform_type + source_fields
- [ ] 审计字段在 design.audit_fields，不在 fields 重复
- [ ] 场景是规则的 scenario 属性
- [ ] data_flow 有 tables（含 role）+ dependencies + schedule_groups
- [ ] ts.md 是 ts.json 的投影（7章），字段部分只放概要
