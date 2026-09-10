# LTS 制品包生成设计（v1 定稿）

> **状态**：设计定稿（2026-09-09 与用户对齐），实现未开始。
> **规律依据**：[ltsjob构建规律.md](./ltsjob规律总结/ltsjob构建规律.md)（451 样本照片转写，唯一文本源，本文件不重复其内容）。
> **范围**：`assemble_export.py` 的 `generate_schedule_excel` 重写 + 设计侧上游声明小增强 + config 新增 lts 段。术加通道（execution xlsx）不动；lts xlsx 列结构不动（平台模板已对齐），重写格子填充。

---

## 一、目标与范围

**做什么**：生成 `lts_{表名}.xlsx`（3 sheet：tasks / jobs / taskParams），内容按规律全集对齐——任务级参数带确定性值模板、主 job 参数模板形状修正、tskdep 补路径与 JSON 全套、虚拟依赖按正确形态条件生成、视图任务改 database 占位 job、增量资产补 GETDATE。

**不做什么**（出范围，见 §十一）：
- FILTER 工具对（GETDATE_INFO/UPDATE_INFO）——仅"带 filter"任务需要，我们无此场景
- group 组节点及其 `G_xxxx|` 前缀抽取 job——仅并行抽取场景
- ANALYZE job
- DQ 任务提交对象悬空问题（DQ 规则行不进术加包）——**另立工作线**，本次 DQ 任务行维持现状形态
- depTaskId 自动生成（跨集群平台 id，输入不可推导）——出厂留空，人核回填

**覆盖的 job 类型**：主 job（url/`${V_URL}`）、tskdep、虚拟依赖（url/`${V_URL_virtualDependence}`，条件生成）、database（视图占位 / GETDATE 简化版）。

## 二、核心定调（对齐会话结论，实现时不得偏离）

1. **环境差异走项目变量，例外=本集群名**：生成物不做 `--env`。有平台变量的值（V_URL/V_TOKEN/抽取目标集群等）一律写变量引用；**本集群名没有平台变量**（用户明确），作为 config 字面量、默认写生产 `fin_pro`（与 dbsource"先写生产"同思路；测试 BIZBAETA / 开发 LTSBETA 记录在 config 注释，按需切换）。
2. **平台变量 = 项目级变量**：`V_URL`/`V_TOKEN`/`P_CLUSTER_EDW_PRO` 等是平台配置的项目级变量（大部分租户/组织级公共），生成物只引用不定义。
3. **tskdep 行归属恒 = 当前任务**：项目名称/任务组名称/任务名称三列填本任务的，上游定位全在执行路径 4/5 段里。
4. **V_FLAG 非固定参数**：仅"增量 + 单规则组 + 变量控跳过"场景才有，由 designer 设计决定，ts.json 驱动条件生成。
5. **V_CYCLE_ID = 数据日期（T-1），锚计划时间**（方案 A）：`$getTaskPlanTime(plantime,@@yyyyMMdd000000@@,-24*60*60)`——补调历史周期时每周期批次正确回填。
6. **虚拟依赖全名直传零推导**：job 名（含源系统编号/版本戳/后缀）由输入提供，缺失 fail-loud，不做拼接兜底。
7. **参数值字面量**：格式串定界 `@@…@@`，偏移秒负数往回（已实证）。
8. 命名固定规范：task=`task_{表名}`；job 名以 ts.tasks.job_name 为唯一锚（设计期盖章 `Pjob_{表名}`，跟随表名小写——平台对大小写不敏感，照片规律明示"不要只看 job 名大小写"）。
9. **一期生成只面向生产**（用户拍板）：测试/开发环境的集群名与 depTaskId 均不同（上游任务测试环境约六成存在）——二期视痛点加 `--env`+重写表（输入仍对齐生产单源，重写为生成末端确定性替换）；本期把集群名/depTaskId 取值收在 builder 单点函数，为二期留口。

## 三、任务组合模型

每个任务按资产形态组装 job 集（`←` 依赖方向：后者等前者）：

```
f 任务（增量资产）:  GETDATE(database,父=start) ← 主job(url,父=GETDATE) ← tskdep×N(父=主job)
f 任务（全量资产）:  主job(url,父=start) ← tskdep×N
view 任务:          占位job(database,父=start) ← tskdep×1(父=占位job,声明task_f)
dq 任务:            主job(url,父=start) ← tskdep×N          [形态维持现状]
init 任务:          主job(url,父=start)，无上游              [一次性表示照抄现状:周期任务+cron]
```

- **GETDATE 生成条件** = 资产为增量（ts 有 init 段或 RS 增量声明）。全量资产不生成。
- **主 job 父节点**：有 GETDATE 写 `GETDATE`（单值，定稿），否则 `start`。
- **tskdep 父节点** = 本任务主 job（view 任务=占位 job）；job 名称 = 上游任务名（路径末段）。
- view/dq/init 任务的 taskParams 与 f 任务同配（约定参数每个任务必配）。

## 四、逐类 job 生成规格

> 列名为 jobs sheet 的列。未提到的列一律留空（集群名称/datastage日志级别/job资源设置/job扩展属性/生产执行路径/生产job中断处理/生产schema/组件资源/job描述/job中断处理）。
> **所有 job 行恒填三列**（照片"通用属性"）：`job执行节点=任一节点`、`job异常处理方式=fail`、`参数空值校验=否`。

### 4.1 主 job（f/dq/init 任务的执行行）

| 列 | 值 | 来源 |
|---|---|---|
| job名称 | ts.tasks.job_name（设计期盖章 `Pjob_{表名}`） | ts.json |
| job类型 | `url` | 常量 |
| job的父节点名称 | `GETDATE` 或 `start` | 按 §三 |
| 执行路径信息 | `${V_URL}` | 变量引用 |
| job参数 | 8 键 JSON（下表） | 模板 |
| job调用方法 | `POST` | 常量 |
| job超时时间/重试次数/重试间隔 | `60`/`3`/`60` | 常量 |
| job是否跳过清场 | `跟随任务` | 常量 |
| job超时处理 | `一次邮件提醒` | 常量 |

job参数 8 键（修正点：现状模板是虚拟依赖形态，此处按主 job 形态）：

```json
{"headers":"Content-Type:application/json;charset=UTF-8",
 "invokingMode":"异步",
 "retVal":"",
 "jobRunParams":"{内嵌JSON，见下}",
 "appToken":"${V_TOKEN}",
 "appId":"${V_APPID}",
 "authenticationType":"手动输入",
 "timeout":10}
```

jobRunParams 内嵌 JSON 固定 4 键：

```json
{"batch_number":"${V_BATCH_NUMBER}",
 "group_code":"${V_GROUP_CODE}",
 "sch_from":"${V_SCH_FROM}",
 "params":[{"name":"{etl_param}","type":"constants","value":"${lts_var}"}, ...]}
```

**params 数组内容 = ts.json `meta.schedule.lts_params` 直译**（V→P 映射，designer 声明；`etl_param` 为空的条目不进数组）。默认两条：V_CYCLE_ID→P_CYCLE_ID；V_FLAG→P_FLAG（仅增量+单规则组+变量控跳过场景由 designer 加入）。

### 4.2 tskdep（每条上游一行）

> **场景矩阵（2026-09-09 与用户定调收敛——只支持两个常态格）**：
> - ① **同集群 · task 级**（资产内 I→F）：4 段路径，job名称/name=depTaskName=任务名，depJobName=`"end"`（挂任务结束节点），无 id。
> - ② **跨集群依赖**（f 上游湖表依赖，主场景）：5 段路径（末段=任务名），
>   job名称/name/depJobName=**upstream.job**（输入直传的依赖引用名，多为 job 名——仅显示/引用，不参与 id 定位）；
>   **depTaskId 与 task 同粒度**（2026-09-09 用户终稿更正，非 job 级），键四段「集群|调度组|任务组|任务名」。
> - ③ 同集群·job 级 / ④ 跨集群·task 级：**无真实案例，不支持**（用户拍板"先不管，遇到再说"）；**跨集群⇒job 必填**是输入校验（缺 job fail-loud，job 是引用名）。
> - 依赖大部分跨集群（上游在别的团队的集群），②是主场景；同集群主要是资产内依赖（如 view→f）走①。
> - **id 来源（2026-09-09 终稿）**：内网脚本仅开发环境可跑而制品对齐生产，生产 id 拿不到——**脚本路搁置**；
>   当前唯一常态来源 = **config `dep_task_ids` 显式表人工维护**（人上平台查得后填，或请平台导全量表灌入——同一结构；id 稳定填一次永续复用）；
>   resolver 契约保留为**预留口子**（平台开放接口后配 script 即启用，代码零改动）。

| 列 | 值 |
|---|---|
| 项目名称/任务组名称/任务名称 | **当前任务**的（不是上游的——现状 F 表上游写法要改） |
| job类型 | `tskdep` |
| job的父节点名称 | 本任务主 job（view 任务=占位 job） |

**同集群（4 段路径 `{appId}|{项目组名}|{任务组}|{任务名}`）**：
- job名称 = name = depTaskName = 路径末段（upstream.task）；depJobName = `"end"`
- 路径 = upstream `app/project/group/task` + appid 反查
- depTaskId 无

**跨集群（5 段路径 `{生产集群}|{appId}|{itemName}|{taskGroupName}|{depTaskName}`）**：
- job名称 = name = depJobName = **远端真实 job 名**（upstream 新字段 `job`，输入直传——⚠️ 字段规则表说 name=路径末段，但样本②实测跨集群 name=远端 job 名，以样本为准）
- depTaskName = 路径末段（upstream.task）
- 路径首段 = upstream 新字段 `cluster`（生产集群名，输入直出）
- **depTaskId = config 直读**：`lts.dep_task_ids` 表（人上平台查得后填——唯一来源；**全局，不参与 schema 覆盖**），键=四段「集群|调度组|任务组|任务名」（id 与 task 同粒度——用户终稿更正；upstream.job 只是引用名不参与定位）；**缺键跳过该依赖行**（不阻断生成，制品可导入，末尾汇总打印跳过清单+补填指引——人补 config 重出或平台手工加依赖）。外部接口获取为预留（对接规范见 [lts-deptaskid脚本契约.md](./lts-deptaskid脚本契约.md)，平台开放接口后按契约接回）。
- productionClusterName = 路径首段；crossClusterDepName = 路径首段；crossClusterDepKey = `{集群}|{pro\}` `[?]`字面量待样本核对；crossClusterSrcName = 本集群名字面量

**job参数 JSON 全量键**（两种场景共骨架，按上述差异填充）：

```json
{"type":"tskdep",
 "mainJobName":"{父job名}",
 "depJobName":"end 或 远端job名",
 "name":"{路径末段 或 远端job名}",
 "depTaskName":"{路径末段}",
 "productionClusterName":"{本集群名 或 路径首段}",
 "declarativeDependency":0,
 "breadthSenior":["0"],
 "groupOk":"",
 "start":"",
 "depTaskGroupType":0,
 "rangeSenior":[],
 "dotSenior":[],
 "hourList":[],
 "crossClusterDepKey":"",
 "crossClusterDepName":"",
 "crossClusterSrcName":"{本集群名}",
 "applyName":"",
 "itemName":"{项目组名 或 路径第3段}",
 "taskGroupName":"{任务组 或 路径第4段}"}
```

- **本集群名 = config 字面量**（默认生产 `fin_pro`；本集群无平台变量——用户定调），同集群两集群字段同值。
- `applyName`：字段规则表说"同集群=项目组名"，但样本①为空；跨集群样本是业务域英文名（DIMSVR/Procurement），输入侧无此字段——**生成默认留空**（宁照样本），内网核对后调（§十一）。
- 工程属性列（超时/重试/间隔）：照片未给 tskdep 规格，**留空**，内网核对（§十一）。

### 4.3 虚拟依赖（条件生成：upstream 项 `dep_type=虚拟依赖`）

| 列 | 值 |
|---|---|
| job名称 | **输入直传的完整 job 名**（upstream 项新字段 `job`，如 `PJob_EXT_2500_FND_LOOKUP_VALUES_T_MP002442023051000179_D2S`） |
| job类型 | `url` |
| job的父节点名称 | `start`（挂主 job 抽取链时按 §三链路） |
| 执行路径信息 | `${V_URL_virtualDependence}` |
| job参数 | 8 键：headers/appToken/appId **全空**、invokingMode=异步、retVal=""、authenticationType=无、timeout=10、jobRunParams=下 |
| job调用方法 | `POST` |
| 工程属性 | 60/3/60；跳过清场=跟随任务 |

jobRunParams = URL query 形态（`&` 连接）固定 8 键：

```
clusterName=${P_CLUSTER_EDW_PRO}&appId={upstream.app}&itemName={upstream.project}
  &taskGroupName={upstream.group}&taskName={upstream.task}
  &jobName={本job自身名,自指}&begin=${BEGIN_TIMES}&end=${END_TIMES}
```

**`job` 字段缺失 → fail-loud 报人补，零拼接兜底。**

### 4.4 database · 视图占位 job（view 任务）

| 列 | 值 |
|---|---|
| job名称 | ts.tasks.job_name（`Pjob_{i_view表名}`） |
| job类型 | `database` |
| job的父节点名称 | `start` |
| 执行路径信息 | `SELECT 1 FROM {schema}.{i_view} WHERE 1 = 2`（I 是视图，存在即可查，语义同样本的 _I 表） |
| job参数 | 6 键：`schema={目标schema}`、`dbsource=[*].[{config库名}]`、`datasourceTypeName=gauss200`、`retVal/inParams/outParams=""` |
| job调用方法 | `sql` |
| 工程属性 | 10/3/1；跳过清场=`否` |

> dbsource 定调：一个租户一个库源、跨环境同名，仅 `[*]` 前缀随环境变（生产=PRD/测试=UAT）。样本真实件里写的就是 `[*]`，故**照样本原样生成 `[*]`**（即平台按环境解析的占位，天然 env-neutral）；若内网验证 `[*]` 不被解析，按用户建议切生产字面量 `[PRD].[库名]`——config 一改即切。

### 4.5 database · GETDATE（f 任务，增量资产）

| 列 | 值 |
|---|---|
| job名称 | `GETDATE` |
| job类型 | `database` |
| job的父节点名称 | `start`（我们无组/FILTER 汇聚链） |
| 执行路径信息 | 简化版 SQL：`SELECT to_char(sysdate,'yyyy-mm-dd hh24:mi:ss') AS DW_LAST_UPDATE_DATE, '${V_CYCLE_ID}' AS CUR_CYCLE_ID`（V_CYCLE_ID 已是 yyyyMMdd000000，无需拼接；照片简化版只出这两列） |
| job参数 | 6 键同 §4.4 |
| job变量设置 | `P_DW_LAST_UPDATE_DATE=DW_LAST_UPDATE_DATE;P_CUR_CYCLE_ID=CUR_CYCLE_ID`（设计引用 V_FLAG 时追加 `;P_FLAG=P_FLAG`） |
| job调用方法 | `sql` |
| 工程属性 | 60/3/60；跳过清场=`跟随任务`；超时处理=一次邮件提醒 |

## 五、taskParams 规格

**基础全集**（每个任务恒配，值模板为确定性表达式）：

| 参数 | 值模板 |
|---|---|
| V_BATCH_NUMBER | `$getJobUUID(jobUUID)` |
| V_GROUP_CODE | **规则组编码占位符 `GR_{表名}`（资产级）**——业务组=规则组（2026-09-10 用户定调），值依赖术加平台取码回填：占位符与 RULE sheet 规则组编码同款，内网取码脚本一次回填管两处；init 任务（separate）用 `GR_{表名}_init` |
| V_SCH_FROM | `LTS` |
| V_CYCLE_ID | `$getTaskPlanTime(plantime,@@yyyyMMdd000000@@,-24*60*60)`（**方案 A 定稿**） |
| BEGIN_TIMES | `$getTaskPlanTime(plantime,@@yyyy-MM-dd 00:00:00@@)` |
| END_TIMES | `$getTaskPlanTime(plantime,@@23:59:59@@)` |
| V_DW_LAST_UPDATE_DATE | `$getCurrentTime(@@yyyy-MM-dd HH:mm:ss@@,0)` |
| V_APPID | appid **字面量**（schema_apps 反查；一租户绑定一 appid，跨环境相同——用户定调） |

**条件项**：

| 参数 | 生成条件 | 值 |
|---|---|---|
| V_FLAG | ts.json 引用（designer 声明：增量+单规则组+变量控跳过） | designer 给的常量（如 `1`） |
| V_RENTER_CODE / V_RENTER_ID | config 配了租户标识才生成 | config 字面量（**用户定调：租户标识是某些任务的设计，暂不配**→默认不生成） |

**不进 taskParams**（平台项目级变量，只引用）：V_URL、V_URL_virtualDependence、V_FILTER_*（本次不用）、V_TOKEN、P_CLUSTER_*。

## 六、字段级来源对账

| 生成内容 | 来源 | 状态 |
|---|---|---|
| 任务骨架（task_name/job_name/cron/project_name/task_group） | ts.json meta.schedule.tasks（lts_config 任务路径段设计期盖章） | ✅ 已有 |
| tskdep 路径 4 段 | upstream 项 app/project/group/task + schema_apps 反查 appid | ✅ 已有 |
| params 数组内容 | ts.json meta.schedule.lts_params（designer V→P 声明） | ✅ 已有 |
| V_FLAG 及取值 | designer 增量决策（ts.json 驱动） | ✅ 已有通道 |
| 跨集群集群名 / 远端 job 名 / 虚拟依赖 job 全名 | upstream 项 `cluster` / `job`（新增字段，输入直传） | ➕ 增强两字段 |
| depTaskId（跨集群） | config `dep_task_ids` 查表（三元组固定，补一次永久生效） | ➕ 新增查表 |
| 本集群名、库名、业务组编码 | platform_config `lts` 块（default.consts + schema_mappings 按 schema 覆盖；本集群默认生产 fin_pro；租户标识/业务组编码暂空不生成——用户定调） | ➕ 新增 |
| V_APPID 值 | schema_apps 反查 appid 字面量（租户绑定，跨环境同） | ✅ 已有 |
| 值模板表达式 / 8键6键形态 / 工程属性 | 本文件 §四§五 常量表（依据规律文档） | ✅ 定稿 |
| depTaskId（跨集群） | 人核回填 | ⛔ 不可生成 |

## 七、config 设计

独立 `lts_config.json`（2026-09-10 自 platform_config 拆分——该文件更名 shujia_config 只含术加内容；config_paths.lts_config_path 单点定位）：

```json
"lts": {
  "default": {                   // consts=默认字面量
    "consts": {
      "cluster_local": "fin_pro",  // 本集群名（无平台变量——用户定调；测试=BIZBAETA / 开发=LTSBETA 按需切换）
      "db_name": "GAUSS_EDW_BFD_BNIL", // database job 库名（[*] 前缀平台按环境解析 PRD/UAT）
      "datasource_type": "gauss200"
    }
  },
  "schema_mappings": {           // 按目标 schema 覆盖 consts（任务所在项目/库名/编码与 schema 挂钩——只覆盖差异键）
    "fin": { "consts": {} }
  },
  "dep_task_ids": {              // 跨集群 tskdep 的 depTaskId 表——★全局，不参与 schema 覆盖（依赖的任务唯一与 schema 无关）。exporter 直读（id 与 task 同粒度）：键="集群|调度组|任务组|任务名"（四段）。人上平台查得后填/平台导全量表灌入，id 稳定填一次永续复用；**缺键跳过该依赖行**（不阻断生成，末尾汇总提示）
    "示例集群|示例调度组|示例任务组|示例任务名": "20224946"
  }
}
```

- `appid` 不进 config：V_APPID 值 = schema_apps 反查的字面量（一租户一 appid，跨环境相同——用户定调）。
- **三套环境集群名（用户口径）**：生产 `fin_pro` / 测试 `BIZBAETA` / 开发 `LTSBETA`——我们建的任务都在这三个集群下；上游依赖大部分在**别的集群**（各 upstream 声明自带集群信息，RS 输入提供来源任务信息——用户确认）。
- 租户标识（V_RENTER_*）：用户定调"某些任务的设计，暂不管"→ consts 不配则不生成。
- **depTaskId = 显式表直读**（无缓存/无脚本——独立取值脚本与缓存机制随脚本路搁置一并移除，2026-09-09 内联定稿；外部接口预留见 §4.2）。
- **三合一终态（2026-09-10 定稿）**：schedule_config（任务路径）并入 lts_config 退役——LTS 配置都是平台上已存在的事实（同域），设计期/导出期只是消费时机。default/schema_mappings **平铺层**共存两类键（两消费者键不重叠互不干扰）：任务路径（project_name/task_group + init/dq 任务种类子键，两维度嵌套——assemble_ts 盖章进 ts 后冻结）+ 导出期键（cluster_local/db_name，schema 浅合并覆盖差异键；V_GROUP_CODE 是资产级规则组编码不在此——出厂 GR_ 占位符由内网取码回填）；`dep_task_ids` 全局段（依赖的任务唯一，与 schema 无关——隔离在覆盖链外已用测试钉住）。appid 不在本文件（schema_apps.json 反查）；datasource_type 纯常量归代码。
- 不做环境维度、不做 `--env`（一期面向生产；二期预留见 §二.9）。

## 八、设计侧改动（assemble_ts / RS 声明）

1. **upstream 项增强**（RS @upstream / designer upstream_added 同步）：
   - `job` 字段（**跨集群 tskdep 与虚拟依赖共用**，语义=依赖引用名直传）：跨集群 tskdep=依赖引用名（name/depJobName/本行 job名称 三处同值，多为 job 名——仅显示/引用，id 是 task 级不参与定位）；虚拟依赖=抽取 job 完整名（含编号/版本戳/后缀，本行命名+jobRunParams 自指）。跨集群 tskdep 与虚拟依赖时必填，缺失 fail-loud（**跨集群⇒job 必填**是输入校验）。同集群（task 级）不读该字段。
   - `cluster`（跨集群 tskdep 时必填）：上游所在生产集群名（5 段路径首段）——**RS 输入已提供来源任务相关信息（用户确认）**，优先复用 upstream 现有字段（`env` 预计即集群名，实现时以真实 RS 样本核对映射）；designer upstream_added 显式支持。
2. **V_FLAG 声明通道**：复用 `lts_params`（designer 在 decisions.schedule.lts_params 加 `{lts_var: V_FLAG, etl_param: P_FLAG, desc: ...}` + 值）——机制已有，SKILL 指引补"何时加 V_FLAG"一句。
3. **depTaskId 不进输入**：config 显式表直读（§七）。
4. 其余设计侧不动（任务骨架/路径原料/cron 均已具备）。

## 九、出厂校验（生成后即跑，硬阻断）

1. **${V_XXX} 引用闭合**：所有 job 格子（job参数/执行路径/变量设置/SQL）里出现的 `${V_XXX}` 引用 ⊆ 该任务 taskParams 定义集。（照片 §2 铁律）
2. **父节点引用闭合**：每行 `job的父节点名称` ∈ {start, EMPTY} ∪ 本任务已生成 job 名集合。
3. **tskdep 路径完整**：4 段或 5 段各段非空（appid/project/group/task 任一缺失 → 指名报哪条上游；跨集群另要求 `cluster`+`job` 字段非空）。
4. **depTaskId 取得**：跨集群 tskdep 的四段键在 config `dep_task_ids` 无命中 → 跳过该依赖行（不阻断），stdout 汇总跳过清单（任务名+四段键+补填指引）。
5. **P_ 变量供给链**：术加 RULE 行运行条件引用的 `${P_XXX}` ⊆ 主 job params 数组供给的 P_ 变量集 ⊆ taskParams 定义集。（堵现状 P_FLAG 静默断供）

## 十、模拟案例（实现后的验收基准）

**案例 A：全量资产 dwb_user_center_f**（f 无上游）

- tasks：task_dwb_user_center_f、task_dwb_user_center_i 两行（同现状）
- jobs 3 行：
  1. `Pjob_dwb_user_center_f`（url，父=start，`${V_URL}`，主 job 8 键，POST，60/3/60，跟随任务）
  2. `Pjob_dwb_user_center_i`（database，父=start，`SELECT 1 FROM {schema}.dwb_user_center_i WHERE 1=2`，6 键，sql，10/3/1，否）
  3. tskdep：job名=`task_dwb_user_center_f`，父=`Pjob_dwb_user_center_i`，路径=`{appid}|SRP_DAILY|GROUP_SPRD|task_dwb_user_center_f`，tskdep JSON 全套；行首三列=task_i 所属
- taskParams：两任务各 8 项基础全集（V_FLAG 不生成——全量且无变量控跳过设计）

**案例 B：增量资产 delta（相对案例 A）**

- f 任务 +1 行 GETDATE（database，父=start，简化版 SQL 两列，变量设置桥接）
- 主 job 父节点 start→`GETDATE`
- designer 声明了 V_FLAG→P_FLAG 时：taskParams + V_FLAG 行（值=designer 常量），主 job params 数组 + P_FLAG 条目，GETDATE 变量设置 + `;P_FLAG=P_FLAG`
- taskParams 供给链校验通过（术加运行条件 `${P_FLAG}` 有源头）

## 十一、运行约定与遗留项

**运行约定（写给运维/交付，生成器无感）**：
- **跨集群依赖上线前补 id**：新跨集群上游首次出制品时若 config 表无该键 → 该依赖行跳过（制品仍可导入），stdout 汇总提示；处理=人上生产平台查得该任务 id 填入 `lts.dep_task_ids` 后重出（一次填写永续复用），或导入后平台手工加依赖。
- **停调恢复走补调**：跳周期不补调时，增量窗口（BEGIN/END_TIMES 锚计划时间）只覆盖恢复日前一天，窗口式增量会漏天；水位式增量不受影响。补调时 planTime 锚定使每周期批次正确回填。
- depTaskId（跨集群依赖）：出厂留空，导入前人工按平台查表回填（或内网脚本查表替换——沿用术加占位符思路）。

**遗留核对项（不阻塞实现，内网拿真实样本后回填）**：
1. **RS 来源任务字段映射核对**：RS 输入提供来源任务信息（用户确认），`env` 字段预计即集群名——实现时以真实 RS 样本核对一次取值映射。
2. **dbsource `[*]` 解析验证**：样本真实件即 `[*].[库名]`，按"平台按环境解析"生成（天然 env-neutral）；若内网验证不解析，切生产字面量 `[PRD].[库名]`（config 一改即切）。
3. tskdep JSON 完整键集（样本带 `...` 尾，可能有未见字段）+ `applyName` 取值（同集群样本①空、跨集群样本是业务域英文名且输入侧无来源——默认留空核对）；`crossClusterDepKey` 精确字面量（`{集群}|{pro\}` 待核）。
4. tskdep 行工程属性列（超时/重试/间隔）是否需要填。
5. 主 job 8 键 JSON 的键序/多余键以真实导出对齐一次。
6. **depTaskId 外部接口（预留）**：内网脚本仅开发环境可跑而制品对齐生产、生产 id 拿不到——2026-09-09 搁置并内联为 config 直读；对接规范保留纯文档（[lts-deptaskid脚本契约.md](./lts-deptaskid脚本契约.md)），平台开放接口后按契约接回（实现参考 git 历史曾有的三级取值+缓存）。上游任务测试环境约六成存在——二期重写表需带"无对应任务"的显式处理。另：内网联调时顺手核对管线调用命令形态（python/python3）与权限白名单 `python *` 的匹配。
7. init 任务一次性表示：照抄现状（周期任务+cron），平台侧有意见再调。

## 十二、实施切分（对齐后按此落地）

1. **exporter 重写**：`generate_schedule_excel` 拆 builder 函数族（主job/tskdep/虚拟依赖/占位/GETDATE 各一纯函数）+ 常量表集中 + §九四条校验。
2. **设计侧增强**：upstream `job` 字段 + RS 格式说明 + V_FLAG 的 SKILL 指引一句。
3. **config**：platform_config 加 `lts` 块（default.consts + schema_mappings 覆盖 + 全局 dep_task_ids，缺 id 跳过不阻断）。
4. **测试**：不连库构造 ts.json → 生成 → 逐格断言（案例 A/B 为基准）；四条校验各配反例。
5. **端到端**：模拟资产全链路（含 P_FLAG 供给链）→ 内网真实导入验证（顺带回收 §十一核对项）。
