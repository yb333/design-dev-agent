# eval-suite 评测系统

> **一句话**：评测 = 真实入口跑完整 new-pipe（`nga/opencode run --command new-pipe`）+
> 只对产出做两级断言评分；golden 是人审的标准答案；全程零交互。
>
> 三条设计红线：golden 只能人手工沉淀（语义判断不自主）／评测不重放编排
> （100% 走 commands/new-pipe.md，零拷贝漂移）／批量跑不问任何问题
> （需要人判断的一律落报告）。

---

## 〇、能力总览

| 能力 | 一句话说明 | 入口 |
|---|---|---|
| 真实入口评测 | 调真实 new-pipe 命令跑全流程（含 UT 连库），对产出断言评分 | menu[1] / `run.py --case X` |
| 只评测已有产出 | 不重跑，对三层产出直接断言 | menu[2] / `--eval-only` |
| 断言草稿 | 从产出抽事实生成 checks.yaml 草稿（人 review 固化） | menu[3] / `seed.py` |
| 稳定性测量 | 同案例连跑 N 次：及格率/分数趋势/断言摇摆/阶段耗时分布/执行回路 | menu[4] / `--repeat N` |
| golden 沉淀 | 把实际调测认可的产出手工拷成标准答案（多方案并存=多解兼容） | menu[5] / `promote.py` |
| 历史分析 | 跨轮趋势（早期vs晚期）+ 跨案例总览 | menu[6] / `history.py` |
| 阶段可观测 | 命令回显/心跳动画（并行组+回路计数）/live log/超时收割/崩溃隔离 | 内置 |
| 两级评分 | 及格=致命项零失败（交付安全）；非致命只扣分做趋势 | 内置 |

## 一、目录约定（东西放哪，看这张表）

| 角色 | 位置 | 说明 |
|---|---|---|
| 虚拟案例 | `eval-suite/cases/{资产}/` | 001~012 + T 系列陷阱，git 入库 |
| **真实案例输入/要点** | `eval-suite/cases_real/{分类}/{资产}/` | 分类名自由命名；gitignore，内网放 |
| deliver_only 临时落点 | `cases_real/未分类/{资产}/` | 只有产出没输入的案例 seed 时自动建，后续 mv |
| **golden（标准答案）** | `cases_real/{分类}/{资产}/golden/{方案名}/` | 一份完整认可产出，**只能人手工沉淀** |
| **流程产出（三层唯一）** | `10_project_deliver/{appid}/{schema}/{资产}/ddlc_design_dev/` | new-pipe 自建；平铺老结构**不识别** |
| 评测存档 | `results/{case}/{时间戳}/result.json` | 每轮快照：score/passed/deductions/stage_times/stage_loops/checks/git_sha |
| 稳定性报告 | `results/{case}/{时间戳}/stability_report.md` | --repeat 跑完自动落盘 |
| 异常轮留档 | `results/{case}/{时间戳}/artifacts/` | 仅不及格/越界轮拷完整产出 |
| 实时全文 log | `results/_live/{阶段}.log` | 安静模式也能随时看子进程在干嘛 |
| 失败诊断全文 | 产出 `_internal/diagnose/pipeline_{阶段}.log` | 阶段挂了看这里 |

**命名贯通规则**：`案例目录名 = 资产表名`（三层产出按它定位）；输入文件按后缀发现
（目录里唯一的 xlsx/xls = mapping，唯一的 md/txt = RS 可选；评测自己的 yaml/json 不干扰）。

## 二、命令

```bash
./eval.sh                                    # 交互式菜单（7项，推荐）
python3 eval-suite/v2/run.py --case 002                     # 单案例：真实入口全流程+评测（默认）
python3 eval-suite/v2/run.py --case 002 --eval-only          # 只评测已有产出
python3 eval-suite/v2/run.py --case 002 --replay             # 分阶段重放（诊断：定位哪个阶段挂/慢）
python3 eval-suite/v2/run.py --all --cases-dir=eval-suite/cases_real
python3 eval-suite/v2/run.py --case X --repeat 10            # 稳定性：连跑10次
python3 eval-suite/v2/run.py --case X --timeout-pipe 7200    # 真实流程超时（默认3600s）
python3 eval-suite/v2/run.py --case X --replay --skip-ai     # 重放+跳AI（脚本链路快查）
python3 eval-suite/v2/run.py --case X --opencode <路径>      # 启动器显式指定
python3 eval-suite/v2/run.py --case X --verbose              # 实时全量输出（调试）
python3 eval-suite/v2/seed.py --case X --cases-dir=... --review [--from <产出路径>]
python3 eval-suite/v2/promote.py --case X [--name 方案A] [--from <产出路径>]
python3 eval-suite/v2/history.py --case X    # 或 --all
```

## 三、断言体系（五层）

| 层 | 判什么 | 归因 |
|---|---|---|
| 流程层 | 真实入口单步（跑没跑出东西）；重放模式逐阶段 | 脚本/契约/案例数据 |
| 产物层 | ts 结构/文件齐全/回退成对/**DDL自洽（列⊇ts/基类型/分布键/视图列/回退DROP）** | assemble_ddl（不一致即其锅） |
| design 质量 | business_key/规则集/load_mode 契约 + **ts类型vs mapping输入类型** + 默认检查 | designer / 脚本 |
| code 质量 | **字段覆盖契约（SELECT⊇field_targets，零配置）** + 配置类断言 | coder |
| golden 命中 | 八维指纹 vs 人审 golden 集合（命中任一即过） | 待人工裁决 |

**checks.yaml 可用键全清单**（写错键名直接报错，防 typo 静默失效）：

```yaml
case:
  name: 展示名
  rules_expected: [R0001]              # 规则集合契约（严格相等）
design:                                 # 只写钉死点，默认项不写
  business_key: [order_id]             # 陷阱/强契约场景
  load_mode_expected: {R0001: merge_into}
  source_tables_required: [ods.a, ods.b]
  field_not_mapped_from: {field: x, not_from_table: y}   # 禁止式（陷阱用）
code:
  R0001:
    fields_required: [...]             # L3 上线后可不写（覆盖契约自动）
    join_tables: [...]
    group_by_granularity: [...]
    where_must_contain_del_flag: false # 开关只在关时写
scoring: {fatal: 30, structure_std: 3}  # 权重覆盖（只写要改的）
```

## 四、golden：命中算法与纪律

**八维指纹全等才命中**（提取时归一化：排序/小写/SQL 写法无关）：
business_key、规则集、load_mode、field_targets、表结构（类型/分布键/build_mode，
**表名是 key**）、规则数据流（源表/目标表）、DDL（每表列+类型，**基类型比对**）、
SELECT 口径签名（每字段 refs/aggs/consts——CAST/COALESCE 包裹不改签名；
SUM vs 裸列/引用错列/常量变值都 diff）。

**miss 自解释**：逐维度并排证据（`business_key: golden=[..] | 实际=[..]`），
命中不了自己就能看出差在哪。**严格命中不归一化**——表命名有标准，不合标准就是要暴露。

**纪律**：①promote.py 是纯拷贝工具，认不认可永远人定，系统绝不自动推；
②多 golden 并存=多解兼容（方案A/B/C 命中任一即过）；③典型循环：实际调测出认可
产出 → promote 沉淀 → --repeat 批量测 → 未命中轮 → 人裁决（新方案再 promote / 回归去修）。

## 五、评分（两级：致命门 + 非致命扣分）

**及格 = 致命项零失败**（不是分数阈值）——"结果准确、不影响交付"：

- **致命（各-20，任一=不及格）**：流程没跑通／字段不全（SELECT漏/DDL缺列/覆盖不全/
  视图缺列）／类型不符（DDL↔ts 基类型、ts↔mapping 输入类型）／加工逻辑错
  （口径 refs/aggs 与 golden 不一致）／business_key、load_mode、规则集契约错
- **非致命（只扣分）**：表结构/数据流/GROUP_BY/JOIN 漂移 -5、口径常量 -2、
  类型精度 -2（varchar50 vs 100：可见可扣分不拦及格）、其他断言 -6~8
- **根因去重**：契约断言已扣的维度，golden 同维度差异只展示证据不重复扣
- 退出码挂钩及格门：不及格=exit 1；golden 结构性未命中但交付安全=exit 0
- 无 golden：加工逻辑项无参照（自洽兜底），报告标注及格含金量打折

## 六、稳定性报告 & 历史分析

**--repeat N 报告**：每轮结果（✔/✘及格标记+分数+golden 命中）／及格率／分数趋势／
**阶段耗时分布**（跨轮 avg/min/max）／**执行回路**（UT 挂了回 coder 的频率——流程质量
核心指标）／断言稳定性（稳定过/稳定挂/摇摆）／golden 命中分布／阶段通过率。

**历史分析**：`history.py --case X`（轮次明细/分数趋势/阶段耗时**早期vs晚期**——直接
回答优化效果）/ `--all`（跨案例：平均分/耗时/最耗时阶段/回路率）。

## 七、执行引擎细节

- **启动器**：`--opencode`/EVAL_OPENCODE → `nga`（内网包壳）→ `opencode`。
  已内置 Windows PATHEXT 解析（WinError 2 修复）+ 管道 UTF-8 解码（GBK 崩溃修复）
- **重复跑清场（★稳定性前提）**：同资产重跑前默认清空其 ddlc_design_dev（旧产出会被
  AI 复用，--repeat 10 只有第 1 轮是真跑）；护栏：只删 DELIVER_BASE 下的
  ddlc_design_dev；`--keep-artifacts` 跳过（迭代优化场景钩子）；eval-only 不清
- **输出模式**：默认安静——`$ 命令回显`/`▶ 阶段横幅`/`✅❌ 结果` + 心跳动画
  `⠹ new-pipe 真实流程 187s · 阶段:DDL生成+DQ生成+规则编码(3个SQL)(并行) · 45行/12KB · 静默3s`。
  阶段由**双信号**反推：输出流锚点（顶层 pipe 的脚本/agent 调用）+ 产出文件
  marker（subagent 内层活动顶层流看不到——设计/编码靠 designer/coder 写的
  文件事件补，秩守卫只前进不回退）；编码段是**并行组**（不互吞）；流锚点重现=
  **执行回路**计数（文件事件永不制造假回路）；静默>60s 切 ⚠（卡住和长思考区分不了就如实说，
  超时兜底收割）；全文实时落 `_live/`；`--verbose` 切全量上屏
- **超时**：真实流程 3600s / 重放 AI 1800s、脚本 120s；超时 kill 不拖垮整轮
- **崩溃隔离**：单案例崩批次继续、单轮崩剩余轮继续、干净报错替代裸 traceback
- **重放定位**：无既有产出时按 schema（mapping 目标表）+ appid（schema_apps.json）
  推导三层路径；查不到明确报错

## 八、故障排查速查

| 症状 | 原因/解法 |
|---|---|
| WinError 2 找不到启动器 | npm 装 .cmd Popen 不认 → 内置 which 解析；不行 `--opencode` 传全路径 |
| UnicodeDecodeError gbk | 子进程 UTF-8 遇 GBK 解码 → 已强制 UTF-8+replace |
| golden 命中不了 | 看 miss 并排证据；常见：中间表改名/常量漂移/类型精度 |
| 三层产出找不到 | 案例目录名≠资产表名？schema_apps.json 没配 schema？seed 可 `--from` 指旧产出 |
| 跑到一半不动了 | 看 ⚠ 静默秒数 + `_live/` 全文；超时上限内会自动收割 |
| 结果不可信（版本差） | 快照带 git sha；跑前重跑 install.py 或确认走 repo 源（默认 repo 优先） |
