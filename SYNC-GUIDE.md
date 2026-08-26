# sync_to_team 使用手册

> 把本仓（design-dev-agent）**已推送的最新能力**，一键同步到内部仓的 `.opencode/` 目录，产生一个提交并推送。
> 运行环境：内网 Windows 电脑（`sync_to_team.bat`）。核心逻辑在 `sync_to_team.py`。

---

## 一、同步什么

| 本仓（源，origin/main） | 内部仓（目标，8.12 分支） | 方式 |
|---|---|---|
| `skills/` 下 5 个 skill | `.opencode/skills/<同名目录>/` | 逐目录镜像（含删除） |
| `agents/*.md` | `.opencode/agents/` | 同名覆盖，**不删**别人的 |
| `commands/*.md` | `.opencode/commands/` | 同名覆盖，**不删**别人的 |
| 4 个 config 的 example | `.opencode/_references/rules/dws-design-dev/` | **缺失才初始化，已有永不覆盖** |

不同步：docs / tests / eval-suite 等开发侧内容；本仓未 commit 或未 push 的改动。

**别人的内容绝不会被覆盖**，靠四道防线：

1. 只动上面表里我们自己的条目，`git add` 只加我们管理的路径——别人的 skill / agent / 根目录文件全程不碰
2. 同步前检查：上次同步之后若有**别人的提交**改过我们管理的文件，拦截并列出明细，人工确认后才继续（`--accept-foreign`）
3. 镜像删除只删 git 已跟踪的文件——别人放的未跟踪文件（私货）不碰
4. config 是内网侧维护的真实配置，同步只在缺失时从 example 初始化

---

## 二、前置条件（一次性）

内网电脑上：

- [ ] 本仓的本地克隆（从 GitHub main clone / pull 下来的那个文件夹）
- [ ] 内部仓的本地克隆，checkout 在 **8.12** 分支
- [ ] 装了 git；装了 Python 3.10+（跑过 `install.bat` 就有）

---

## 三、首次使用（配置一次）

打开 cmd，cd 到本仓克隆目录（`sync_to_team.bat` 所在目录）：

```bat
sync_to_team.bat --config D:\path\to\内部仓克隆 --team-branch 8.12
```

配置保存在 `%USERPROFILE%\.design-dev-agent-sync.conf`，以后不用再传路径。
`--team-branch 8.12` 是防呆：内部仓哪天不在 8.12 分支上会直接拦下，防止同步到错误分支。

## 四、日常使用（三步）

1. **（外网）** 本仓 commit 并 push 到 GitHub main
2. **（内网）** 本仓克隆 `git pull` —— **必须做**：工具读的就是本地 main 当前内容，不 pull 同步的是旧内容
3. **（内网）** 双击或在 cmd 里运行 `sync_to_team.bat` —— 完成，无变更时不会有提交

同步提交的 message 形如 `sync: design-dev-agent@f999a1e <本仓提交标题>`，每个都能对回本仓一个提交。

---

## 五、每次运行做什么（屏幕输出顺序）

```
[Step 1] 读源仓本地 main 分支当前内容 → 导出到临时目录（不动本地工作区）
[Step 2] 校验内部仓：分支对不对 → 非 .opencode 的本地改动自动还原（以远端为准）
         → .opencode/ 下脏了拦（列明细）→ pull --rebase 拿远端最新
         → 基线检测：上次同步后有没有别人动过我们的文件
[Step 3] 逐条目同步到 .opencode/（skill 镜像 / md 覆盖 / config 补缺）
[Step 4] git add 限定路径 → 无变更跳过 / 有变更单 commit
[Step 5] push；被拒（别人刚推了）自动 rebase 重试一次
```

pull / push 的原始输出都直接显示在屏幕上，出错时结合 `[ERROR]` 行定位。

---

## 六、出错了怎么办（对照表）

| 屏幕提示 | 原因 | 处理 |
|---|---|---|
| `未指定内部仓路径` | 还没配置过 | 先跑第三节的首条命令 |
| `不是 git 仓库: ...` | 路径不对 | 检查路径是否为内部仓克隆 |
| `fetch 失败，请检查网络或远端配置` | 连不上 GitHub | 检查网络/代理 |
| `内部仓当前分支是 X，配置要求 8.12` | 内部仓不在 8.12 | `git checkout 8.12` 后重跑 |
| `已重置非 .opencode 的本地改动` | 内部仓 `.opencode` 之外有本地改动 | 无需处理：那些目录不重要，工具自动以远端为准 |
| `内部仓 .opencode/ 下有未提交改动` + 文件明细 | 我们的领地里有未提交改动（如 config 填了真实地址没提交） | 看明细：该提交的提交（如 config 真实配置），该还原的 `git checkout -- <文件>`，处理完重跑 |
| `上次同步后有别人的提交改动过我们管理的文件` + 提交明细 | 有同事改了我们的 skill/agent/config，同步会覆盖它 | 看明细：改动该保留就先人工合并；确认可覆盖才加 `--accept-foreign` 重跑 |
| `本地有 N 个未推送的 sync 提交（可再生成），对齐远端避免冲突` | 上次 push 失败遗留的同步提交挡住了 rebase | 无需处理：工具自动丢弃（重同步会生成同样内容）；本地有手工提交则不会动，走正常补推 |
| `rebase 冲突` + 冲突文件清单 | push 时和别人的提交撞了同一文件 | `git rebase --abort` 放弃本次；或人工解决冲突后重跑 |
| `push 失败，请检查权限/网络` | 内部远端权限或网络问题 | 检查内部仓远端凭据 |
| `内容无变更，补推遗留的 N 个提交` | 上次 push 失败留下的提交 | 正常，自动补推，不用管 |

---

## 七、注意事项

- **顺序**：外网 push → 内网本仓 pull → 跑同步。顺序反了同步的是旧内容（不会出错，只是不同步最新）。
- `--accept-foreign` 不持久化：每次命中拦截都要显式传，多看一眼明细再放行。
- **弃用整个 skill / agent / command 条目**（不只是改内容）：工具不会自动删（扫描不到就不碰），需要在内部仓手动 `git rm -r` 一次。
- 内部仓 `.gitignore` 建议加一行 `.opencode/venv/`——内网机器跑过 `install.py` 会生成 venv，忽略后同事 clone 下来 `git status` 才干净（工具本身不会把 venv 提交进去，这只是卫生问题）。
- 双击运行窗口结束会 `pause` 等按键；cmd 里跑也是，方便看结果。

---

## 八、配置文件参考

`%USERPROFILE%\.design-dev-agent-sync.conf`（优先级：命令行参数 > 配置文件 > 默认值）：

```ini
TEAM_REPO=D:\path\to\internal-repo   # 内部仓本地克隆路径（必填）
SRC_BRANCH=main                      # 源仓分支（读本地该分支当前内容，默认 main）
TEAM_BRANCH=8.12                     # 内部仓分支校验（空=不校验）
```

命令行临时覆盖：`sync_to_team.bat --src-branch <分支> --team-branch <分支>`；
保存新配置：`sync_to_team.bat --config <内部仓路径> [--src-branch ..] [--team-branch ..]`。
