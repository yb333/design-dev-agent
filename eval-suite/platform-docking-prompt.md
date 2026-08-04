# 平台对接调研提示词（内网使用）

> 用途：在内网电脑上，让 agent 摸清"打通平台的脚本"需要什么输入，
> 对照本仓的产出（ts.json + SQL），定出两边对接的契约格式。
> 这是一次**探路**，目标是产出一份契约文档，不是马上写代码。

---

## 背景：为什么要先调研再写代码

外网仓（design-dev-agent）产出的是 ETL 制品的"源料"：
- `ts.json`（设计权威源，含调度信息、规则、字段）
- `etl/R0001.sql`（纯 SELECT）
- `ddl/create_table_*.sql` / `create_view_*.sql`
- `ddl_rollback/rollback_*.sql`

**缺的是 exporter**——把这些源料打包成平台能消费的格式。
平台要什么格式，目前不确定。内网有"打通平台的脚本"，能跑通就知道平台要什么。

所以这次的任务：**用内网脚本跑通一个案例 → 反推平台需要的输入 schema → 定义契约**。

---

## 提示词（复制以下全部内容给内网 agent）

你在内网环境，任务是**摸清平台对接的输入契约**。

### 第一步：理解我们这边的产出

先读这几个文件，理解外网仓产出了什么、结构是什么：

1. **TS 制品格式定义**（最核心）：
   `docs/specs/ts-format.md`
   重点看 `meta.schedule` 段（task_name / cron / project / task_group / exec_params / upstream / execution_platform）——这是调度信息的权威源。

2. **新结构完整产出样本**（看真实数据）：
   `10_project_deliver/dwb_trade_wide_f/ddlc_design_dev/ts.json`
   看 `meta.schedule` 段实际值、`rules` 段结构、`meta.target` 目标表。

3. **旧示例的 export 制品**（平台对接的历史影子）：
   `docs/output/dwl_con_pu_any_f/09_export/export_manifest.json`
   这是旧版 exporter 产出的 manifest。**注意：旧版 exporter 已删除，新 exporter 还没写**。
   但这个 manifest 揭示了平台曾经需要哪些字段（task_name / job_name / project / cron / params / upstream_tasks / view_task_name），有参考价值。

4. **架构文档的对接章节**：
   `docs/architecture/architecture.md` 的"§四 螺旋回路"和"§3.2 制品能力（适配器模式）"
   理解：当前是"绕过平台直连库"的过渡态，目标是 exporter 产中间表达 → 平台适配器部署。

### 第二步：摸清内网平台脚本的能力

找到内网那个"打通平台的脚本"（Python），搞清楚：

1. **它的输入是什么**？命令行参数？配置文件？读哪个文件？
   - 把它接受的输入字段全列出来（字段名、类型、必填/可选）
2. **它推到平台后，平台那边创建的是什么**？
   - 一个"任务"（task）？一个"作业"（job）？一个"调度"（schedule）？
   - 推送成功后，平台返回什么？
3. **它现在能处理哪些操作**？
   - 只能推送 ETL 任务？还是也能推 DDL / DQ / 调度配置？
   - 能不能反向查询（如查任务是否存在、查执行状态）？
4. **它需要什么认证/配置**？
   - 连接信息从哪来？跟我们的 db-sources.json 是什么关系？

### 第三步：对照——我们有什么 vs 平台要什么

列一张映射表，三列：

| 平台需要的字段 | 我们 ts.json 里的来源 | 缺口 |
|---|---|---|
| （平台脚本要的字段） | （ts.json 对应路径，如 meta.schedule.task_name） | （有 / 需派生 / 完全没有） |

特别关注这些**可能需要派生的字段**：
- `job_name`（Pjob_ 前缀）——旧 manifest 有，ts.json 没有，可能要 exporter 派生
- `view_task_name` / `view_job_name`——从 rules 里 is_view_step=true 的规则推导
- `upstream_tasks` 的 `schedule_task` / `exec_path`——ts.json 的 upstream 结构可能不同
- `params`——ts.json 的 exec_params 现在含 P_CYCLE_ID，但平台可能要不同的参数名（如 V_CYCLE_ID）

### 第四步：产出契约文档

写一份 `docs/specs/platform-contract.md`，包含：

1. **平台输入 schema**（字段清单 + 类型 + 含义 + 必填可选）
2. **字段映射表**（上面那张三列表）
3. **缺口清单**（ts.json 里没有的、需要 exporter 派生的字段）
4. **契约文件格式建议**（exporter 产出什么文件给平台 skill 消费）
   - 建议名字：`platform_manifest.json`（或沿用旧名，看你）
   - 放在哪：`10_project_deliver/{资产名}/ddlc_design_dev/` 下（跟 ts.json 同级）
5. **skill 对接约定**（两边 skill 名称 + 输入路径约定）
   - 如：本仓产 `platform_manifest.json`，内网 skill 名 `platform-push`，读 `{资产目录}/platform_manifest.json`

### 第五步：跑通一个案例验证（如果时间够）

用内网平台脚本，手动构造一个最小输入（照着 `dwb_trade_wide_f` 的 ts.json 填），试着推一次。
记录：哪些字段是必填的、推送后平台创建了什么、返回什么。

**不要改本仓代码**——这次只调研、定契约。exporter 的实现是下一步的事。

---

## 给做调研的 agent 的提示

- **不要急着写 exporter 代码**。先搞清楚"平台要什么"。
- 旧 manifest（`export_manifest.json`）是**参考**不是**标准**——平台可能已经变了，以实际跑通为准。
- 如果平台脚本的输入跟 ts.json 差距很大，不要硬改 ts.json 去迎合——记下来，这是 exporter 要做的翻译工作。
- 重点关注**参数名差异**（如 P_CYCLE_ID vs V_CYCLE_ID）、**job_name 派生规则**、**多规则场景**（tmp 中间表 + f 目标表 + i 视图，平台怎么组织）。
- 契约文档写到 `docs/specs/platform-contract.md`，这是两边对接的唯一权威。
