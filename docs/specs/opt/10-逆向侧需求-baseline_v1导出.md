---
status: active
last_reviewed: 2026-08-17
depends_on: [./09-契约-baseline_v1.md]
---

# 逆向侧需求：baseline_v1 导出能力（发 dws-analyzer-skill）

> 目标读者：analyzer 侧实施者。背景：design-dev-agent 新增**优化场景**（存量资产精确变更），需要 analyzer 产出 `baseline_v1`（纯物理事实包）作为外部资产的存量表示。接口契约全文见 `09-契约-baseline_v1.md`（双端共同定稿）；本文是**实施需求**：做什么、映射怎么走、验收是什么。
> 本文档与 vendored schema（`baseline_v1.schema.json`）+ fixture（`baseline_v1_demo_full.json`）一起构成交接包。

---

## 一、需求范围

**做**：`analyzer` 新增导出模式 `--export baseline_v1`——在现有解析（knowledge_draft）之上投影出契约文件。**纯增量能力**：现有 knowledge_draft 与三视图产出一个字节不改。

**不做（非目标）**：
1. **不猜语义**——增量字段、驱动表、主键、粒度这些判断永不进产物（哪怕解析时能推测）；
2. mapping 视图不在本需求内（mapping 是业务侧交付物，与 analyzer 的协作由业务侧定）；
3. 优化场景怎么消费 baseline_v1 不归本需求管。

## 二、行为要求（硬约束）

1. **逐字保真**：`query_sql`、`raw_expr`、`delete_condition` 逐字节保留解析原文——不美化、不重排版、不规范化大小写。这是消费方围栏比对/SQL 审计的地基。
2. **显式空**：拿不到的信息 = 显式 `null` 或空数组，**不省略 key**（如 xlsx 输入模式无调度 → `"schedule": null`）。缺口显式化是契约原则，静默省略会让消费方无法区分"没有"和"忘了"。
3. **自校验后落盘**：export 产物先过仓内权威 schema 校验，不过 fail loud 不写文件。
4. **CLI 与输出路径**：
   ```
   python run.py analyzer --input {xlsx或代码仓目录} --output {dir} [--ddl-dir D] \
                          --export baseline_v1 [--platform-generation 1.0]
   ```
   产物为 `{dir}/baseline_v1.json`（若沿用按规则组建子目录的惯例，**stdout 打印最终绝对路径**，消费方解析该行定位文件）。
5. **platform_generation**：平台代次（当前 "1.0"），CLI 参数或配置，默认 "1.0"。平台迁移（2.0）时此处变值，产物其余结构不变。

## 三、字段映射表（knowledge_draft → baseline_v1）

| baseline_v1 | 来源（knowledge_draft） | 变换说明 |
|-------------|------------------------|---------|
| `version` | 常量 `"1.0"` | 契约版本，与仓内权威 schema 同步 |
| `asset.schema` / `asset.table` | `meta`（目标表；demo=`dws`/`dwb_trade_order_d`） | 最终目标表（F 表） |
| `asset.rule_group_code` | `meta.rule_group_code` | 直投 |
| `asset.rule_group_en` | 规则组英文名称（输出子目录名来源） | 直投 |
| `asset.dialect` / `source_type` / `analysis_time` | `meta.dialect` / `meta.source_type` / `meta.analysis_time` | 直投 |
| `asset.platform_generation` | CLI/配置 | ★新增（见 §四-3） |
| `provenance[]` | 解析过程消费的源文件清单 | ★新增（见 §四-1；`lts_file`/`dq_file` 已在 meta 里，补 xlsx/yml/ddl 的记录） |
| `rules[].rule_code/rule_name/exec_sequence/scenario_id/is_common` | `topology.steps[]` | 直投 |
| `rules[].target_schema/target_table` | `topology.steps[]` | 直投 |
| `rules[].delete_mode / delete_condition` | `topology.steps[]` | **逐字原始值**，不做任何归一 |
| `rules[].merge_on` | ★新增抽取（见 §四-2） | dm=6 时必供 |
| `rules[].query_sql` | `source.raw_sql[].sql`（或 `data_flow.steps[].raw_sql`） | **逐字** |
| `rules[].source_tables[]` | `topology.steps[].source_tables_from_sql` | schema.table 形态 |
| `rules[].joins[]` | `data_flow.steps[].joins` | 字段对应（source_table/alias/join_type/join_condition） |
| `rules[].where_clause / group_by` | `data_flow.steps[].where_clause / group_by` | 直投 |
| `rules[].is_view_step` | `topology.steps[].is_view_step` | 直投 |
| `rules[].exchange_source_table` | `topology.steps[].exchange_temp_table` | **改名**（temp→source） |
| `tables[]` | `data_flow.tables`（schema/name；role 不进契约） | 覆盖 SQL 涉及全部表 |
| `tables[].fields[]` | DDL 解析结果（目标表可用 `meta.target_field_types/comments` 兜底） | DDL 缺 → 空数组（消费方查库回填） |
| `lineage[].rule_code / target_field / transform_type` | `field_mappings.fields[]` | 直投 |
| `lineage[].raw_expr` | `field_mappings.fields[].lineage[].raw_sql` | **逐字**（改名 raw_sql→raw_expr） |
| `lineage[].physical_sources[]{table,field}` | `field_mappings.fields[].physical_source` | **裁剪**：只留 table/field（step_id/alias/transform 等附加字段不进契约） |
| `schedule` | `meta.schedule`（建议只投 f_tasks/i_tasks/other_tasks，all_tasks 冗余可裁） | xlsx 模式 → `null` |
| `dq_rules[]` | `meta.dq_rules`（保留 rule_number/name/desc/check_type/alert_level/sql/target_table；dq_file 进 provenance） | 直投 |
| `load_strategy` | `meta.load_strategy` | hint 级原样（消费方标注非权威） |
| `patterns[]` | `meta.patterns` | 直投 |
| `warnings[]` | `field_mappings.warnings` + `quality.issues`（type 字段区分两类） | 消费方用途=报告+存档 |

## 四、需要 analyzer 侧新增/补强的三个点

1. **provenance 记录**：解析过程中把实际消费的源文件（输入 xlsx / 代码仓 yml 列表 / DDL 文件 / LTS yml / DQ yml）记成 `{type, path}` 清单。LTS/DQ 路径已天然可得，主要是把 xlsx/yml/ddl 的消费记录补上。
2. **merge_on 抽取**（dm=6 必供）：来源自定（delete_condition 列 / SQL 文本 / 平台配置推导均可），但 delete_mode=6 的规则产物里 merge_on 必须非空——消费方有语义校验会拦。
3. **platform_generation 参数**：见 §二-5。

## 五、schema 与版本协议

- **初始权威 schema**：直接以交接包里的 `baseline_v1.schema.json`（vendor 版）为 v1.0 权威拷贝入 analyzer 仓，此后权威随 analyzer 仓维护，消费方 vendor 同步。
- 版本变更：schema 改动 → bump version + 通知消费方同步 vendor 拷贝与校验器；breaking change 提前约定。
- 双端各自 CI 校验（不跨仓 import）：analyzer 断言 export 过权威 schema；消费方断言 vendor fixture 通过其校验器。

## 六、验收标准

1. **demo 资产**（DWB_TRADE_ORDER_D，两步链路）export 产物通过消费方 vendored schema + `baseline_contract` 校验器（消费方 fixture `baseline_v1_demo_full.json` 可作值对照基准——同一 demo 数据的期望投影）；
2. `query_sql` 与代码仓 yml / 制品包原文**逐字节一致**；
3. xlsx 输入模式产物：`schedule: null` 显式存在；
4. 增量 merge 用例（dm=6）：`merge_on` 非空且通过消费方语义校验；
5. **现有能力零回归**：knowledge_draft / mapping.xlsx / asset_report.html / tech_design.md 产出与改造前一致（analyzer 现有测试全绿）。

## 七、交接清单

| 交接物 | 位置（消费方仓） |
|--------|----------------|
| 本需求文档 | `docs/specs/opt/10-逆向侧需求-baseline_v1导出.md` |
| 契约全文 | `docs/specs/opt/09-契约-baseline_v1.md` |
| 初始权威 schema | `skills/design-dev-shared/schemas/baseline_v1.schema.json` |
| demo 基准 fixture | `tests/fixtures/opt/baseline_v1_demo_full.json` |
| 消费端校验器（语义检查参考） | `skills/design-dev-shared/scripts/baseline_contract.py` |
