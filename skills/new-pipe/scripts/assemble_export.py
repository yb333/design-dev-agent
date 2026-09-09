#!/usr/bin/env python3
"""
平台制品包 exporter

UT 通过后调用。把验证过的 ts.json + ETL SQL 翻译成
内网平台消费的 Excel 格式（execution_tasks.xlsx + schedule_tasks.xlsx）。
视图不发术加规则行（视图是 DDL 对象，走 ddl/ 通道部署；RULE 行只表达
"SELECT 取数写入目标表"）。

产出目录：{outdir}/export/
  - shujia_{表名}.xlsx    术加执行平台导入（10 sheet）
  - lts_{表名}.xlsx       LTS 调度平台导入（3 sheet）

规则编码策略：占位符出厂，内网脚本查表替换（Excel 自描述，脚本零配置）。
  规则组编码 = GR_{组英文名}；规则编码 = ts 规则码；参数变量行 = PV000N。
  TargetFields/GroupVariables 按占位码挂引用，生成阶段做三处闭合校验。
  项目只填中文名（人可确认的锚点）；项目编码/英文名、子项目全套留空——
  内网脚本按中文名从平台补齐。
  交接流程：闸口②收集 项目中文名（配置预填可改）+ 子项目中文名 → 内网
  脚本补齐编码/英文名、取码替换占位符 → 人工上传。
  租户ID = appid（schema_apps 反查）；组织英文简称/数据源 = 术加租户属性
  （platform_config 的 shujia_tenants[appid]，租户级覆盖 schema 级）。

用法:
  python assemble_export.py --ts ts.json --etl-dir etl/ --outdir .

退出码: 0=成功, 1=参数/数据错误, 2=依赖缺失
"""

import sys
import os
import re
import json
import argparse
from datetime import datetime
from pathlib import Path

# shared 公共库自洽引用：相对路径推算 design-dev-shared（skill 脚本标准 bootstrap）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "design-dev-shared" / "scripts"))

# config_paths/resolve_appid 在 shared 公共库（上方 bootstrap 已接通）
from config_paths import platform_config_path, resolve_appid

try:
    import openpyxl
except ImportError:
    print("错误: 需要 openpyxl。请运行 pip install openpyxl", file=sys.stderr)
    sys.exit(2)


# ============================================================
# 列定义（精确对齐执行平台制品模板，跟 legacy 一致）
# ============================================================

RULE_COLUMNS = [
    "租户ID", "组织英文简称", "类型", "项目编码", "项目中文名", "项目英文名",
    "项目描述", "子项目编码", "子项目中文名", "子项目英文名", "子项目描述",
    "规则组编码", "规则组中文名称", "规则组英文名称", "规则组业务责任人",
    "规则组描述", "规则组数据源", "规则编码", "规则中文名称", "规则英文名称",
    "创建方式", "规则类型", "数据源", "备注",
    "(生成的）查询语句1", "(生成的）查询语句2", "(生成的）查询语句3",
    "(生成的）查询语句4", "(生成的）查询语句5", "(生成的）查询语句6",
    "(生成的）查询语句7", "(生成的）查询语句8", "(生成的）查询语句9",
    "运行条件", "Select Hint语句", "执行序列", "源Schema", "目标Schema",
    "目标SCHEMA解析值", "目标表", "目标表解析", "是否去重", "删除模式",
    "删除条件", "业务责任人", "delete hint", "交换分区来源表",
    "目标表统计信息收集", "行迁移开关", "会话变量", "环境变量设置",
    "并行开关", "事前操作", "事后操作", "存储模式", "压缩比", "是否散列",
    "程序包名", "SP名称", "API参数", "更新索引", "循环变量",
    "规则循环并行调度标志", "循环分组设置", "循环优先级", "引用规则",
    "重试间隔", "重试次数", "不满足时", "数据库类型", "调度类型",
    "指定分区", "来源表统计分析收集", "统计分析来源表", "规则描述",
    "装载字段", "进程数", "运行内存", "线程数", "批量大小", "并发数",
    "spark数据源",
]
_RULE_COL = {name: idx for idx, name in enumerate(RULE_COLUMNS)}

GROUPVARS_COLUMNS = [
    "规则编码", "动态参数/变量名", "字段类型", "字段定义类型",
    "字段值类型", "变量默认值", "是否校验通过", "数据类型", "描述",
    "是否必填",
]

TARGETFIELDS_COLUMNS = [
    "规则编码", "目标字段名称", "来源字段名称", "加密方式",
    "Merge模式数据源字段值", "别名", "字段类型", "备注",
]

MODELRELATIONS_COLUMNS = [
    "规则编码", "左表schema", "左表名", "左表别名", "右表schema",
    "右表", "右表别名", "模型顺序号", "关联关系", "左表字段列表串",
    "右表字段列表串",
]
EXTRAFIELDS_COLUMNS = ["规则编码", "拓展字段名", "别名", "表达式", "字段类型", "生效", "统计标识"]
SPPARAMS_COLUMNS = ["规则编码", "规则参数名", "数据类型", "入参、出参", "变量默认值"]
CONDITIONS_COLUMNS = [
    "规则编码", "字段名称", "字段关系", "字段值1", "字段值2",
    "与下个条件的逻辑关系", "序号", "字段类型", "条件类型",
    "树形组件业务父类id", "树形组件业务id",
]
MAINTENANCEPARAMS_COLUMNS = ["规则编码", "执行序列", "类型", "schema", "表名", "字段名", "分区表名"]
EXTRACT_COLUMNS = [
    "标签id", "规则编码", "数据库名称", "数据库类型", "标签名",
    "分区读写字段", "分区读写字段类型", "分区数量", "分区下界",
    "分区上界", "批量提取大小", "数据提取SQL", "运行SQL",
    "统计信息分析标识", "统计信息分析来源表信息",
]
EXTRACTCOLUMN_COLUMNS = ["数据标签id", "规则编码", "解密字段", "字段类型", "解密类型"]

# 调度平台列
TASKS_COLUMNS = [
    "项目名称", "任务组名称", "任务名称", "任务类型", "开始时间", "结束时间",
    "调度周期", "依赖上一周期", "日历数据", "责任人", "同步标识", "CTM任务标识",
    "CTM集群标识", "任务是否跳过清场", "TASK资源设置", "不调度过期周期",
    "任务扩展属性", "是否一天多调", "是否并行", "异常任务是否清场",
    "是否导入全量job", "调度频率配置",
]
JOBS_COLUMNS = [
    "项目名称", "任务组名称", "任务名称", "job名称", "job类型",
    "job的父节点名称", "执行路径信息", "job参数", "job调用方法",
    "job超时时间", "job重试次数", "job重试间隔", "job描述",
    "job执行节点", "job变量设置", "job异常处理方式", "job中断处理",
    "job超时处理", "集群名称", "job是否跳过清场", "datastage日志级别",
    "job资源设置", "job扩展属性", "参数空值校验", "生产执行路径",
    "生产job中断处理", "生产schema", "组件资源",
]
TASKPARAMS_COLUMNS = ["项目名称", "任务组名称", "任务名称", "参数名称", "参数值"]

# 审计字段（TargetFields 里过滤掉）
AUDIT_FIELDS = {"del_flag", "crt_cycle_id", "last_upd_cycle_id", "dw_last_update_date"}

# 固定常量


# ============================================================
# schedule_tasks.xlsx 构建（LTS 制品；设计依据 docs/platform/lts-制品生成设计.md）
# ============================================================

# 所有 job 通用属性（451 样本规律"总览"：无需特殊配置的恒取值）
JOB_COMMON_ATTRS = {"job执行节点": "任一节点", "job异常处理方式": "fail", "参数空值校验": "否"}

# taskParams 基础全集（每个任务必配；值模板为平台变量函数表达式，@@…@@ 为格式串定界符）
LTS_PARAM_TEMPLATES = {
    "V_BATCH_NUMBER": "$getJobUUID(jobUUID)",
    "V_SCH_FROM": "LTS",
    "V_CYCLE_ID": "$getTaskPlanTime(plantime,@@yyyyMMdd000000@@,-24*60*60)",
    "BEGIN_TIMES": "$getTaskPlanTime(plantime,@@yyyy-MM-dd 00:00:00@@)",
    "END_TIMES": "$getTaskPlanTime(plantime,@@23:59:59@@)",
    "V_DW_LAST_UPDATE_DATE": "$getCurrentTime(@@yyyy-MM-dd HH:mm:ss@@,0)",
}
TASKPARAMS_BASE = ["V_BATCH_NUMBER", "V_GROUP_CODE", "V_SCH_FROM", "V_CYCLE_ID",
                   "BEGIN_TIMES", "END_TIMES", "V_DW_LAST_UPDATE_DATE", "V_APPID"]

# 平台/项目级注入变量（只引用、不在 taskParams 定义——引用闭合校验的豁免集）
PLATFORM_INJECTED_REFS = {"V_URL", "V_URL_virtualDependence", "V_FILTER_QUERY_URL",
                          "V_FILTER_UPDATE_URL", "V_TOKEN", "P_CLUSTER_EDW_PRO"}

_JOBS_COL = {name: idx for idx, name in enumerate(JOBS_COLUMNS)}

_V_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _new_job_row() -> list:
    return [""] * len(JOBS_COLUMNS)


def _fill_project_cols(row: list, project: str, group: str, task_name: str):
    """tskdep 行归属恒=当前任务（用户定调：上游定位全在执行路径里）。"""
    row[_JOBS_COL["项目名称"]] = project
    row[_JOBS_COL["任务组名称"]] = group
    row[_JOBS_COL["任务名称"]] = task_name


def _fill_common_job_attrs(row: list):
    for col, val in JOB_COMMON_ATTRS.items():
        row[_JOBS_COL[col]] = val


def _fill_engineering(row: list, timeout: int, retry: int, interval: int,
                      skip_cleanup: str, timeout_handler: str = ""):
    row[_JOBS_COL["job超时时间"]] = str(timeout)
    row[_JOBS_COL["job重试次数"]] = str(retry)
    row[_JOBS_COL["job重试间隔"]] = str(interval)
    row[_JOBS_COL["job是否跳过清场"]] = skip_cleanup
    if timeout_handler:
        row[_JOBS_COL["job超时处理"]] = timeout_handler


def _main_job_params(run_params_json: str) -> str:
    """主 job 8 键（异步 POST 形态；与虚拟依赖的全空 8 键区分——曾拿错形态当通用模板）。"""
    return json.dumps({
        "headers": "Content-Type:application/json;charset=UTF-8",
        "invokingMode": "异步",
        "retVal": "",
        "jobRunParams": run_params_json,
        "appToken": "${V_TOKEN}",
        "appId": "${V_APPID}",
        "authenticationType": "手动输入",
        "timeout": 10,
    }, ensure_ascii=False)


def _main_job_run_params(lts_params: list) -> str:
    """主 job jobRunParams 内嵌 JSON 固定 4 键；params 数组 = lts_params（V→P）直译。"""
    entries = [{"name": p.get("etl_param", ""), "type": "constants",
                "value": "${%s}" % p.get("lts_var", "")}
               for p in (lts_params or []) if p.get("etl_param")]
    return json.dumps({
        "batch_number": "${V_BATCH_NUMBER}",
        "group_code": "${V_GROUP_CODE}",
        "sch_from": "${V_SCH_FROM}",
        "params": entries,
    }, ensure_ascii=False)


def _virtual_dep_params(run_params_query: str) -> str:
    """虚拟依赖 8 键：headers/appToken/appId 全空 + authenticationType=无。"""
    return json.dumps({
        "headers": "", "invokingMode": "异步", "retVal": "",
        "jobRunParams": run_params_query,
        "appToken": "", "appId": "",
        "authenticationType": "无", "timeout": 10,
    }, ensure_ascii=False)


def _database_job_params(schema: str, db_name: str, datasource_type: str) -> str:
    """database 6 键恒定。dbsource=[*].[库名]——[*] 照样本原样（平台按环境解析）。"""
    if not db_name:
        raise ValueError("platform_config lts.consts.db_name 未配置（database job 库名，"
                         "如 GAUSS_EDW_BFD_BNIL）")
    return json.dumps({
        "schema": schema,
        "dbsource": f"[*].[{db_name}]",
        "datasourceTypeName": datasource_type or "gauss200",
        "retVal": "", "inParams": "", "outParams": "",
    }, ensure_ascii=False)


def _cross_dep_key(cluster: str) -> str:
    """crossClusterDepKey 启发式：fin_oracc→oracc|pro|、edw_pro→edw|pro|（样本②③归纳）。

    ⚠️ 字面量待真实导出核对（设计文档 §十一.3），不符时只改这里。
    """
    base = cluster
    if base.startswith("fin_"):
        base = base[len("fin_"):]
    if base.endswith("_pro"):
        base = base[:-len("_pro")]
    return f"{base}|pro|"


def _tskdep_params(main_job_name: str, name: str, dep_task_name: str, dep_job_name: str,
                   production_cluster: str, item_name: str, task_group: str,
                   cross_src: str = "", cross_dep_name: str = "", cross_key: str = "",
                   dep_task_id: str = "") -> str:
    """tskdep job参数 JSON（恒量字段 + 派生字段；同/跨集群差异由调用方传值）。"""
    data = {
        "type": "tskdep",
        "mainJobName": main_job_name,
        "depJobName": dep_job_name,
        "name": name,
        "depTaskName": dep_task_name,
        "productionClusterName": production_cluster,
        "declarativeDependency": 0,
        "breadthSenior": ["0"],
        "groupOk": "",
        "start": "",
        "depTaskGroupType": 0,
        "rangeSenior": [],
        "dotSenior": [],
        "hourList": [],
        "crossClusterDepKey": cross_key,
        "crossClusterDepName": cross_dep_name,
        "crossClusterSrcName": cross_src,
        "applyName": "",
        "itemName": item_name,
        "taskGroupName": task_group,
    }
    if dep_task_id:
        data["depTaskId"] = str(dep_task_id)
    return json.dumps(data, ensure_ascii=False)


def _collect_v_refs(text: str) -> set:
    """提取字符串里所有 ${V_XXX} 引用（引用闭合校验用）。"""
    return set(_V_REF.findall(text or ""))


def validate_lts_package(ts: dict, lts_params: list, job_rows: list, param_names: set) -> list:
    """出厂校验（设计文档 §九五条中可在行集上静态判定的三条；路径/depTaskId 在构建期 fail-loud）。

    1. ${V_XXX} 引用闭合：job 各格引用 ⊆ taskParams 定义集（照片 §2 铁律）
    2. 父节点引用闭合：∈ {start, EMPTY} ∪ 本任务 job 名集合
    5. P_ 变量供给链：inline init 的 ${P_FLAG} 必须有 params 数组供给 + taskParams 定义
    """
    problems = []
    name_col = _JOBS_COL["job名称"]
    task_col = _JOBS_COL["任务名称"]
    parent_col = _JOBS_COL["job的父节点名称"]
    ref_cols = [_JOBS_COL[c] for c in ("执行路径信息", "job参数", "job变量设置")]

    job_names_by_task = {}
    for r in job_rows:
        job_names_by_task.setdefault(r[task_col], set()).add(r[name_col])

    for r in job_rows:
        task = r[task_col]
        refs = set()
        for c in ref_cols:
            refs |= _collect_v_refs(r[c])
        dangling = sorted(refs - param_names - PLATFORM_INJECTED_REFS)
        if dangling:
            problems.append(f"任务 {task} 的 job 引用了 taskParams 未定义的参数: {dangling}")
        parent = r[parent_col]
        if parent and parent not in ({"start", "EMPTY"} | job_names_by_task.get(task, set())):
            problems.append(f"任务 {task} 的 job {r[name_col]!r} 父节点 {parent!r} 不存在（须为 start/EMPTY 或本任务 job 名）")

    init_section = ts.get("init") or {}
    if isinstance(init_section, dict) and init_section.get("group_mode") == "inline":
        p_names = {p.get("etl_param") for p in (lts_params or []) if p.get("etl_param")}
        if "P_FLAG" not in p_names:
            problems.append("inline init 模式 RULE 运行条件引用 ${P_FLAG}，但 lts_params 无 V_FLAG→P_FLAG 映射（执行端拿不到 P_FLAG）")
        if "V_FLAG" not in param_names:
            problems.append("inline init 模式 taskParams 缺 V_FLAG（designer 需在 lts_params 声明 {lts_var: V_FLAG, value: ...}）")
    return problems


def generate_schedule_excel(ts: dict, config: dict, output_path: Path):
    """生成 lts_{表名}.xlsx（3 sheet：tasks/jobs/taskParams）——LTS 制品。

    任务组合模型（设计文档 §三）：
      f 任务   = [虚拟依赖×N] + [GETDATE(增量)] + 主job + tskdep×N
      view 任务 = database 占位job + tskdep(声明 f 任务)
      dq/init  = 主job + tskdep×N
    一期面向生产（§二.9）：本集群名/depTaskId 走 consts/三级取值，不做 --env。
    """
    from dep_task_id import resolve_dep_task_id

    meta = ts.get("meta", {})
    sched = meta.get("schedule", {})
    tasks_sched = sched.get("tasks", {})
    lts_params = sched.get("lts_params", [])
    lts_cfg = config.get("lts", {})
    consts = lts_cfg.get("consts", {}) or {}
    cluster_local = (consts.get("cluster_local") or "").strip()
    db_name = (consts.get("db_name") or "").strip()
    datasource_type = consts.get("datasource_type", "gauss200")

    # 兜底默认值（旧 ts.json 无 project/task_group 时用 platform_config 的 lts 段）
    fallback_project = _cfg(lts_cfg, "project_name")
    fallback_group = _cfg(lts_cfg, "task_group")
    appid = (config.get("shujia") or {}).get("appid", "")
    owner = _cfg(config.get("shujia", {}), "business_owner", "")

    incremental = bool(ts.get("init"))
    v_flag_declared = any(p.get("lts_var") == "V_FLAG" for p in (lts_params or []))

    def _resolve_path(task_info):
        p = task_info.get("project_name") or fallback_project
        g = task_info.get("task_group") or fallback_group
        return p, g

    def _schema_of(kind_table):
        return (meta.get("target", {}).get(kind_table, {}) or {}).get("schema", "")

    # --- job 行 builders（闭包取 consts/appid/lts_cfg） ---

    def _tskdep_row(task_info, main_job_name, upstream):
        """同集群 4 段 / 跨集群 5 段。跨集群缺 cluster/job → fail-loud（输入直传不推导）。"""
        p, g = _resolve_path(task_info)
        task = upstream.get("task", "")
        project = upstream.get("project", "") or p
        group = upstream.get("group", "") or g
        app = upstream.get("app", "")
        remote_cluster = (upstream.get("cluster", "") or upstream.get("env", "") or "").strip()
        main_job = main_job_name or task_info.get("job_name", "")

        if remote_cluster:
            job_name = (upstream.get("job") or "").strip()
            if not job_name:
                raise ValueError(
                    f"跨集群依赖缺远端 job 名：上游 {task}（集群 {remote_cluster}）。"
                    "upstream 项需提供 job 字段（远端真实 job 名，输入直传不推导）")
            segs = [remote_cluster, app, project, group, task]
            if not all(segs):
                raise ValueError(f"跨集群依赖路径段不全（集群|appId|itemName|任务组|任务名）: 上游 {task}，"
                                 f"got cluster={remote_cluster!r} app={app!r} project={project!r} group={group!r}")
            path = "|".join(segs)
            dep_task_id = resolve_dep_task_id(remote_cluster, project, group, task, lts_cfg)
            params = _tskdep_params(main_job, job_name, task, job_name,
                                    remote_cluster, project, group,
                                    cross_src=cluster_local, cross_dep_name=remote_cluster,
                                    cross_key=_cross_dep_key(remote_cluster), dep_task_id=dep_task_id)
        else:
            if not cluster_local:
                raise ValueError("platform_config lts.consts.cluster_local 未配置（本集群名，生产 fin_pro/"
                                 "测试 BIZBAETA/开发 LTSBETA 三选一）——同集群 tskdep 集群字段需要它")
            job_name = task
            segs = [appid, project, group, task]
            if not all(segs):
                raise ValueError(f"同集群依赖路径段不全（appId|项目组|任务组|任务名）: 上游 {task}，"
                                 f"got appid={appid!r} project={project!r} group={group!r}")
            path = "|".join(segs)
            params = _tskdep_params(main_job, job_name, task, "end",
                                    cluster_local, project, group)

        row = _new_job_row()
        _fill_project_cols(row, p, g, task_info.get("task_name", ""))
        _fill_common_job_attrs(row)
        row[_JOBS_COL["job名称"]] = job_name
        row[_JOBS_COL["job类型"]] = "tskdep"
        row[_JOBS_COL["job的父节点名称"]] = main_job
        row[_JOBS_COL["执行路径信息"]] = path
        row[_JOBS_COL["job参数"]] = params
        return row

    def _virtual_dep_row(task_info, upstream):
        """向远端集群发抽取请求（上游为手工起调的非周期任务时用；场景极少）。"""
        p, g = _resolve_path(task_info)
        task = upstream.get("task", "")
        job_name = (upstream.get("job") or "").strip()
        if not job_name:
            raise ValueError(f"虚拟依赖缺 job 全名：上游 {task}。upstream 项需提供 job 字段"
                             "（PJob_EXT_源系统编号_表名_版本戳_后缀 完整名，输入直传不推导）")
        query = (f"clusterName=${{P_CLUSTER_EDW_PRO}}"
                 f"&appId={upstream.get('app', '')}&itemName={upstream.get('project', '')}"
                 f"&taskGroupName={upstream.get('group', '')}&taskName={task}"
                 f"&jobName={job_name}&begin=${{BEGIN_TIMES}}&end=${{END_TIMES}}")
        row = _new_job_row()
        _fill_project_cols(row, p, g, task_info.get("task_name", ""))
        _fill_common_job_attrs(row)
        row[_JOBS_COL["job名称"]] = job_name
        row[_JOBS_COL["job类型"]] = "url"
        row[_JOBS_COL["job的父节点名称"]] = "start"
        row[_JOBS_COL["执行路径信息"]] = "${V_URL_virtualDependence}"
        row[_JOBS_COL["job参数"]] = _virtual_dep_params(query)
        row[_JOBS_COL["job调用方法"]] = "POST"
        _fill_engineering(row, 60, 3, 60, "跟随任务")
        return row

    def _main_job_row(task_info, parent):
        p, g = _resolve_path(task_info)
        row = _new_job_row()
        _fill_project_cols(row, p, g, task_info.get("task_name", ""))
        _fill_common_job_attrs(row)
        row[_JOBS_COL["job名称"]] = task_info.get("job_name", "")
        row[_JOBS_COL["job类型"]] = "url"
        row[_JOBS_COL["job的父节点名称"]] = parent
        row[_JOBS_COL["执行路径信息"]] = "${V_URL}"
        row[_JOBS_COL["job参数"]] = _main_job_params(_main_job_run_params(lts_params))
        row[_JOBS_COL["job调用方法"]] = "POST"
        _fill_engineering(row, 60, 3, 60, "跟随任务", "一次邮件提醒")
        return row

    def _view_placeholder_row(task_info):
        """视图任务 job = database 占位查询（数据由 DDL 视图承担，任务只为依赖挂线）。"""
        p, g = _resolve_path(task_info)
        view = meta.get("target", {}).get("i_view", {}) or {}
        row = _new_job_row()
        _fill_project_cols(row, p, g, task_info.get("task_name", ""))
        _fill_common_job_attrs(row)
        row[_JOBS_COL["job名称"]] = task_info.get("job_name", "")
        row[_JOBS_COL["job类型"]] = "database"
        row[_JOBS_COL["job的父节点名称"]] = "start"
        row[_JOBS_COL["执行路径信息"]] = f"SELECT 1 FROM {view.get('schema', _schema_of('i_view'))}.{view.get('table', '')} WHERE 1 = 2"
        row[_JOBS_COL["job参数"]] = _database_job_params(view.get("schema", ""), db_name, datasource_type)
        row[_JOBS_COL["job调用方法"]] = "sql"
        _fill_engineering(row, 10, 3, 1, "否")
        return row

    def _getdate_row(task_info):
        """GETDATE 简化版（无 filter）：出 DW_LAST_UPDATE_DATE + CUR_CYCLE_ID 两列，桥接 P_ 变量。"""
        p, g = _resolve_path(task_info)
        sql = ("SELECT to_char(sysdate,'yyyy-mm-dd hh24:mi:ss') AS DW_LAST_UPDATE_DATE, "
               "'${V_CYCLE_ID}' AS CUR_CYCLE_ID")
        var_setting = "P_DW_LAST_UPDATE_DATE=DW_LAST_UPDATE_DATE;P_CUR_CYCLE_ID=CUR_CYCLE_ID"
        if v_flag_declared:
            var_setting += ";P_FLAG=P_FLAG"
        row = _new_job_row()
        _fill_project_cols(row, p, g, task_info.get("task_name", ""))
        _fill_common_job_attrs(row)
        row[_JOBS_COL["job名称"]] = "GETDATE"
        row[_JOBS_COL["job类型"]] = "database"
        row[_JOBS_COL["job的父节点名称"]] = "start"
        row[_JOBS_COL["执行路径信息"]] = sql
        row[_JOBS_COL["job参数"]] = _database_job_params(_schema_of("f_table"), db_name, datasource_type)
        row[_JOBS_COL["job变量设置"]] = var_setting
        row[_JOBS_COL["job调用方法"]] = "sql"
        _fill_engineering(row, 60, 3, 60, "跟随任务", "一次邮件提醒")
        return row

    def _task_deps(task_info):
        """按 dep_type 分流该任务的依赖行：虚拟依赖行在前（构建顺序 §七-3），宽/周期 tskdep 在主 job 后。"""
        virtual, normal = [], []
        for u in task_info.get("upstream", []):
            if not u.get("task"):
                continue
            (virtual if u.get("dep_type") == "虚拟依赖" else normal).append(u)
        return virtual, normal

    project_name, task_group = _resolve_path(tasks_sched.get("f", {}))

    wb = openpyxl.Workbook()

    # --- Sheet 1: tasks（F + view + dq + init）---
    ws = wb.active
    ws.title = "tasks"
    ws.append(TASKS_COLUMNS)

    def _task_row(task_info):
        p, g = _resolve_path(task_info)
        return [p, g, task_info.get("task_name", ""), "周期任务",
                "", "", task_info.get("cron", ""), "是", "", owner,
                "", "", "", "", "", "", "", "", "", "", "", ""]

    all_tasks = []
    for kind in ("f", "view", "dq", "init"):
        ti = tasks_sched.get(kind, {})
        if ti.get("task_name"):
            all_tasks.append(ti)
            ws.append(_task_row(ti))

    # --- Sheet 2: jobs（任务组合模型 §三）---
    ws = wb.create_sheet("jobs")
    ws.append(JOBS_COLUMNS)
    job_rows = []

    f_info = tasks_sched.get("f", {})
    view_info = tasks_sched.get("view", {})
    dq_info = tasks_sched.get("dq", {})
    init_info = tasks_sched.get("init", {})

    if f_info.get("task_name"):
        virtual, normal = _task_deps(f_info)
        for u in virtual:
            _jr0 = _virtual_dep_row(f_info, u)
            ws.append(_jr0)
            job_rows.append(_jr0)
        if incremental:
            _jr1 = _getdate_row(f_info)
            ws.append(_jr1)
            job_rows.append(_jr1)
        _jr2 = _main_job_row(f_info, "GETDATE" if incremental else "start")
        ws.append(_jr2)
        job_rows.append(_jr2)
        for u in normal:
            _jr3 = _tskdep_row(f_info, f_info.get("job_name", ""), u)
            ws.append(_jr3)
            job_rows.append(_jr3)

    if view_info.get("task_name"):
        _jr4 = _view_placeholder_row(view_info)
        ws.append(_jr4)
        job_rows.append(_jr4)
        for u in view_info.get("upstream", []):
            if u.get("task"):
                _jr5 = _tskdep_row(view_info, view_info.get("job_name", ""), u)
                ws.append(_jr5)
                job_rows.append(_jr5)

    if dq_info.get("task_name"):
        _jr6 = _main_job_row(dq_info, "start")
        ws.append(_jr6)
        job_rows.append(_jr6)
        for u in dq_info.get("upstream", []):
            if u.get("task"):
                _jr7 = _tskdep_row(dq_info, dq_info.get("job_name", ""), u)
                ws.append(_jr7)
                job_rows.append(_jr7)

    if init_info.get("task_name"):
        _jr8 = _main_job_row(init_info, "start")
        ws.append(_jr8)
        job_rows.append(_jr8)
        for u in init_info.get("upstream", []):
            if u.get("task"):
                _jr9 = _tskdep_row(init_info, init_info.get("job_name", ""), u)
                ws.append(_jr9)
                job_rows.append(_jr9)

    # --- Sheet 3: taskParams（基础全集 + designer 附加参数）---
    ws = wb.create_sheet("taskParams")
    ws.append(TASKPARAMS_COLUMNS)

    extras = {p.get("lts_var", ""): p for p in (lts_params or [])
              if p.get("lts_var") and p.get("lts_var") not in TASKPARAMS_BASE}
    param_names = TASKPARAMS_BASE + list(extras)
    for ti in all_tasks:
        p, g = _resolve_path(ti)
        for name in param_names:
            if name in LTS_PARAM_TEMPLATES:
                val = LTS_PARAM_TEMPLATES[name]
            elif name == "V_GROUP_CODE":
                val = consts.get("group_code", "")
            elif name == "V_APPID":
                val = appid
            else:
                val = (extras.get(name) or {}).get("value", "")
            ws.append([p, g, ti["task_name"], name, val])

    # --- 出厂校验（§九；路径段/depTaskId/配置缺失在构建期已 fail-loud）---
    problems = validate_lts_package(ts, lts_params, job_rows, set(param_names))
    if problems:
        raise ValueError("LTS 制品出厂校验失败:\n  " + "\n  ".join(problems))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


# ============================================================
# 配置加载
# ============================================================

def load_platform_config(config_path: str = "") -> dict:
    """读 platform_config.json 原始内容。未找到返回空 dict。

    结构：{ default: {shujia, lts}, schema_mappings: {schema: {shujia, lts}} }
    """
    if not config_path:
        config_path = os.environ.get(
            "PLATFORM_CONFIG",
            str(platform_config_path()),
        )
    p = Path(config_path)
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    # 过滤掉 _comment / _structure 等说明字段
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def resolve_config_by_schema(raw_config: dict, schema: str, appid: str = "") -> dict:
    """按 schema 从 platform_config 取两套平台配置。

    查找顺序：schema_mappings[schema] → default。
    术加租户块 shujia_tenants[appid]（org_abbr/datasource）是租户级属性，
    覆盖 schema 级取值（数据源是术加租户属性，单一归属）。
    appid 由调用方传入（main 用 resolve_appid 反查 schema_apps）。
    返回 {shujia: {...含 appid/org_abbr}, lts: {...}}
    """
    if not raw_config:
        return {"shujia": {"appid": appid}, "lts": {}}
    default_cfg = raw_config.get("default", {})
    mappings = raw_config.get("schema_mappings", {})
    schema_cfg = mappings.get(schema, {})
    shujia = {**default_cfg.get("shujia", {}), **schema_cfg.get("shujia", {})}
    if appid:
        tenant = (raw_config.get("shujia_tenants") or {}).get(appid) or {}
        shujia = {**shujia, **{k: v for k, v in tenant.items() if v}}
    shujia["appid"] = appid
    lts = {**default_cfg.get("lts", {}), **schema_cfg.get("lts", {})}
    return {"shujia": shujia, "lts": lts}


def _cfg(config: dict, key: str, fallback: str = "待配置") -> str:
    """安全取配置值，缺失用 fallback。"""
    val = config.get(key, "")
    return val if val else fallback


# ============================================================
# execution_tasks.xlsx 构建
# ============================================================

def _split_schema_table(full: str) -> tuple[str, str]:
    """schema.table → (schema, table)。无 schema 时返回 ("", full)。"""
    if "." in full:
        sch, tbl = full.rsplit(".", 1)
        return sch, tbl
    return "", full


# 查询单列安全长度：Excel 单元格上限 32767，留余量
MAX_SQL_CHUNK = 30000


def _fill_query_columns(row: list, sql: str):
    """查询语句分列：超长 SQL 按 MAX_SQL_CHUNK 切到「查询语句1~9」。

    下游按列号顺序原样拼接非空列（不做 strip/美化），因此任意边界直切即可，
    拼接后逐字还原。
    """
    if len(sql) <= MAX_SQL_CHUNK:
        row[_RULE_COL["(生成的）查询语句1"]] = sql
        return
    chunks = [sql[i:i + MAX_SQL_CHUNK] for i in range(0, len(sql), MAX_SQL_CHUNK)]
    if len(chunks) > 9:
        raise ValueError(
            f"SQL 超长：{len(sql)} 字符，超过 9 列 × {MAX_SQL_CHUNK} 上限，无法装入制品包"
        )
    for n, chunk in enumerate(chunks, start=1):
        row[_RULE_COL[f"(生成的）查询语句{n}"]] = chunk


def _has_separate_init(ts: dict) -> bool:
    """是否发独立的 init 规则组（group_mode=separate 且 init 段有数据规则）。"""
    section = ts.get("init") or {}
    if not isinstance(section, dict) or section.get("group_mode") != "separate":
        return False
    return bool(section.get("rules"))


def _pv_codes(ts: dict) -> list[str]:
    """参数变量规则的占位编码：主组 PV0001；separate init 组追加 PV0002。"""
    return ["PV0001"] + (["PV0002"] if _has_separate_init(ts) else [])


def build_rule_rows(ts: dict, config: dict, etl_dir: Path) -> list[list]:
    """构建 RULE sheet 行。顺序：取数规则 → 参数变量规则（每规则组一行）。

    config: resolve_config_by_schema 返回的 {shujia, lts} 结构。
    术加执行平台配置从 config["shujia"] 取（含租户块解析的 appid/org_abbr）。
    编码为占位符（内网脚本查表替换）：规则组编码 GR_{组英文名}、
    规则编码 = ts 规则码、参数变量行 PV000N。
    子项目编码留空（schema 与子项目 N:M，人工填）。
    视图不发术加规则行：RULE 行规则类型 1 的查询语句列必须是可执行的
    SELECT（平台当取数语句跑），视图 DDL 走 ddl/ 通道部署，不进术加。
    """
    rules = ts.get("rules", {})
    meta = ts.get("meta", {})
    f_table = meta.get("target", {}).get("f_table", {})

    target_short = f_table.get("table", "")
    group_desc = f_table.get("cn", "") or target_short

    shujia = config.get("shujia", {})
    appid = shujia.get("appid", "")
    org_abbr = shujia.get("org_abbr", "")
    data_source = _cfg(shujia, "datasource")
    business_owner = _cfg(shujia, "business_owner", "")
    # 项目只填中文名（人可确认的锚点）；编码/英文名由内网脚本按中文名从平台补齐
    project_cn = _cfg(shujia, "project_cn")
    project_code = ""
    project_en = ""
    # 子项目三件套留空（schema 与子项目 N:M；中文名闸口②人填，编码/英文名脚本补）
    sub_code = ""
    sub_cn = ""
    sub_en = ""

    # init 管道规则（与增量 rules 合并发执行行；inline 靠 P_FLAG 选跑，separate 靠独立 init 任务）
    init_section = ts.get("init") or {}
    init_rules = (init_section.get("rules") or {}) if isinstance(init_section, dict) else {}
    init_group_mode = (init_section.get("group_mode") or "") if isinstance(init_section, dict) else ""
    # 合并迭代：增量规则 + init 规则，标记 is_init
    merged = [(c, r, False) for c, r in rules.items()]
    merged += [(c, r, True) for c, r in init_rules.items()]

    rows = []
    group_code = f"GR_{target_short}"
    init_group_name = f"{target_short}_init"
    init_group_code = f"GR_{init_group_name}"

    # 公共列填充（每行都要填的项目）
    def _fill_common(row):
        row[_RULE_COL["租户ID"]] = appid                # 租户ID = appid（schema_apps 反查）
        row[_RULE_COL["组织英文简称"]] = org_abbr        # 术加租户名（shujia_tenants[appid]）
        row[_RULE_COL["类型"]] = "3"
        row[_RULE_COL["项目编码"]] = project_code
        row[_RULE_COL["项目中文名"]] = project_cn
        row[_RULE_COL["项目英文名"]] = project_en
        row[_RULE_COL["子项目编码"]] = sub_code
        row[_RULE_COL["子项目中文名"]] = sub_cn
        row[_RULE_COL["子项目英文名"]] = sub_en
        row[_RULE_COL["规则组编码"]] = group_code        # 占位符，内网脚本替换
        row[_RULE_COL["规则组中文名称"]] = target_short
        row[_RULE_COL["规则组英文名称"]] = target_short
        row[_RULE_COL["规则组描述"]] = group_desc
        row[_RULE_COL["规则组数据源"]] = data_source
        row[_RULE_COL["规则组业务责任人"]] = business_owner

    # --- 取数规则（每条 ETL SQL 一行）---
    for code, rule, is_init in merged:
        # 读 ETL SQL 文件
        sql_file = etl_dir / f"{code}.sql"
        if not sql_file.exists():
            # 尝试模糊匹配
            candidates = list(etl_dir.glob(f"*{code}*.sql"))
            sql_file = candidates[0] if candidates else None
        query_sql = sql_file.read_text(encoding="utf-8").strip() if sql_file and sql_file.exists() else ""

        target = rule.get("target_table", "")
        sch, tbl = _split_schema_table(target)

        row = [""] * len(RULE_COLUMNS)
        _fill_common(row)
        # separate 模式：init 规则进独立规则组（_init 后缀），跟增量区分（init 任务跑这个组）
        if is_init and init_group_mode == "separate":
            row[_RULE_COL["规则组编码"]] = init_group_code
            row[_RULE_COL["规则组中文名称"]] = init_group_name
            row[_RULE_COL["规则组英文名称"]] = init_group_name
        row[_RULE_COL["规则编码"]] = code                # 占位符 = ts 规则码，内网脚本替换
        row[_RULE_COL["规则中文名称"]] = tbl or target
        row[_RULE_COL["规则英文名称"]] = tbl or target
        row[_RULE_COL["创建方式"]] = "2"
        row[_RULE_COL["规则类型"]] = "1"
        row[_RULE_COL["数据源"]] = data_source
        _fill_query_columns(row, query_sql)
        row[_RULE_COL["规则描述"]] = rule.get("design_intent", "")
        # 执行序列决定加工拓扑（中间表步骤必须先于消费步骤），从 ts 透传
        row[_RULE_COL["执行序列"]] = str(rule.get("exec_sequence", 1))
        # 运行条件：inline 靠 P_FLAG 选 init/增量管道；separate/无 init → "0"
        if init_group_mode == "inline":
            row[_RULE_COL["运行条件"]] = "${P_FLAG}='2'" if is_init else "${P_FLAG}='1'"
        else:
            row[_RULE_COL["运行条件"]] = "0"
        row[_RULE_COL["目标Schema"]] = sch
        row[_RULE_COL["目标表"]] = tbl
        # 删除模式 + 删除条件：从 ts.json 的 load_mode + write_condition 映射（不再硬编码"1"）
        load_mode = rule.get("load_mode", "truncate_table")
        write_condition = rule.get("write_condition", "")
        delete_mode_map = {
            "truncate_table": "1", "no_delete": "2", "delete": "4",
            "truncate_partition": "5", "merge_into": "6", "update": "6",
        }
        row[_RULE_COL["删除模式"]] = delete_mode_map.get(load_mode, "1")
        if write_condition:
            row[_RULE_COL["删除条件"]] = write_condition
        row[_RULE_COL["业务责任人"]] = business_owner
        row[_RULE_COL["行迁移开关"]] = "1"
        row[_RULE_COL["并行开关"]] = "0"
        row[_RULE_COL["数据库类型"]] = "GaussDB"
        row[_RULE_COL["调度类型"]] = "0"
        row[_RULE_COL["来源表统计分析收集"]] = "0"
        rows.append(row)

    # --- 参数变量规则（每规则组一行；主组恒有，separate init 组有规则时加一行）---
    # 形态：中文名"参数变量规则"/英文名"Parameter Variable Rule"、创建方式 1、
    # 规则类型 12、执行序列 -1；查询语句/运行条件等留空。变量本身登记在
    # GroupVariables sheet（按本行占位码挂引用），不占 RULE 行。
    def _pv_row(group_name: str, group_code_: str, pv_code: str) -> list:
        row = [""] * len(RULE_COLUMNS)
        _fill_common(row)
        row[_RULE_COL["规则组编码"]] = group_code_
        row[_RULE_COL["规则组中文名称"]] = group_name
        row[_RULE_COL["规则组英文名称"]] = group_name
        row[_RULE_COL["规则编码"]] = pv_code              # 占位符，内网脚本替换
        row[_RULE_COL["规则中文名称"]] = "参数变量规则"
        row[_RULE_COL["规则英文名称"]] = "Parameter Variable Rule"
        row[_RULE_COL["创建方式"]] = "1"
        row[_RULE_COL["规则类型"]] = "12"
        row[_RULE_COL["执行序列"]] = "-1"
        row[_RULE_COL["业务责任人"]] = business_owner
        row[_RULE_COL["行迁移开关"]] = "0"
        row[_RULE_COL["并行开关"]] = "0"
        row[_RULE_COL["数据库类型"]] = "GaussDB"
        row[_RULE_COL["调度类型"]] = "0"
        return row

    rows.append(_pv_row(target_short, group_code, "PV0001"))
    if _has_separate_init(ts):
        rows.append(_pv_row(init_group_name, init_group_code, "PV0002"))

    return rows


def build_group_variables(ts: dict) -> list[list]:
    """构建 GroupVariables sheet 行。按参数变量规则的占位码挂引用。

    参数来源：ts.json meta.schedule.exec_params。separate init 模式下
    每个规则组各挂一份（组自含），分别指向该组 pv 行的占位码。
    """
    exec_params = ts.get("meta", {}).get("schedule", {}).get("exec_params", {})
    rows = []
    for pv_code in _pv_codes(ts):
        for pname in sorted(exec_params.keys()):
            # 默认值从 ts.default_value 读（static 给值；dynamic 留空让平台运行时注入）
            pdecl = exec_params.get(pname) or {}
            dv = pdecl.get("default_value")
            if isinstance(dv, dict):
                default_val = dv.get("value", "") if dv.get("type") == "static" else ""
            elif dv is not None and dv != "":
                default_val = str(dv)
            else:
                default_val = ""
            desc = pdecl.get("desc", "") if isinstance(pdecl, dict) else ""
            rows.append([
                pv_code,      # 规则编码（占位 = 参数变量规则行）
                pname,        # 动态参数/变量名
                "1",          # 字段类型
                "1",          # 字段定义类型
                "1",          # 字段值类型
                default_val,  # 变量默认值
                "1",          # 是否校验通过
                "",           # 数据类型
                desc,         # 描述（ts exec_params.desc）
                "",           # 是否必填
            ])
    return rows


def build_target_fields(ts: dict) -> list[list]:
    """构建 TargetFields sheet 行。从 tables 段取字段定义，过滤审计字段。

    字段来源优先级：tables[target_table].fields → rule.fields（旧格式兼容）。
    规则编码 = ts 规则码（占位符，与 RULE 行对应）。
    """
    from ts_compat import normalize_ts
    rules = normalize_ts(ts).get("rules", {})
    rows = []
    for code, rule in rules.items():
        fields = rule.get("fields") or {}
        # 三桶展开为 (target, 源列名) 对；来源列取首个引用/直取列（登记形态固定
        # s.字段——s 是平台标准别名，与规则 SQL 内表别名无关）；赋值/无源留空
        pairs = []
        for _p in fields.get("processed", []):
            refs = _p.get("refs") or []
            first = str(refs[0]).rsplit(".", 1)[-1].strip() if refs else ""
            pairs.append((_p.get("target", ""), first))
        for _a in fields.get("assign", []):
            pairs.append((_a.get("target", ""), ""))
        for _d in fields.get("direct", []):
            _base = str(_d).split(" AS ")[0].strip()
            _t = str(_d).rsplit(" AS ", 1)[-1].strip() if " AS " in str(_d) else _base.rsplit(".", 1)[-1].strip()
            pairs.append((_t, _base.rsplit(".", 1)[-1].strip()))

        for target_field, col in pairs:
            if not target_field or target_field.lower() in AUDIT_FIELDS:
                continue
            src_field = f"s.{col}" if col else ""
            rows.append([
                code,               # 规则编码（占位 = ts 规则码）
                target_field,       # 目标字段名称
                src_field,          # 来源字段名称（s.字段 / 空）
                "0",                # 加密方式
                "",                 # Merge模式数据源字段值
                "",                 # 别名（不填）
                "",                 # 字段类型
                "",                 # 备注
            ])
    return rows


def validate_code_closure(rule_rows: list[list], gv_rows: list[list], tf_rows: list[list]) -> list[str]:
    """出厂校验：占位编码三处引用闭合（这是"Excel 出厂即标准"的硬约束）。

    - RULE 规则编码非空且不重复；规则组编码非空
    - TargetFields / GroupVariables 的规则编码必须在 RULE 行能找到（不悬挂）
    返回问题列表（空 = 通过）。
    """
    problems = []
    codes = [r[_RULE_COL["规则编码"]] for r in rule_rows]
    for r, c in zip(rule_rows, codes):
        if not c:
            problems.append("RULE 行规则编码为空")
        if not r[_RULE_COL["规则组编码"]]:
            problems.append(f"规则 {c or '?'} 的规则组编码为空")
    dups = sorted({c for c in codes if c and codes.count(c) > 1})
    if dups:
        problems.append(f"RULE 规则编码重复: {dups}")
    code_set = set(codes)
    for row in tf_rows:
        if row[0] not in code_set:
            problems.append(f"TargetFields 规则编码悬挂: {row[0]!r}")
    for row in gv_rows:
        if row[0] not in code_set:
            problems.append(f"GroupVariables 规则编码悬挂: {row[0]!r}")
    return problems


def generate_execution_excel(ts: dict, config: dict, etl_dir: Path, output_path: Path):
    """生成 execution_tasks.xlsx（10 sheet）。出厂前做占位编码闭合校验。"""
    rule_rows = build_rule_rows(ts, config, etl_dir)
    gv_rows = build_group_variables(ts)
    tf_rows = build_target_fields(ts)

    problems = validate_code_closure(rule_rows, gv_rows, tf_rows)
    if problems:
        raise ValueError("制品包占位编码校验失败:\n  " + "\n  ".join(problems))

    wb = openpyxl.Workbook()

    # Sheet 1: RULE
    ws = wb.active
    ws.title = "RULE"
    ws.append(RULE_COLUMNS)
    for row in rule_rows:
        ws.append(row)

    # Sheet 2: GroupVariables
    ws = wb.create_sheet("GroupVariables")
    ws.append(GROUPVARS_COLUMNS)
    for row in gv_rows:
        ws.append(row)

    # Sheet 3: TargetFields
    ws = wb.create_sheet("TargetFields")
    ws.append(TARGETFIELDS_COLUMNS)
    for row in tf_rows:
        ws.append(row)

    # Sheet 4-10: 空 sheet（保留表头，跟 legacy 一致）
    empty_sheets = [
        ("ModelRelations", MODELRELATIONS_COLUMNS),
        ("ExtraFields", EXTRAFIELDS_COLUMNS),
        ("SPParams", SPPARAMS_COLUMNS),
        ("Conditions", CONDITIONS_COLUMNS),
        ("MaintenanceParams", MAINTENANCEPARAMS_COLUMNS),
        ("Extract", EXTRACT_COLUMNS),
        ("ExtractColumn", EXTRACTCOLUMN_COLUMNS),
    ]
    for sheet_name, columns in empty_sheets:
        ws = wb.create_sheet(sheet_name)
        ws.append(columns)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="平台制品包 exporter（UT 通过后调用）")
    parser.add_argument("--ts", required=True, help="ts.json 路径")
    parser.add_argument("--etl-dir", required=True, help="ETL SQL 目录（etl/）")
    parser.add_argument("--ddl-dir", default="", help="（兼容保留，已不使用：视图不发术加规则行）")
    parser.add_argument("--outdir", required=True, help="产出根目录（export/ 建在此下）")
    parser.add_argument("--config", default="", help="platform_config.json 路径")
    args = parser.parse_args()

    ts_path = Path(args.ts)
    etl_dir = Path(args.etl_dir)
    export_dir = Path(args.outdir) / "export"

    # 读 ts.json
    if not ts_path.exists():
        print(f"错误: ts.json 不存在: {ts_path}", file=sys.stderr)
        sys.exit(1)
    ts = json.loads(ts_path.read_text(encoding="utf-8"))

    # 读配置（按目标表 schema 映射两套平台配置；appid 从 schema_apps 反查，
    # 注入 shujia 段 → 租户ID 列 + shujia_tenants 租户块解析）
    raw_config = load_platform_config(args.config)
    target_schema = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", "")
    appid = resolve_appid(target_schema)
    config = resolve_config_by_schema(raw_config, target_schema, appid)

    # 产出（文件名带平台标识 + 表名，便于多资产区分）
    target_short = ts.get("meta", {}).get("target", {}).get("f_table", {}).get("table", "unknown")
    exec_path = export_dir / f"shujia_{target_short}.xlsx"
    sched_path = export_dir / f"lts_{target_short}.xlsx"

    generate_execution_excel(ts, config, etl_dir, exec_path)
    generate_schedule_excel(ts, config, sched_path)

    print("=" * 50)
    print("平台制品包已生成:")
    print(f"  {exec_path}")
    print(f"  {sched_path}")
    print(f"  目标表: {ts.get('meta', {}).get('target', {}).get('f_table', {}).get('table', '')}")


if __name__ == "__main__":
    main()
