# LTS 任务 job 构建规律（照片转写）

> **来源**：内网拍屏照片 IMG_4870~4876 转写（2026-09-09；照片原件已删，本文档即唯一源，git 历史可回溯照片）。
> **原文依据**：任务导出样本 451 条 job（4 种类型，JSON 全部可解析）。本表只写规律与构建规则，供照此搭建 LTS 任务。
> **转写约定**：少数小字不确定处以 `[?]` 标注；值模板中的 `@@…@@` 为**格式串定界符**（2026-09-09 用户实证核实：`$getCurrentTime(@@yyyyMMdd000000@@,-24*60*60)` = 当前时间的前一天；偏移为秒、负数往回；初读曾把 `@@` 误作 `@0`）。

---

## 一、总览

| job类型 | 数量 | 作用 |
|---|---|---|
| tskdep | 314 | 依赖声明（挂父节点上，声明上游） |
| url | 115 | 实际执行单元（HTTP 调用） |
| group | 10 | 并行分支容器（无执行逻辑） |
| database | 12 | SQL 执行（取日期/统计/占位） |

**所有 job 通用属性**（无需特殊配置）：

| 属性 | 恒取值 |
|---|---|
| job执行节点 | 任一节点 |
| job异常处理方式 | fail |
| 参数空值校验 | 否 |
| job描述 / job资源设置 / job扩展属性 / 组件资源 | 留空 |

---

## 二、任务级参数（taskParams）规律

任务参数在任务级声明，供任务内 job 以 `${V_XXX}` 引用；**job变量设置/jobRunParams 里出现的 `${V_XXX}` 都必须在 taskParams 有定义**。

**变量函数**：

| 函数 | 语义 |
|---|---|
| `$getJobUUID(jobUUID)` | 本次运行唯一批次号 |
| `$getTaskPlanTime(plantime,格式,偏移秒)` | 任务计划时间（非实际运行时间） |
| `$getCurrentTime(格式,偏移秒)` | 当前时间 + 偏移 |
| `$concat(a,b)` | 字符串拼接 |
| `$.data[0].xxx`（仅 job变量设置） | 从 GET 响应 JSON 提取字段 |

**约定参数（每个任务必配）**：

| 参数 | 值模板 |
|---|---|
| V_BATCH_NUMBER | `$getJobUUID(jobUUID)` |
| V_GROUP_CODE | `URG_/BRG_ + 6位数字`（业务组编码） |
| V_SCH_FROM | `LTS` |
| V_CYCLE_ID | `$getCurrentTime(@@yyyyMMdd000000@@,-24*60*60)`（当前时间的前一天——**已核实字面量**）；另有 `$concat($getTaskPlanTime(plantime,@@yyyyMMdd00:00:00@@),@@000000@@)` 变体 `[?]`拼接细节待核 |
| BEGIN_TIMES / END_TIMES | `$getTaskPlanTime(plantime,@@yyyy-MM-dd 00:00:00@@)` / `@@23:59:59@@`（抽取时间窗） |
| V_DW_LAST_UPDATE_DATE | `$getCurrentTime(@@yyyy-MM-dd HH:mm:ss@@,0)` |
| V_FLAG | `0/1/3`（增量标志） |
| V_RENTER_CODE / V_RENTER_ID | 租户标识（多租户场景） |
| V_APPID | 本集群 appId |

**平台系统注入（无需配置）**：`${V_URL}`、`${V_URL_virtualDependence}`、`${V_FILTER_QUERY_URL}`、`${V_FILTER_UPDATE_URL}`、`${V_TOKEN}`、`${P_CLUSTER_EDW_PRO}`。

> **补注（2026-09-09 用户口径，非照片原文）**：
> - 上排"平台系统注入"实为**平台上配置的项目级变量**（平台最高层级是项目，故每个项目都有这些参数）——大部分是租户甚至组织级公共定义，少部分项目下独立；**值由各环境的项目自行配置，环境差异靠变量吸收**（同一变量名，各环境配不同值）。生成物只引用、不定义。
> - `V_FLAG` 非固定参数：仅**增量加工 + 单规则组 + 变量控制规则是否跳过**的场景才有，是否定义、取值由设计方案（designer）决定。
> - `V_CYCLE_ID`（调度批次号）现网语义两派：数据日期（T+1 场景=前一天）vs 调度时间（反映当前调度时点）——待统一固定。

---

## 三、tskdep 构建规律

tskdep = 挂在父节点 job（普通 job 或组节点）上，声明对上游任务/job 的依赖。

**执行路径信息**（被依赖对象的集群定位路径，`|` 分隔）：
- **4 段 = 同集群**：`{appId}|{项目组名}|{任务组}|{任务名}`
- **5 段 = 跨集群**：`{生产集群}|{appId}|{itemName}|{taskGroupName}|{depTaskName}`

**JSON 恒量字段**：`type=tskdep`、`groupOk/start=""`、`depTaskGroupType=0`、`rangeSenior/dotSenior/hourList=[]`、`declarativeDependency=0`、`breadthSenior=["0"]`。

**核心字段规则**：

| 字段 | 规则 |
|---|---|
| depTaskId | **仅跨集群有**；**task 级 id**（被依赖任务的平台 id——2026-09-09 用户终稿；原文"三元组固定"缺任务名段，键=「集群|调度组|任务组|任务名」四段） |
| depJobName | 同集群=`"end"`；跨集群=远端真实 job 名 |
| name / depTaskName | 同集群：name=depTaskName=路径末段（任务名）。跨集群：仅 depTaskName=路径末段（任务名），name=depJobName=**依赖引用名**（输入提供，多为 job 名，≠路径末段——仅显示/引用；id 是 task 级，定位靠四段键不含此名） |
| crossClusterDepKey | 跨集群=`{远端集群}|{pro\}` `[?]` |
| crossClusterDepName | 跨集群=路径首段（生产集群名） |
| crossClusterSrcName | 跨集群=`fin_pro`（源侧集群） |
| applyName | 业务域（同集群=项目组名） |
| itemName / taskGroupName | =路径第2/3段（4段）或第3/4段（5段） |

注：`productionClusterName` 按样本归纳 = **被依赖任务的集群名**（同集群=本集群名如 fin_pro；跨集群=路径首段/远端集群名）。

**特殊模式**：
- 父节点是 G_ 组节点 → **必须带 `depInGroup` 字段**（组内依赖序号），且 `mainJobName=parentJobName=G_xxxx`
- 偏移依赖：`minList/dayList=["-3"]` 表示 T-3 依赖；正常为空 `[]`
- 上游任务被多次依赖 → job 名带 `_dep_N` 后缀，depTaskName 仍用无后缀基名
- 远端中文任务名 → name/depTaskName 用中文显示名，depJobName 用真实 job 名

### 3.4 示例（真实样本）

**① 同集群依赖**（父=普通job，4段路径，depJobName="end"，无跨集群字段）：
```
job名称: TASK_DWB_LTC_CON_DIMENSION_EXT_I (tskdep)
父节点: PJob_DWB_LTC_CON_CHANGE_F
执行路径: com.huawei.fin.bfd.bcnb|BCNB_DAILY|GROUP_LTC|TASK_DWB_LTC_CON_DIMENSION_EXT_I
job参数: {"type":"tskdep","mainJobName":"PJob_DWB_LTC_CON_CHANGE_F","depJobName":"end",
          "name":"TASK_DWB_LTC_CON_DIMENSION_EXT_I","depTaskName":"TASK_DWB_LTC_CON_DIMENSION_EXT_I",
          "productionClusterName":"fin_pro","declarativeDependency":0,"breadthSenior":["0"],
          "crossClusterDepKey":"","crossClusterDepName":"","crossClusterSrcName":"","applyName":"",...}
```

**② 跨集群依赖**（5段路径，带 depTaskId / crossCluster*）：
```
job名称: PJob_INTERFACE_DWR_DIM_CONTRACT_D (tskdep)
父节点: PJob_DWB_LTC_CON_CHANGE_F
执行路径: fin_oracc|com.huawei.fin.fmd.dimsrv|DIM_SYNC_GAUSS_DAILY|EDW_PROD1|TASK_DIM_DW1_DWRDIM_INTERFACE_SCHEDULE
job参数: {"type":"tskdep","depTaskId":"20224946","depTaskName":"TASK_DIM_DW1_DWRDIM_INTERFACE_SCHEDULE",
          "name":"PJob_INTERFACE_DWR_DIM_CONTRACT_D","depJobName":"PJob_INTERFACE_DWR_DIM_CONTRACT_D",
          "itemName":"DIM_SYNC_GAUSS_DAILY","taskGroupName":"EDW_PROD1","applyName":"DIMSVR",
          "productionClusterName":"fin_oracc","crossClusterDepName":"fin_oracc",
          "crossClusterDepKey":"oracc|pro|","crossClusterSrcName":"fin_pro",
          "declarativeDependency":0,"breadthSenior":["0"],...}
```

**③ 组节点依赖**（父=G_ 组节点，带 depInGroup）：
```
job名称: PJob_EXT_1002_OE_BLANKET_HEADERS_ALL_D2S (tskdep)
父节点: G_1024
执行路径: edw_pro|com.huawei.procurement.dw1|采购PTP|采购付款申请单|SP支付头信息_待失效
job参数: {"type":"tskdep","depInGroup":"7","mainJobName":"G_1024",
          "depTaskName":"SP支付头信息_待失效","depJobName":"PJob_EXT_1002_OE_BLANKET_HEADERS_ALL_D2S",
          "itemName":"采购PTP","taskGroupName":"采购付款申请单","applyName":"Procurement",
          "productionClusterName":"edw_pro","crossClusterDepName":"edw_pro",
          "crossClusterDepKey":"edw|pro|","crossClusterSrcName":"fin_pro",
          "declarativeDependency":0,"breadthSenior":["0"],...}
```

---

## 四、url 构建规律

url = HTTP 调用，任务内真正干活的执行单元。**4 个子类用「执行路径信息」区分**（不要只看 job 名大小写，个别命名不规范）。

### 4.1 主 job（执行路径信息 = `${V_URL}`）

- 调用方法 **POST**，invokingMode=**异步**（只提交执行，不等待结果）
- job参数 8 键：
  - `headers` = `Content-Type:application/json;charset=UTF-8`
  - `retVal` = `""`、`appToken` = `${V_TOKEN}`、`appId` = `${V_APPID}`、`authenticationType` = 手动输入、`timeout` = 10
- **jobRunParams = 内嵌 JSON，固定 4 键**：
  - `batch_number` = `${V_BATCH_NUMBER}`、`group_code` = `${V_GROUP_CODE}`、`sch_from` = `${V_SCH_FROM}`
  - `params` = 数组：`[{"name":"P_XXX","type":"constants","value":"${V_XXX}"}]` —— 向执行端传加工参数表
- 父节点（上游链，`;` 分隔、末段恒 start）：无依赖=start；先取日期=GETDATE；依赖本任务内抽取 job 则写 `PJob_EXT_...;...;start`
- 超时 60 / 重试 3 / 间隔 60；跳过清场 = 跟随任务

### 4.2 虚拟依赖（执行路径信息 = `${V_URL_virtualDependence}`）

- 作用：向远端集群发"抽取 XX 表"同步请求（不落本地 SQL）
- 命名：`PJob_EXT_{源系统编号}_{表名}_{版本戳}_{后缀}`；后缀语义：`_D2S`=增量 / `_PD`=周期 / `_ALL`=全量 / `_TH`=按天；版本戳 = `_MP{13位数字}`（存量可无）
- job参数 8 键：**headers/appToken/appId 全空**、authenticationType=无、timeout=10
- **jobRunParams = URL query 形态**（`&` 连接），固定 8 键：
  - `clusterName` = `${P_CLUSTER_EDW_PRO}`（恒）
  - `appId` = 远端业务域（com.huawei.so.master_data 等）；`itemName/taskGroupName/taskName` = 远端调度组/任务组/任务名（可为中文业务名）
  - `jobName` = 恒等于本 job 自身名称（**自指**，远端据此定位）
  - `begin/end` = 时间窗变量（`${BEGIN_TIMES}/${END_TIMES}` 或 GETDATE 输出）
- 挂组节点版：job 名 = `G_xxxx|PJob_EXT_...`（层级编码进名字），父节点 = start，参数同构
- 跳过清场 = 跟随任务

### 4.3 FILTER 工具（成对出现，可选增强）

| job | 方法/方式 | 父节点 | 作用 |
|---|---|---|---|
| PJob_FILTER_GETDATE_INFO | GET / 同步 retVal=data | start | 查 filter 上次周期 |
| PJob_FILTER_UPDATE_INFO | POST / 同步 | 对应主 job | 回写本次周期 |

- GETDATE_INFO：`jobRunParams = page=1&rows=1&filterName=${P_TASK_NAME}&appId=${V_APPID}`；job变量设置用 JSONPath 从响应提取 4 个周期变量（`START_DATE=$.data[0].startDate`、`END_DATE`、`CYCLE_ID`、`LAST_CYCLE_ID`）
- UPDATE_INFO：jobRunParams = 内嵌 JSON，`queryParam.filterName` 定位，`updateParam` 回写 cycleId/lastCycleId/startDate/endDate/lastModifiedDate
- 需要 `P_TASK_NAME`（任务名）、`V_APPID` 参数；**仅"带 filter"的任务才配，非通用模板**

### 4.4 示例（真实样本）

**① 主 job**（`${V_URL}`，异步 POST）：
```
job名称: PJob_DWB_LTC_CON_CHANGE_F    父节点: start    调用方法: POST
job参数: {
  "headers": "Content-Type:application/json;charset=UTF-8",
  "invokingMode": "异步", "retVal": "",
  "jobRunParams": "{
    \"batch_number\": \"${V_BATCH_NUMBER}\", \"group_code\": \"${V_GROUP_CODE}\", \"sch_from\": \"${V_SCH_FROM}\",
    \"params\": [
      {\"name\": \"P_CYCLE_ID\", \"type\": \"constants\", \"value\": \"${V_CYCLE_ID}\"},
      {\"name\": \"P_FLAG\", \"type\": \"constants\", \"value\": \"${V_FLAG}\"},
      {\"name\": \"P_START_DATE\", \"type\": \"constants\", \"value\": \"${V_START_DATE}\"},
      \"name\": \"P_END_DATE\", \"type\": \"constants\", \"value\": \"${V_END_DATE}\"}]}" `[?]`末行转写
  ,
  "appToken": "${V_TOKEN}", "appId": "${V_APPID}", "authenticationType": "手动输入", "timeout": 10
}
超时60/重试3/间隔60 ｜ 跳过清场=否 ｜ 超时处理=一次邮件提醒
```

**② 虚拟依赖**（`${V_URL_virtualDependence}`，query 形态，jobName 自指）：
```
job名称: PJob_EXT_2500_FND_LOOKUP_VALUES_T_MP002442023051000179_D2S   父节点: start
job参数: {
  "headers": "", "invokingMode": "异步", "retVal": "", "appToken": "", "appId": "",
  "authenticationType": "无", "timeout": 10,
  "jobRunParams": "clusterName=${P_CLUSTER_EDW_PRO}&appId=com.huawei.so.master_data
    &itemName=IT_产品服务&taskGroupName=IT_开通配置配置信息&taskName=IT_Jalor应用系统权限值
    &jobName=PJob_EXT_2500_FND_LOOKUP_VALUES_T_MP002442023051000179_D2S
    &begin=${BEGIN_DATE}&end=${END_DATE}"
}
超时60/重试3/间隔60 ｜ 跳过清场=跟随任务
```

**③ 虚拟依赖挂组节点**（同 ②，job 名带 `G_xxxx|` 前缀）：
```
job名称: G_1020|PJob_EXT_2860_HW_CSPM_CONTRACT_NO_T_D2S   父节点: start
job参数: 与 ② 同构, jobRunParams 中 jobName=PJob_EXT_2860_HW_CSPM_CONTRACT_NO_T_D2S（自指）,
         begin=${BEGIN_TIMES}&end=${END_TIMES}, 远端目标 appId=com.huawei.so.master_data / itemName=CBG_服务备件... `[?]`截断
```

**④ FILTER 成对**：
```
GETDATE_INFO（父=start, GET 同步, retVal=data）:
  jobRunParams = page=1&rows=1&filterName=${P_TASK_NAME}&appId=${V_APPID}
  job变量设置  = START_DATE=$.data[0].startDate;END_DATE=$.data[0].endDate;
                 CYCLE_ID=$.data[0].cycleId;LAST_CYCLE_ID=$.data[0].lastCycleId
UPDATE_INFO（父=PJob_DWB_LTC_CONTRACT_BASE_MID_F, POST 同步）:
  jobRunParams = {"appId":"${V_APPID}","queryParam":{"filterName":"${P_TASK_NAME}"},
                  "updateParam":{"cycleId":"${P_cycleId}","lastCycleId":"${P_lastCycleId}",
                  "startDate":"${P_startDate}","endDate":"${P_endDate}",
                  "lastModifiedDate":"${P_startDate}"}}
```

---

## 五、group 构建规律

- 组节点 = 并行分支容器，**无执行逻辑，job参数全空**
- 命名 `G_` + 编号，按"抽取/加工逻辑"分组命名，**可被多个任务复用**
- 组内成员 = 命名 `G_xxxx|PJob_EXT_...` 的 url job
- 工程属性：超时 10 / 重试 3 / 间隔 1；跳过清场 = 否；执行节点留空
- 父节点：start 或 EMPTY 二选一

### 5.1 示例（真实样本）
```
job名称: G_1020（group）    父节点: start
job参数: （空）             job执行节点: （空）
超时10/重试3/间隔1 ｜ 跳过清场=否 ｜ 超时处理:（空）
配套的子抽取 job（url 虚拟依赖）命名: G_1020|PJob_EXT_2860_HW_CSPM_CONTRACT_NO_T_D2S、
G_1020|PJob_EXT_3530_PUB_CONTRACT_T_..._ALL 等；同一 G_ 编号可挂到多个任务的同名抽取逻辑上。
```

---

## 六、database 构建规律

- 调用方法 = `sql`；**job参数 6 键恒定**：`schema={目标schema}`、`dbsource="[*].[GAUSS_EDW_BFD_BNIL]"`、`datasourceTypeName=gauss200`、`retVal/inParams/outParams=""`
- 超时处理 = 一次邮件提醒

**3 个子类**：

| 子类 | SQL 形态 | 父节点 | 工程属性 |
|---|---|---|---|
| GETDATE 取日期 | SELECT 日期计算，固定输出 4 列：START_DATE/END_DATE/CUR_CYCLE_ID/DW_LAST_UPDATE_DATE | 组节点 + FILTER + start 汇聚链（在 filter 之后） | 60/3/60；跟随任务 |
| ANALYZE | `ANALYZE {schema}.{表名}` | 对应主 job（主 job 跑完后收集统计） | 60/3/60；跟随任务 |
| I 类占位查询 | `SELECT 1 FROM {schema}.{目标表} WHERE 1 = 2` | start | 10/3/1；跳过清场=否 |

- **job变量设置** = `P_START_DATE=START_DATE;P_END_DATE=END_DATE;P_CUR_CYCLE_ID=CUR_CYCLE_ID;P_DW_LAST_UPDATE_DATE=DW_LAST_UPDATE_DATE` —— SQL输出列 → P_ 前缀任务变量的桥，供主 job 的 params 引用
- 口径：END_DATE = 起始 + 1 天；START_DATE 可取原样或偏移 N 天
- **简化版（无 filter 任务）**：只输出 DW_LAST_UPDATE_DATE + CUR_CYCLE_ID（`yyyymmdd||'000000'`），变量设置带 `P_FLAG=P_FLAG`

### 6.2 示例（真实样本）

**① GETDATE**：
```
job名称: GETDATE    父节点: G_1020;G_1024;PJob_FILTER_GETDATE_INFO;G_1010    调用方法: sql
执行路径(SQL): SELECT TO_CHAR(trunc(TO_DATE('${START_DATE}','YYYY-MM-DD hh24:mi:ss')),'yyyy-mm-dd hh24:mi:ss') AS START_DATE,
               TO_CHAR(TO_DATE('${END_DATE}','YYYY-MM-DD hh24:mi:ss')+1,'YYYY-MM-DD hh24:mi:ss') AS END_DATE,
               '${CYCLE_ID}' AS CUR_CYCLE_ID,
               to_char(sysdate,'yyyy-mm-dd hh24:mi:ss') AS DW_LAST_UPDATE_DATE
job参数: {"schema":"fin_dwb_ltc","dbsource":"[*].[GAUSS_EDW_BFD_BNIL]","datasourceTypeName":"gauss200",
          "retVal":"","inParams":"","outParams":""}
job变量设置: P_START_DATE=START_DATE;P_END_DATE=END_DATE;P_CUR_CYCLE_ID=CUR_CYCLE_ID;P_DW_LAST_UPDATE_DATE=DW_LAST_UPDATE_DATE
超时60/重试3/间隔60 ｜ 跳过清场=跟随任务
```

**② ANALYZE**：
```
job名称: ANALYZE    父节点: PJob_DWB_LTC_INVOICE_LINE_F（对应主 job）
执行路径(SQL): ANALYZE FIN_DWB_LTC.DWB_LTC_INVOICE_LINE_F
job参数: 同 ①（6 键恒定）    超时60/重试3/间隔60 ｜ 跳过清场=跟随任务
```

**③ I 类占位查询**：
```
job名称: PJob_DWB_CDM_PAYMENT_CLAUSE_I    父节点: start
执行路径(SQL): SELECT 1 FROM FIN_DWB_LTC.DWB_CDM_PAYMENT_CLAUSE_I WHERE 1 = 2
job参数: 同 ①（6 键恒定）    超时10/重试3/间隔1 ｜ 跳过清场=否
```

---

## 七、完整任务构建顺序

1. **任务级参数**：配 V_BATCH_NUMBER / V_GROUP_CODE / V_SCH_FROM / V_CYCLE_ID / 时间窗 / 审计 / 增量 / 租户
2. **组节点**（需要并行抽取时）：建 G_xxxx + 子抽取 job `G_xxxx|PJob_EXT_...`（父=start）
3. **虚拟依赖**（无组）：直接建 `PJob_EXT_...`（父=start）
4. **FILTER 工具**（可选）：GETDATE_INFO（父=start）+ UPDATE_INFO（父=主 job）
5. **GETDATE**：父节点 = 组节点+FILTER+start 汇聚链，SQL 出 4 列，变量设置桥接 P_ 变量
6. **主 job**：`PJob_{目标表}`，执行路径信息 = `${V_URL}`，父节点 = GETDATE 或 start 或抽取链
7. **tskdep 依赖**：挂在主 job / 组节点上，声明上游（4 段同集群 / 5 段跨集群）
8. **I 类目标表** → 加占位查询 job（`SELECT 1 ... WHERE 1=2`）
9. **ANALYZE**（可选）：主 job 后收集统计
10. **通用属性**：各 job 执行节点=任一节点、异常=fail、按子类型配超时/重试/跳过清场

> 典型链路：组并行抽取 → filter 取回周期 → GETDATE 取日期 → 主 job 提交需用 → filter 回写；tskdep 挂主 job/组节点声明上游依赖。`[?]`末句小字按可读性转写
