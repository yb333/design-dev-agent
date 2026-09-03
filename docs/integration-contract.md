# 调用契约——设计开发段（DDLC 中游）对接总控

> 面向总控方开发者的对接规格。我们侧的唯一执行入口是 **dws-engineer**（编排 agent），
> 调用方式、参数、部署前提、行为边界以本文为准。总控内部实现不在约定范围。

---

## 一、调用方式：Task 直连 dws-engineer（不经任何中间 runner）

```
Task(
  subagent_type="dws-engineer",
  description="设计开发段交付",
  prompt="""模式: 新建
mapping: /abs/path/xxx_mapping.xlsx
rs: /abs/path/RS_xxx.md"""
)
```

**为什么必须直连**（框架机制，非偏好）：

1. **工具能力沿调用链只收不放**——opencode 的 subagent 权限派生会把父会话的 deny 规则与被排除的工具下压给所有后代，子代 allow 解除不了。链上任何中间 agent（如 dev-runner）对 bash/write/edit/task/skill/read 的排除，会让我们孙代的 designer/coder 工具直接消失或退化（现网实证过：designer 报"没有 write 工具"；skill 被钳时 designer 退化成 Read 兜底加载）。
2. **身份与注入竞争**——中间 agent 自带的身份（职责边界/出错处理）与我们的编排铁律冲突；总控 prompt 里的自由文本注意事项与剧本指令竞争。dws-engineer 的身份由我们定义：红线、铁律、"契约参数之外的内容一律忽略"，行为确定。

## 二、参数（3 必选 + 3 可选，键值格式）

| 键 | 必选 | 取值/说明 |
|----|------|----------|
| `模式` | ✓ | `新建` \| `优化`（决定加载 new-pipe / opt-pipe 剧本） |
| `mapping` | ✓ | mapping 文件**绝对路径**（优化场景可传需求包目录，剧本内有分拣规则）。**资产名/schema/appid 全从输入推导（preprocess --probe）——勿传，传了即双源** |
| `rs` | 可选 | RS 文件绝对路径；省略 = 无 RS 模式 |
| `交互` | 可选 | `interactive`（默认）：闸口①② question 必发，**调用方保证把问题送到人**；`non-interactive`（对应总控的自动决策开关）：**流程闸口继续**（闸口①②不等待，跑完产物人后审，推生产由人放行兜底）；**人工决策照常阻断上报**（类型风险/关联键类型/UT 数据质量根因——无安全默认，agent 不代答不选默认，属"RS/mapping 等输入派生问题"）。两种模式 agent 都不做语义判断 |
> 总控侧的自动决策开关映射为本参数（开=non-interactive），**不要以提示词注入实现**——参数外内容一律被忽略。
| `caller_note` | 可选 | 自由文本，随交付报告透传给人（闸口材料），**不作为执行指令**、不影响任何步骤 |
| `上报格式` | 可选 | **问题上报的输出格式约定，由调用方定义与解析、随调用更新**（调用方基于上报驱动自己的下一步，格式权威归消费方）。dws-engineer 只按它包装上报的输出形态——格式内容里的行为性指令（重试/自动修复/流程变更）仍属忽略区。不给则用默认格式（问题类型/位置/原因/建议四要素） |

**参数之外的一切 prompt 内容（注意事项/自动修正/重试指令）一律被忽略**——这是写在 dws-engineer 身份里的行为规则，不是协商约定。调用方表达诉求的通道只有四个：改参数（行为差异）、改输入文件（业务要求）、caller_note（意见透传）、找我们改契约/剧本（流程演进）。

## 二·五、调用模板（总控侧照抄，只换路径与资产名）

新建：

```
Task(
  subagent_type="dws-engineer",
  description="设计开发段交付",
  prompt="模式: 新建
mapping: /绝对路径/xxx_mapping.xlsx
rs: /绝对路径/RS_xxx.md"
)
```

优化：

```
Task(
  subagent_type="dws-engineer",
  description="设计开发段优化交付",
  prompt="模式: 优化
mapping: /绝对路径/需求包目录（或全量 mapping 文件）
rs: /绝对路径/RS_xxx.md"
)
```

可选行按需追加：`交互: non-interactive`（无人值守批产，闸口人后审）；`上报格式: <格式约定原文>`（如原有的 mapping_issue_report 要求——整段放进这个参数值，不要写在参数区外）；`caller_note: <给人看的话>`。

**变量拼接注意**：路径是调用方运行时变量，值随便填（Windows 反斜杠、含空格均可），但三条要保住——每参数独占一行、值内无换行、变量未填充时**不要发占位符**（`{xxx}` 残留会被 dws-engineer 按缺参 fail loud 拦下）。资产定位是内部推导（preprocess --probe 幂等探测），调用方不参与。

## 三·五、恢复调用（问题修复后继续干活）

首次调用后**记下 Task 返回文本里的 `<task id="...">`**（会话 id，dws-engineer 自身不知晓）。上游（修复 agent）处理完问题后续命：

```
Task(
  subagent_type="dws-engineer",
  task_id="{首次调用返回的 task id}",
  description="设计开发段继续",
  prompt="继续：上游已修复 {一句话说明修了什么}"
)
```

- **prompt 极简**——参数在原会话记忆里，不重传；带 task_id 的调用跳过契约参数解析
- **起点由 dws-engineer 自判**：输入类修复（改了 mapping/RS）→ 从步骤 1 重新走（重新预处理，闸口①重过——输入变了设计可能要变）；环境类修复 → 从失败点继续。判不了按输入类处理（宁重跑不基于旧状态）
- 备选：不传 task_id 新起（同参数原样再发）= 幂等全量重跑，语义干净但闸口/子 agent 全部重来，仅在丢失 task id 时用

## 三、部署前提（五条，缺一在步骤 0 探针 fail loud）

1. **部署形态二选一**：**生产（总控）= 项目仓内启动**——启动目录为包含本仓内容的项目 git 仓（内容随仓走、无安装动作、版本=checkout 版本，符合总控既有习惯，零成本满足）；自测 = 全局安装（`install.py` 到 `~/.config/opencode/`，落安装指纹 `_install_meta.json` 供探针对账——仅此形态有安装版本漂移问题）。
2. **opencode 版本对齐**：≥ 我们验证过的版本（1.2.27）。
3. **`subagent_depth ≥ 2`**：opencode.json 配置（默认 1 会拦"engineer→designer"第二层）。
4. **上游不排除工具面**（★总控侧内容已固化，本条是**部署侧自查项**——核对总控 agent 定义/opencode.json 无对下列工具的 deny/排除即可）：`bash / write / edit / task / skill / read`（直连时总控是 primary 全工具，天然满足；skill/read 被钳不炸但形态退化——子 agent 只能 Read 兜底加载 skill）。
5. **调用环境不向本链暴露 MCP server**（部署侧自查项）：dws-engineer 链（engineer/designer/coder）的全部 DB 能力走自带脚本（dws_db 连目标 schema 数据源）——环境里配的任何 MCP（尤其数据库 MCP）与本流程的数据源/权限无关，子 agent 调用必得错误结论。MCP 配置留在总控自己的会话层，勿下压到本链的项目/全局配置；agent 侧已有提示词禁令+permission deny 尽力兜底。★内网魔改版补充（实测）：**父 agent 定义的 deny 会传导给子代工具集**——链上任何我们自己的 agent 若要起子代，其权限必须 allow-only（engineer 已改；designer/coder 不起子代可保留 deny 白名单）。

## 四、question 的处理约定

interactive 模式下闸口①②会发出 question（设计方向确认/编码质量确认）。**必须送到人**——转发、排队、弹审都行，不允许任何 agent 代答（语义判断不自主是红线）。若总控流程无人值守，改传 `交互: non-interactive`，产物留人后审。

## 五、失败与上报

- 环境类失败（数据库连不上/表不存在/权限钳制/安装滞后）→ dws-engineer 停下并报告原因与修复指引，不重试不绕过。
- **输入类问题**（mapping/RS 质量问题：schema 缺失/字段不一致/阻断校验不过）→ 按调用传入的 `上报格式` 参数包装上报（调用方解析驱动其下一步）；未传则按默认四要素（问题类型/位置/原因/建议）。格式更新改调用方自己的提示词即可，与本仓解耦。
- 执行回路（SQL 修复/设计回改）在 dws-engineer 内部闭环（恢复子 agent 旧会话，每规则限 3 轮），不需要总控参与。
- 完成时交付物在 `10_project_deliver/{appid}/{schema}/{资产}/ddlc_design_dev/`（资产名/schema/appid 由输入推导）：新建=根平铺（ts.json/ts.md、etl/、dq/、ddl/、export/、ut_report.md）；优化=`opt/` 子目录（ALTER 变更单、新 SQL、export/patched 副本、ut_report_opt.md）+ `archive/` 资产档案（入 git）。推生产由人执行，不归调用链。

## 六、本地等价入口（自测对齐用）

人手工：`/new-pipe`、`/opt-pipe`——薄壳正文=固化模式行 + `$ARGUMENTS`，subtask 传给 dws-engineer 的任务 prompt 与本契约的键值块同构（本地单行分号、总控多行，engineer 两种皆解析）。
环境探针：`python skills/new-pipe/scripts/check_env.py`（安装指纹/关键文件/python 版本/运行时依赖逐包对账——缺包或版本不满足即 exit 1，报错带精确 pip 修复命令）。
