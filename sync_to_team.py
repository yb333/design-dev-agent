#!/usr/bin/env python3
"""sync_to_team — 一键同步本仓「使用侧」内容到内部仓的 .opencode/

源 = 本仓本地 <SRC_BRANCH> 分支当前内容（用户自己 git pull，工具不 fetch 远端）。
内部仓一切本地状态不保留（工作区改动/本地提交/失败遗留一律 reset 对齐远端）；
唯一例外：config 目录的工作区改动快照保护（用户拷来的内网真实值，随同步提交）。
结构对齐 install.py：

  skills/    → .opencode/skills/     逐 skill 目录镜像（含 design-dev-shared）
  agents/    → .opencode/agents/     *.md 覆盖（不删别人的）
  commands/  → .opencode/commands/   *.md 覆盖（不删别人的）
  四个 config → .opencode/_references/rules/<dws-design-dev>/
              缺失时从 example 初始化，已有不覆盖（config 以远端为准；
              要更新 config：拷文件到内网仓该目录下，跑工具即随同步提交）

入口：sync_to_team.sh（开发环境测试）/ sync_to_team.bat（内网 Windows 实际运行），
两者都是透传参数的薄壳。

用法：
  sync_to_team.sh                                # 同步（用已存配置）
  sync_to_team.sh /path/to/internal/repo         # 指定内部仓路径，本次生效
  sync_to_team.sh --config /path/to/repo         # 保存配置（含其他已生效选项）后退出
  sync_to_team.sh --src-branch 8.12 --team-branch 8.12   # 分支覆盖，本次生效

配置 ~/.design-dev-agent-sync.conf（优先级：CLI 参数 > 配置文件 > 默认值）：
  TEAM_REPO=/path/to/internal/repo   # 内部仓本地克隆路径（必填）
  SRC_BRANCH=main                    # 源仓分支（读本地该分支当前内容）
  TEAM_BRANCH=                       # 内部仓分支校验，空=用当前 checkout 分支
"""

import argparse
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

CONFIG_NAME = ".design-dev-agent-sync.conf"
EXCLUDE_DIRS = {"__pycache__"}
EXCLUDE_FILES = {".DS_Store"}
EXCLUDE_SUFFIX = (".pyc",)
CONFIG_MAP = [  # (example 相对路径, 真实名) —— 对齐 install.py 第 6-9 步
    ("skills/dws-coding/assets/db-sources.example.json", "db-sources.json"),
    ("skills/dws-coding/assets/platform_config.example.json", "platform_config.json"),
    ("skills/dws-design/assets/schedule_config.example.json", "schedule_config.json"),
    ("skills/dws-design/assets/schema_apps.example.json", "schema_apps.json"),
]


def fail(msg: str):
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def run_git(args, cwd=None, capture=False):
    kwargs = {"cwd": str(cwd)} if cwd else {}
    if capture:
        kwargs.update(capture_output=True, text=True, encoding="utf-8", errors="replace")
    return subprocess.run(["git"] + args, **kwargs)


def load_config(path: Path) -> dict:
    cfg = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


def save_config(path: Path, cfg: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{k}={v}\n" for k, v in cfg.items()), encoding="utf-8"
    )


def excluded(rel: Path) -> bool:
    return (
        any(part in EXCLUDE_DIRS for part in rel.parts)
        or rel.name in EXCLUDE_FILES
        or rel.suffix in EXCLUDE_SUFFIX
    )


def mirror_dir(src: Path, dst: Path, tracked: set, repo_prefix: str):
    """镜像 src → dst：复制新增/变更，删除 dst 中 src 没有的。

    只删除 git 已跟踪的文件（tracked 含 repo_prefix 前缀的仓库相对路径）——
    别人放在目录里的未跟踪文件绝不碰。
    """
    dst.mkdir(parents=True, exist_ok=True)
    src_files = set()
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if excluded(rel) or not p.is_file():
            continue
        src_files.add(rel)
        target = dst / rel
        if not target.exists() or target.read_bytes() != p.read_bytes():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
    for p in sorted(dst.rglob("*"), reverse=True):
        rel = p.relative_to(dst)
        if excluded(rel):
            continue
        if p.is_file():
            if rel not in src_files and f"{repo_prefix}/{rel.as_posix()}" in tracked:
                p.unlink()
        elif not any(p.iterdir()):
            p.rmdir()


def copy_md(src_dir: Path, dst_dir: Path):
    """*.md 覆盖式拷贝（不镜像——不动目标目录里别人的文件）。"""
    for p in sorted(src_dir.glob("*.md")):
        target = dst_dir / p.name
        if not target.exists() or target.read_bytes() != p.read_bytes():
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.dont_write_bytecode = True  # import config_paths 不落 pyc

    parser = argparse.ArgumentParser(description="同步本仓使用侧内容到内部仓 .opencode/")
    parser.add_argument("team_repo", nargs="?", help="内部仓路径（本次生效）")
    parser.add_argument("--config", metavar="TEAM_REPO", help="保存配置（含其他已生效选项）后退出")
    parser.add_argument("--src-branch", help="源仓分支（默认 main）")
    parser.add_argument("--team-branch", help="内部仓分支校验（空=用当前 checkout 分支）")
    args = parser.parse_args()

    src_repo = Path(__file__).resolve().parent
    config_path = Path.home() / CONFIG_NAME
    cfg = load_config(config_path)

    team_repo = args.team_repo or cfg.get("TEAM_REPO", "")
    src_branch = args.src_branch or cfg.get("SRC_BRANCH", "") or "main"
    team_branch = args.team_branch or cfg.get("TEAM_BRANCH", "")

    if args.config:
        save_config(config_path, {
            "TEAM_REPO": args.config,
            "SRC_BRANCH": src_branch,
            "TEAM_BRANCH": team_branch,
        })
        print(f"[OK] 已保存配置: {args.config}（源分支: {src_branch}，内部仓分支: {team_branch or '不校验'}）")
        return 0

    if not team_repo:
        fail("未指定内部仓路径（用法: sync_to_team.sh --config /path/to/internal/repo）")
    team_repo = Path(team_repo).expanduser().resolve()
    if not (team_repo / ".git").exists():
        fail(f"不是 git 仓库: {team_repo}")

    print("=" * 60)
    print("  同步设计开发能力 → 内部仓 .opencode/")
    print("=" * 60)
    print(f"源:   {src_repo} (origin/{src_branch})")
    print(f"目标: {team_repo}/.opencode/")
    print()

    with tempfile.TemporaryDirectory(prefix="design-dev-sync-") as tmp:
        return do_sync(src_repo, Path(tmp), team_repo, src_branch, team_branch)


def managed_paths(skills: list, agents: list, commands: list, rules_dir: str) -> list:
    """我们产出条目的精确清单——唯一受严格保护的路径（脏了拦/参与基线检测和提交）。"""
    return (
        [f".opencode/skills/{s}" for s in skills]
        + [f".opencode/agents/{a}" for a in agents]
        + [f".opencode/commands/{c}" for c in commands]
        + [f".opencode/_references/rules/{rules_dir}"]
    )


def do_sync(src_repo: Path, tmp: Path, team_repo: Path, src_branch: str, team_branch: str) -> int:
    # ── Step 1: 读源仓本地分支当前内容（用户自己 pull，工具不 fetch 远端）──
    print(f"[Step 1] 读取源仓本地分支 ({src_branch})...")
    r = run_git(["rev-parse", "--short", src_branch], cwd=src_repo, capture=True)
    if r.returncode != 0 or not r.stdout.strip():
        fail(f"源仓本地分支不存在: {src_branch}（请先 git pull）")
    src_hash = r.stdout.strip()
    r = run_git(["log", "-1", "--format=%s", src_branch], cwd=src_repo, capture=True)
    src_subject = r.stdout.strip()
    print(f"  源提交: {src_hash} {src_subject}")

    export_dir = tmp / "src"
    export_dir.mkdir()
    r = subprocess.run(
        ["git", "-C", str(src_repo), "archive", src_branch, "--", "skills", "agents", "commands"],
        capture_output=True,
    )
    if r.returncode != 0:
        fail(f"git archive 失败: {r.stderr.decode('utf-8', errors='replace')[:200]}")
    with tarfile.open(fileobj=BytesIO(r.stdout)) as tf:
        tf.extractall(export_dir)

    # 条目清单动态扫描（对齐 install.py：含 SKILL.md 的目录 + design-dev-shared 特例）
    skills = [
        d.name for d in sorted((export_dir / "skills").iterdir())
        if d.is_dir() and ((d / "SKILL.md").exists() or d.name == "design-dev-shared")
    ]
    agents = sorted(p.name for p in (export_dir / "agents").glob("*.md"))
    commands = sorted(p.name for p in (export_dir / "commands").glob("*.md"))
    print(f"  Skills: {len(skills)} 个  Agents: {len(agents)} 个  Commands: {len(commands)} 个")
    print()

    # config 目录名从 config_paths 取（唯一源；取不到回退默认）
    rules_dir = "dws-design-dev"
    sys.path.insert(0, str(export_dir / "skills" / "design-dev-shared" / "scripts"))
    try:
        from config_paths import RULES_DIR_NAME
        rules_dir = RULES_DIR_NAME
    except Exception:
        pass
    finally:
        sys.path.pop(0)

    # 我们产出条目的精确清单：同步/提交只动这些路径，别人的内容全程不碰。
    managed = managed_paths(skills, agents, commands, rules_dir)

    # ── Step 2: 校验内部仓状态（现场回退 + 分支）──
    print("[Step 2] 校验内部仓...")
    # 上次失败遗留的 rebase/merge 冲突现场：自动放弃回退（此时 symbolic-ref 失败
    # 会被误诊成 detached HEAD，且 checkout 被冲突 index 拒绝形成死锁）。
    # 回退后由领先分级 + rebase 自动跳过接管。
    def git_state_present(name: str) -> bool:
        r = run_git(["rev-parse", "-q", "--verify", name], cwd=team_repo, capture=True)
        if r.returncode == 0 and r.stdout.strip():
            return True
        r = run_git(["rev-parse", "--git-path", name], cwd=team_repo, capture=True)
        return (r.returncode == 0 and bool(r.stdout.strip())
                and (team_repo / r.stdout.strip()).exists())

    for state, abort_cmd in (
        ("rebase-merge", ["rebase", "--abort"]),
        ("rebase-apply", ["rebase", "--abort"]),
        ("MERGE_HEAD", ["merge", "--abort"]),
    ):
        if git_state_present(state):
            print(f"  检测到未完成的 {abort_cmd[0]} 现场（上次冲突遗留），自动放弃回退")
            if run_git(abort_cmd, cwd=team_repo).returncode != 0:
                fail(f"放弃 {abort_cmd[0]} 现场失败，请人工处理: git {' '.join(abort_cmd)}")
    r = run_git(["symbolic-ref", "--short", "HEAD"], cwd=team_repo, capture=True)
    cur_branch = r.stdout.strip()
    if not cur_branch:
        fail("内部仓处于 detached HEAD（HEAD 指在提交上、不在任何分支上；git bash "
             "提示符显示 ((8.12)) 双括号即此状态）\n"
             "  处理: 在内部仓运行 git checkout 8.12 回到分支后重跑")
    if team_branch and cur_branch != team_branch:
        fail(f"内部仓当前分支是 {cur_branch}，配置要求 {team_branch}（请手动 checkout）")
    # config 快照（用户拷来的内网真实值——唯一受保护的本地状态，循环外读一次）
    cfg_rel = next(m for m in managed if m.startswith(".opencode/_references"))
    cfg_dir = team_repo / cfg_rel
    snapshot = {}
    if cfg_dir.exists():
        snapshot = {
            p.relative_to(cfg_dir): p.read_bytes()
            for p in sorted(cfg_dir.rglob("*")) if p.is_file()
        }

    def restore_config():
        restored = 0
        for rel, data in snapshot.items():
            target = cfg_dir / rel
            if not target.exists() or target.read_bytes() != data:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                restored += 1
        if restored:
            print(f"  config 工作区改动已保留恢复 {restored} 个文件（随本次同步提交）")

    oc = team_repo / ".opencode"
    rules_path = oc / "_references" / "rules" / rules_dir
    for sub in ("skills", "agents", "commands"):
        (oc / sub).mkdir(parents=True, exist_ok=True)
    rules_path.mkdir(parents=True, exist_ok=True)

    # 上次同步对应的源提交（从内网仓最后一个 sync 提交解析）→ 本次积攒的
    # 能力更新清单 = 源仓 (上次hash..本次] 里动了 skills/agents/commands 的提交
    # （工具/评测类提交不进同步，自动跳过）。解析失败一律退化为单条标题。
    r = run_git(["log", "-1", "--format=%s", "--grep=^sync:\\ design-dev-agent@"],
                cwd=team_repo, capture=True)
    m = re.search(r"@([0-9a-f]{7,40})", r.stdout)
    entries = []
    if m:
        r = run_git(["log", f"{m.group(1)}..{src_branch}", "--oneline", "--",
                     "skills", "agents", "commands"],
                    cwd=src_repo, capture=True)
        if r.returncode == 0:
            entries = [l.strip() for l in r.stdout.splitlines() if l.strip()]

    # 同步主体可整体重试：push 被拒（远端在窗口期又进了新提交）就整个重来一
    # 轮——重新对齐远端、重新 mirror、重新提交。sync 提交可再生成，重来比在
    # 原地解 rebase 冲突更简单可靠。
    done = False
    for attempt in range(1, 4):
        if attempt > 1:
            print(f"[重试 {attempt}/3] push 被拒，重新对齐远端再来一轮...")
            print("  丢弃本轮生成的 sync 提交（可再生成）")

        # fetch 先行。对齐目标用 FETCH_HEAD 而非 origin/<分支>：某些克隆配置
        # （--single-branch / fetch refspec 被改过）下 fetch <分支> 不更新跟踪
        # 引用，reset 到陈旧引用会把已推内容回退重放（全量差异 + push 永远
        # non-FF 三轮失败）。FETCH_HEAD 永远是刚 fetch 的真实远端状态。
        if run_git(["fetch", "origin", cur_branch], cwd=team_repo).returncode != 0:
            restore_config()
            fail("fetch 内部远端失败，请检查网络")

        # ── 对齐远端：丢一切本地状态（唯一例外：config 已快照）──
        if attempt == 1:
            r = run_git(["status", "--porcelain", "-uno"], cwd=team_repo, capture=True)
            dirty = [l for l in r.stdout.splitlines() if l.strip()]
            r = run_git(["rev-list", "--count", "FETCH_HEAD..HEAD"],
                        cwd=team_repo, capture=True)
            ahead = int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else 0
            if ahead > 0:
                r = run_git(["log", "FETCH_HEAD..HEAD", "--format=%s"],
                            cwd=team_repo, capture=True)
                print(f"  本地有 {ahead} 个领先提交（本地状态不保留），对齐远端:")
                for s in [l.strip() for l in r.stdout.splitlines() if l.strip()]:
                    print(f"    {s}")
            if dirty:
                print(f"  本地有 {len(dirty)} 个工作区改动（本地状态不保留），对齐远端:")
                for l in dirty[:10]:
                    print(f"    {l}")
                if len(dirty) > 10:
                    print(f"    ...（共 {len(dirty)} 个）")

        # 远端新增文件撞本地未跟踪文件的先清掉（以远端为准，不清会挡住 reset）
        r = run_git(["diff", "--name-only", "--diff-filter=A", "HEAD", "FETCH_HEAD"],
                    cwd=team_repo, capture=True)
        added = {l.strip().strip('"') for l in r.stdout.splitlines() if l.strip()}
        if added:
            r = run_git(["ls-files", "--others", "--exclude-standard"],
                        cwd=team_repo, capture=True)
            clash = added & {l.strip().strip('"') for l in r.stdout.splitlines() if l.strip()}
            for f in sorted(clash):
                (team_repo / f).unlink(missing_ok=True)
        if run_git(["reset", "--hard", "FETCH_HEAD"],
                   cwd=team_repo).returncode != 0:
            restore_config()
            fail("reset 到远端最新（FETCH_HEAD）失败")
        restore_config()

        # ── mirror 源头内容到我们的条目 ──
        r = run_git(["ls-files", "--"] + managed, cwd=team_repo, capture=True)
        tracked = set(r.stdout.splitlines())
        for s in skills:
            mirror_dir(export_dir / "skills" / s, oc / "skills" / s,
                       tracked=tracked, repo_prefix=f".opencode/skills/{s}")
        copy_md(export_dir / "agents", oc / "agents")
        copy_md(export_dir / "commands", oc / "commands")
        inited = []
        for ex, real in CONFIG_MAP:
            dst = rules_path / real
            src_ex = export_dir / ex
            if not dst.exists() and src_ex.exists():
                shutil.copy2(src_ex, dst)
                inited.append(real)
        if inited:
            print(f"  config 初始化（已有未动）: {' '.join(inited)}")

        # ── 限定路径单 commit ──
        if run_git(["add", "-A", "--"] + managed, cwd=team_repo).returncode != 0:
            fail("git add 失败")
        if run_git(["diff", "--cached", "--quiet"], cwd=team_repo).returncode == 0:
            print("  无变更，内部仓内容已是最新。")
            done = True
            break
        r = run_git(["diff", "--cached", "--name-status"], cwd=team_repo, capture=True)
        changed = [l for l in r.stdout.splitlines() if l.strip()]
        print(f"  提交（{len(changed)} 个文件变更）...")
        for line in changed[:20]:
            print(f"  {line}")
        if len(changed) > 20:
            print(f"  ...（共 {len(changed)} 个）")
        # 提交信息：积攒多条 → 首行汇总 + 正文逐条；单条 → 直接用该条标题；
        # 区间无能力提交（纯 config 变化）→ config 更新；否则退化为源仓最新标题
        if len(entries) >= 2:
            commit_args = ["-m", f"sync: design-dev-agent@{src_hash} 能力更新 {len(entries)} 项",
                           "-m", "\n".join(f"* {e}" for e in entries)]
            print(f"  信息: 能力更新 {len(entries)} 项（正文含逐条清单）")
        elif len(entries) == 1:
            subject = entries[0].split(" ", 1)[-1]
            commit_args = ["-m", f"sync: design-dev-agent@{src_hash} {subject}"]
        elif all(l.split(maxsplit=2)[-1].startswith(".opencode/_references")
                 for l in changed):
            commit_args = ["-m", f"sync: design-dev-agent@{src_hash} config 更新"]
        else:
            commit_args = ["-m", f"sync: design-dev-agent@{src_hash} {src_subject}"]
        if run_git(["commit"] + commit_args, cwd=team_repo).returncode != 0:
            fail("commit 失败")

        # ── push（显式 refspec 不依赖 upstream；只有竞争性被拒才重试）──
        print("  推送到内部远端...")
        r = run_git(["push", "origin", f"HEAD:{cur_branch}"],
                    cwd=team_repo, capture=True)
        if r.returncode == 0:
            done = True
        else:
            err = ((r.stderr or "") + (r.stdout or "")).strip()
            competitive = any(k in err for k in ("fetch first", "non-fast-forward", "stale info"))
            if not competitive:
                # 确定性失败（权限/分支保护/hook 拒绝等）——重试无意义，带原始错误停
                print(err)
                fail("push 失败（非竞争原因）——见上方 git 原始输出；"
                     "常见：8.12 是受保护分支（找管理员开直推权限）、push 凭据/权限问题")
            print(err.splitlines()[-1] if err else "  push 被拒")
    if not done:
        fail("push 连续 3 轮竞争被拒（远端推进太快）——稍后直接重跑即可自愈；"
             "持续失败请在内部仓手动 git push 看真实报错")

    print()
    print("=" * 60)
    print(f"  ✅ 同步完成: design-dev-agent@{src_hash} → {cur_branch}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
