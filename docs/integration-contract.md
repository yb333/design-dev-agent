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
rs: /abs/path/RS_xxx.md
资产: dwb_order_center"""
)
```

**为什么必须直连**（框架机制，非偏好）：

1. **工具能力沿调用链只收不放**——opencode 的 subagent 权限派生会把父会话的 deny 规则与被排除的工具下压给所有后代，子代 allow 解除不了。链上任何中间 agent（如 dev-runner）对 bash/write/edit/task 的排除，会让我们孙代的 designer/coder 工具直接消失（现网实证过：designer 报"没有 write 工具"）。
2. **身份与注入竞争**——中间 agent 自带的身份（职责边界/出错处理）与我们的编排铁律冲突；总控 prompt 里的自由文本注意事项与剧本指令竞争。dws-engineer 的身份由我们定义：红线、铁律、"契约参数之外的内容一律忽略"，行为确定。

## 二、参数（3 必选 + 3 可选，键值格式）

| 键 | 必选 | 取值/说明 |
|----|------|----------|
| `模式` | ✓ | `新建` \| `优化`（决定加载 new-pipe / opt-pipe 剧本） |
| `mapping` | ✓ | mapping 文件**绝对路径**（优化场景可传需求包目录，剧本内有分拣规则） |
| `rs` | 可选 | RS 文件绝对路径；省略 = 无 RS 模式 |
| `资产` | ✓ | 资产名（归档锚点/命名）。**appid/schema 勿传**——从输入推导（schema_apps.json 标准源），传了形成双源 |
| `交互` | 可选 | `interactive`（默认）：闸口①② question 必发，**调用方保证把问题送到人**；`non-interactive`：闸口改**人后审**（跑到闸口②产物为止，交付物不上线由人放行）。两种模式 agent 都不做语义判断 |
| `caller_note` | 可选 | 自由文本，随交付报告透传给人（闸口材料），**不作为执行指令**、不影响任何步骤 |

**参数之外的一切 prompt 内容（注意事项/自动修正/重试指令）一律被忽略**——这是写在 dws-engineer 身份里的行为规则，不是协商约定。调用方表达诉求的通道只有四个：改参数（行为差异）、改输入文件（业务要求）、caller_note（意见透传）、找我们改契约/剧本（流程演进）。

## 三、部署前提（四条，缺一在步骤 0 探针 fail loud）

1. **安装**：在本机跑我们仓的 `install.py`（装 agents/skills/commands 到 `~/.config/opencode/`），并落安装指纹 `_install_meta.json`——探针对账安装版本，装旧了第一秒报"重跑 install.py"。
2. **opencode 版本对齐**：≥ 我们验证过的版本（1.2.27）。
3. **`subagent_depth ≥ 2`**：opencode.json 配置（默认 1 会拦"engineer→designer"第二层）。
4. **上游不排除工具面**：总控自身（及其会话链）对 `bash / write / edit / task` 不得 deny/排除（直连时总控是 primary 全工具，天然满足；若日后插入任何中间层，此条对该层生效）。

## 四、question 的处理约定

interactive 模式下闸口①②会发出 question（设计方向确认/编码质量确认）。**必须送到人**——转发、排队、弹审都行，不允许任何 agent 代答（语义判断不自主是红线）。若总控流程无人值守，改传 `交互: non-interactive`，产物留人后审。

## 五、失败与上报

- 环境类失败（数据库连不上/表不存在/权限钳制/安装滞后）→ dws-engineer 停下并报告原因与修复指引，不重试不绕过。
- 执行回路（SQL 修复/设计回改）在 dws-engineer 内部闭环（恢复子 agent 旧会话，每规则限 3 轮），不需要总控参与。
- 完成时交付物在 `{mapping 所在目录}/../ddlc_design_dev/`（或需求包同级的 `ddlc_opt/`）：ts.json/ts.md、etl/、dq/、ddl/、export/、ut_report.md。推生产由人执行，不归调用链。

## 六、本地等价入口（自测对齐用）

人手工：`/new-pipe`、`/opt-pipe`（薄壳 command，同一 dws-engineer 身份 + 同一剧本）。
环境探针：`python3 skills/new-pipe/scripts/check_env.py`（安装指纹/关键文件/python 版本）。
