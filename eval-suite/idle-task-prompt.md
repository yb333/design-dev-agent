# 闲时任务提示词

> 用于空闲时段执行。复制下面**提示词**整段给 agent，在项目目录下执行。
>
> 结构分两类：
> - **常规任务**（一~四）：每次闲时都跑，幂等——没发现就如实报"无发现"，**不为产出制造改动**。
> - **当期专项**：一次性任务，做完删除条目。当前无。
>
> 环境约束：不连库、不安装依赖（pytest / preprocess / precheck 可跑；DB / install 全链路不可用——需要时如实报告跳过，不硬造验证）。
> 红线：删除仅限零引用死代码（grep 全仓取证）；文档只对齐事实不改约定语义；语义级发现只报告不动手。

---

## 提示词（复制以下全部内容给 agent）

你在 design-dev-agent 项目（/Users/yuanbo/design-dev-agent）里。先读 `/Users/yuanbo/design-dev-agent/CLAUDE.md`（尤其 glob 禁令：文件查找必须用确定性文件名）和 `/Users/yuanbo/design-dev-agent/AGENTS.md`（当前实际结构 + 分层铁律：shared 绝不 import dws-design/dws-coding）。

按顺序做任务一~四（+ 当期专项如有），每步如实记录，最后收尾。

### 任务一：健康回归（起手门）

1. `python3 -m pytest tests/ -q` 全量通过（含 `tests/test_layering.py` 分层守护）
2. `python3 install.py --check` 组件扫描正常

红了先定位：能确定性修的修掉（带测试）；修不了的如实报告并**停止后续任务**（基线不稳不做巡检）。绿了才继续。

### 任务二：文档-代码一致性审计

对照实际文件修文档漂移（文档对齐事实，**只改活跃文档**：AGENTS.md / commands/new-pipe.md / docs/tool-registry.md / skills/*/SKILL.md / agents/*.md。已知滞后文档 CLAUDE.md / README.md / architecture.md / eval-suite 历史**不动**——项目约定它们不同步）：

1. `docs/tool-registry.md`：每个 scripts/*.py 有行、每行文件存在（skills/design-dev-shared|dws-design|dws-coding 三处对照）；④ imported 表的被 import 关系与代码 import 语句一致
2. `AGENTS.md` 结构树 ↔ 实际 scripts 文件清单；"读 ts[rules/init]"等断言 ↔ 代码实际
3. `commands/new-pipe.md` 的 SHARED/DESIGN/CODING_SCRIPTS 清单 ↔ 实际；脚本调用路径 ↔ 实际
4. SKILL.md / agents/*.md 提到的脚本名与路径 ↔ 实际
5. 文档中的量化断言抽查（如校验条数、缓存时长）↔ 代码常量

### 任务三：零引用死代码扫描

对 `skills/*/scripts/` 每个 .py 模块和其中的公开函数：

1. 模块级：grep 全仓（排除 .git / __pycache__ / 10_project_deliver）找 import 与路径调用。**零引用 → 删**（同步删 tool-registry 行 + AGENTS.md 结构树提及，记入汇报）；引用仅在死代码之间 mutual → 一并删
2. 函数级：跨模块被 import 的函数（tool-registry ④ 表是现成依赖图）重点看；全仓零引用的公开函数**只报告不删**（等人工判断）
3. 顺手清各 scripts/__pycache__ 里无对应源文件的 stale .pyc

### 任务四：测试覆盖缺口巡检

1. 优先：tool-registry ④ 表里跨模块被 import 的函数——grep tests/ 确认有直接测试；缺的补（不连库，dict/mock 构造，参照 tests/conftest.py 工厂）
2. 其次：近 20 个提交新增/改动的公开函数（`git log --oneline -20` 圈范围）缺测试的补
3. 补的测试验证明确行为（正常路径 + 边界 + 错误处理），不为凑数写无意义断言
4. 发现疑似 bug（行为与文档/注释矛盾）：确定性小修直接修 + 测试钉住；语义拿不准的只报告

### 当期专项

（当前无一次性任务。有则加在此处：背景 / 要做 / 验收 / 约束，做完删除条目。）

### 收尾

1. 跑 `python3 -m pytest tests/ -q` 确认全套通过
2. **自动提交**：`git add -A && git commit && git push origin main`（提交信息按 `feat/fix/refactor/docs: 描述` 规范；纯巡检无改动则不提交空commit，说明即可）
3. 如实汇报：每任务的发现 / 改动 / 无发现；删了什么（附零引用证据）；修了什么文档漂移；补了什么测试
