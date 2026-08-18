---
status: active
last_reviewed: 2026-08-17
depends_on: [./01-逆向契约.md]
---

# baseline_v1 契约（正式版）

> 面向 dws-analyzer-skill 侧实施的接口规格。立场与推导过程见 [01-逆向契约.md](./01-逆向契约.md)；本文件是可执行的约定。**schema 文档与 JSON Schema 文件以 analyzer 仓为准**（与投影代码同仓维护），本仓 vendor 一份带版本拷贝做消费端校验。

---

## 一、定位与调用边界

- baseline_v1 = **纯物理事实包**（逆向产物），是优化场景外部资产的存量表示。
- **文件交接，不跨项目调用脚本**：analyzer 是 peer agent，资产定位 / 脚本演化 / 运行环境均归其侧；我方从契约校验开始，缺失 / 版本不符 fail loud。
- 消费方不感知输入模式（xlsx / 代码仓之别是生产侧的事），契约只有"事实 + 显式空"。
- 我方默认输入准确：**baseline_v1 必须反映线上实跑现状**（源文件与平台一致性由交付方保证），我方不做新鲜度校验。

## 二、内容规格

```
baseline_v1
├─ version                      必填      契约版本（双端校验锚点）
├─ asset                        必填      schema / table / rule_group_code / rule_group_en
│                                         dialect / source_type / analysis_time
│                                         platform_generation（平台代次）
├─ provenance                   必填      原始源文件定位信息（路径清单；交付方保证可达，
│                                         我方快照兜底仅作 patch 保险）
├─ rules[]                      必填      每规则：
│     rule_code / rule_name     必填      平台稳定标识
│     exec_sequence / scenario_id / is_common    必填
│     target_schema / target_table               必填
│     delete_mode / delete_condition             必填（无则空串，逐字原始值，不做语义归一）
│     merge_on                  dm=6 必供  MERGE ON 条件（实现来源是 analyzer 的自由）
│     query_sql                 ★必填     SQL 原文，逐字保真（禁美化/重排版；不可避免
│                                         的变换写入契约文档）
│     source_tables[]           必填      SQL 内物理表
│     joins[] / where_clause / group_by[]        必填（可空）结构化事实
│     is_view_step / exchange_source_table       可空
├─ tables[]                     必填      SQL 涉及全部表 {schema,name}；
│                                         fields[]{name,type,comment} 可选（DDL 缺则空，
│                                         类型回填由我方查库，仅用于全量 DDL 生成）
├─ lineage[]                    必填      {rule_code, target_field, transform_type,
│                                         raw_expr 逐字, physical_sources[]{table,field}}
│                                         CTE 穿透到物理源表
├─ schedule                     可空      任务/jobs/params（含增量变量）；无则显式 null
├─ dq_rules[]                   可空      编号/名/口径/check_type/SQL 原文
├─ load_strategy                必填      hint 级（资产级判定，非权威）
├─ patterns[]                   可空      hint 级加工模式提示
└─ warnings[]                   必填(可空)  逆向交叉验证差异事实（声明 vs SQL / DDL vs SQL /
                                          SQL 内在质量）——消费方式为我方报告+存档
```

**三级语义分级**：事实（必填或显式空）/ 判定 hint（load_strategy、patterns——非权威，供人参考）/ 语义（增量字段、驱动表、主键、粒度——**永不进契约**，归人回路）。

**枚举原始值原则**：delete_mode 等平台值逐字携带；**语义映射（→load_mode 等）归消费方**按 platform_generation 维护版本化映射表，平台迁移（如术加 1.0→2.0）时契约事实不变。

## 三、版本与变更协议

- 契约 schema 变更：version bump + 双端同步校验器与 vendor 拷贝；breaking change 提前约定。
- 运行时：消费方先对 version 字段，不支持即 fail loud。

## 四、fixture 与契约测试

- fixture 语料：全量两步链路 / 增量 merge（dm=6）/ 多场景分组 / I 视图封装——analyzer 侧生成，本仓 vendor 带版本拷贝。
- 双方各自 CI（不跨仓 import）：analyzer 断言 export 过 schema；本仓断言 adapter 消费 vendor fixture 成功。

## 五、analyzer 侧实施清单

1. `--export baseline_v1` 投影模式 + JSON Schema + 契约文档（放 analyzer 仓）；
2. 产出交付到约定交接路径（路径约定见双方使用文档）；
3. `merge_on` 抽取（dm=6 必供）；
4. 契约期望：反映线上实跑现状（交付方责任）；
5. 远期可选：补数任务发现、MERGE detail 细化。

> 注：mapping 标注载体**不在本契约内**——mapping 是业务侧交付物，我方只发布输入格式规格（mapping-format.md 扩展"变更标识"列）与交付方对齐。
