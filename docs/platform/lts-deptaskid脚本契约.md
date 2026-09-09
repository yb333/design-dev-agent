# 内网查 depTaskId 脚本·对接契约

> 目的：LTS 跨集群依赖（tskdep）需要远端任务组 id `depTaskId`。该 id 按平台规律**按（生产集群, itemName, taskGroupName）三元组固定**、无法推导，故由生成端调用本脚本实时查询。
> 调用方：数据交付流水线的 LTS 制品生成（`assemble_export` → `dep_task_id`）。**调用方式我方固定，脚本本体内网侧实现/维护**。缓存（30 天 TTL）与失败兜底我方负责，脚本只管"给参数 → 返回 id"。
> 使用场景（2026-09-09 定调收敛）：仅**跨集群 · job 级依赖**（f 任务的上游湖表依赖，主场景）需要查 id；同集群依赖（资产内 I→F）挂任务 end 节点无 id，不调本脚本。

---

## 一、调用方式（我方固定，含脚本命名）

**脚本文件名固定为 `query_deptaskid.py`**（或内网现成脚本定稿的唯一名，一经登记不变）——杜绝多版本/路径漂移。调用命令：

```
python <脚本绝对路径> --cluster <生产集群名> --item <远端调度组/itemName> --group <远端任务组/taskGroupName> --task <远端任务名/depTaskName> --job <被依赖job名/depJobName>
```

- 五个参数以**命令行参数**传入（shell 调用），脚本需自行处理含空格/特殊字符/中文的引号安全
- **非交互**：一问一答即退出，不得有确认提示/菜单/人工输入
- 超时：我方按 30 秒（可配）掐断，脚本内部对网页/接口的访问请自设超时并在超时时非零退出
- 运行环境：内网 Windows，`python` 命令可直接执行

## 二、输入

| 参数 | 含义 | 示例 |
|---|---|---|
| `--cluster` | 被依赖任务所在的生产集群名 | `fin_oracc` |
| `--item` | 远端调度组（itemName） | `DIM_SYNC_GAUSS_DAILY` |
| `--group` | 远端任务组（taskGroupName） | `EDW_PROD1` |
| `--task` | 远端任务名（depTaskName，被依赖 job 所属的任务） | `TASK_DIM_DW1_DWRDIM_INTERFACE_SCHEDULE` |
| `--job` | **被依赖的 job 名（depJobName）** | `PJob_INTERFACE_DWR_DIM_CONTRACT_D` |

**id 粒度：job 级——一个被依赖 job 对应一个 depTaskId**（跨集群依赖挂远端任务下的具体 job，id 是那个 job 的平台 id）。前四个参数定位到远端任务，`--job` 唯一确定依赖对象，五个参数缺一不可。一期只查**生产**；将来如扩展测试环境会在命令行追加 `--env` 参数（接口预留，届时提前通知）。

## 三、输出（二选一，注册时告知我方用哪种）

**推荐 JSON 模式**——stdout 打印一行 JSON，id 放在 `depTaskId` 字段：

```json
{"depTaskId": "20224946"}
```

**备选 TEXT 模式**——stdout 首个非空行就是纯 id（如 `20224946`）。

硬性要求：
1. **stdout 只放结果**：进度/日志一律走 stderr（stdout 混入日志会破坏解析）
2. **查到**：exit code 0 + 按上述格式输出 id
3. **查不到/出错**：非零 exit code（或输出空值）——我方统一按"查询失败"处理，向操作员报出可手工执行的完整命令
4. 纯查询、幂等、无任何写操作

## 四、脚本放在哪

- **内网侧自选固定路径维护**（建议放内网团队自己的工具目录，不放进我方 skill/config 目录——升级互不影响）
- 定稿后把**绝对路径**告知我方，我方登记在 `platform_config.json → lts.dep_id_resolver.script`，配合 `cmd_template` 使用（占位符 `{script}/{cluster}/{item}/{group}/{task}/{job}` 由我方替换）
- 要求该路径对执行流水线的机器/账号可读可执行

## 五、我方负责的部分（脚本无需关心）

- **缓存**：查到的 id 本地缓存 30 天，TTL 内不重复调用脚本（id 三元组固定，缓存安全）
- **优先级**：人工确认表 > 缓存 > 调脚本（脚本只在表和缓存都没有时被调）
- **失败兜底**：脚本失败/超时 → 我方报错并给出完整命令，人工查得后填人工表，不堵交付
- **留痕**：每次调用（命令/stdout/stderr/解析结果）落盘诊断目录

## 六、联调验收（三步）

1. **手工样例**：`python query_deptaskid.py --cluster fin_oracc --item DIM_SYNC_GAUSS_DAILY --group EDW_PROD1 --task TASK_DIM_DW1_DWRDIM_INTERFACE_SCHEDULE --job PJob_INTERFACE_DWR_DIM_CONTRACT_D` → stdout 得到 `{"depTaskId": "20224946"}`（真实历史样本，可直接验收）
2. **接我方流水线**：给一个新三元组走一次 LTS 生成，确认脚本被调用、id 进制品、我方诊断目录留痕
3. **故障演练**：给一个不存在的三元组，确认非零退出 → 我方报错含可手跑命令，交付不被卡死
