#!/usr/bin/env python3
"""sync_to_team — 一键同步本仓「使用侧」内容到内部仓的 .opencode/

源 = 本仓本地 <SRC_BRANCH> 分支当前内容（用户自己 git pull，工具不 fetch 远端）。
内部仓只管 .opencode/：其下脏了拦；其余目录不重要，本地改动自动还原
（以内部远端为准）。结构对齐 install.py：

  skills/    → .opencode/skills/     逐 skill 目录镜像（含 design-dev-shared）
  agents/    → .opencode/agents/     *.md 覆盖（不删别人的）
  commands/  → .opencode/commands/   *.md 覆盖（不删别人的）
  四个 config → .opencode/_references/rules/<dws-design-dev>/
              缺失时从 example 初始化，已有不覆盖（真实配置归内网侧维护）

.opencode/ 是共享目录（别人也有 skill/agent），绝不整目录镜像 / 全量 add。
多人协作：push 前 pull --rebase；rebase 冲突（有人动了我们的文件）立即退出，
现场留给人，不自动猜。

入口：sync_to_team.sh（开发环境测试）/ sync_to_team.bat（内网 Windows 实际运行），
两者都是透传参数的薄壳。

用法：
  sync_to_team.sh                                # 同步（用已存配置）
  sync_to_team.sh /path/to/internal/repo         # 指定内部仓路径，本次生效
  sync_to_team.sh --config /path/to/repo         # 保存配置（含其他已生效选项）后退出
  sync_to_team.sh --src-branch 8.12 --team-branch 8.12   # 分支覆盖，本次生效
  sync_to_team.sh --accept-foreign               # 放行别人对我们路径的改动（见下）

防覆盖（内部仓是多人分支，别人的内容绝不能被静默覆盖）：
  1. 他人改动检测：上次 sync 提交之后若有别人的提交动过我们管理的路径，
     拦截并列出明细；人工确认后加 --accept-foreign 才覆盖（不持久化）。
  2. 镜像删除只针对 git 已跟踪文件——别人放的未跟踪文件绝不碰。
  3. agents/commands 只覆盖 *.md 不删多余；config 缺失才初始化、已有不覆盖。
  4. push 前 pull --rebase，冲突时列出冲突文件退出，现场留给人。

配置 ~/.design-dev-agent-sync.conf（优先级：CLI 参数 > 配置文件 > 默认值）：
  TEAM_REPO=/path/to/internal/repo   # 内部仓本地克隆路径（必填）
  SRC_BRANCH=main                    # 源仓分支（读本地该分支当前内容）
  TEAM_BRANCH=                       # 内部仓分支校验，空=用当前 checkout 分支
"""

import argparse
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
    parser.add_argument("--accept-foreign", action="store_true",
                        help="放行：确认别人对我们路径的改动可被覆盖（不持久化，每次显式传）")
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
        return do_sync(src_repo, Path(tmp), team_repo, src_branch, team_branch,
                       accept_foreign=args.accept_foreign)


def managed_paths(skills: list, agents: list, commands: list, rules_dir: str) -> list:
    """我们产出条目的精确清单——唯一受严格保护的路径（脏了拦/参与基线检测和提交）。"""
    return (
        [f".opencode/skills/{s}" for s in skills]
        + [f".opencode/agents/{a}" for a in agents]
        + [f".opencode/commands/{c}" for c in commands]
        + [f".opencode/_references/rules/{rules_dir}"]
    )


def outside_managed(files: list, managed: list) -> bool:
    """改动文件是否全部在我们条目之外（可丢弃，以远端为准——含 .opencode 内别人的内容）。"""
    return bool(files) and all(
        not any(f == m or f.startswith(m + "/") for m in managed) for f in files
    )


def changed_files(team_repo: Path, rev: str) -> list:
    r = run_git(["show", "--name-only", "--format=", rev], cwd=team_repo, capture=True)
    return [l.strip().strip('"') for l in r.stdout.splitlines() if l.strip()]


def rebase_or_report(team_repo: Path, where: str, managed: list) -> bool:
    """pull --rebase；我们条目之外的提交（含 .opencode 内别人的内容）自动跳过
    （以远端为准），其余冲突列出冲突文件并 fail（现场留给人）。"""
    if run_git(["pull", "--rebase"], cwd=team_repo).returncode == 0:
        return True
    while True:
        r = run_git(["rev-parse", "--git-path", "rebase-merge"], cwd=team_repo, capture=True)
        if r.returncode != 0 or not r.stdout.strip() or not (team_repo / r.stdout.strip()).exists():
            break  # 不在 rebase 进行中状态（如 fetch 失败）
        if outside_managed(changed_files(team_repo, "REBASE_HEAD"), managed):
            subj = run_git(["log", "-1", "--format=%s", "REBASE_HEAD"],
                           cwd=team_repo, capture=True).stdout.strip()
            print(f"  跳过与远端冲突的无关提交（我们条目之外，以远端为准）: {subj}")
            rc = run_git(["rebase", "--skip"], cwd=team_repo).returncode
            if rc == 0:
                return True
            continue  # skip 后停在下一个冲突，继续判
        break
    r = run_git(["diff", "--name-only", "--diff-filter=U"], cwd=team_repo, capture=True)
    files = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    detail = "\n".join(f"    {f}" for f in files) or "    （未取到冲突文件清单）"
    fail(f"{where} rebase 冲突（本地提交与远端提交改动撞车）:\n{detail}\n"
         f"  处理: git rebase --abort 可放弃本次；人工解决后重跑同步")


def do_sync(src_repo: Path, tmp: Path, team_repo: Path, src_branch: str, team_branch: str,
            accept_foreign: bool = False) -> int:
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

    # 我们产出条目的精确清单：唯一受严格保护的路径；
    # 其余一切（含 .opencode 内别人的 skill/agent）都以远端为准。
    managed = managed_paths(skills, agents, commands, rules_dir)
    excludes = [f":(exclude){m}" for m in managed]

    # ── Step 2: 校验内部仓状态（干净 + 分支），rebase 到远端最新 ──
    print("[Step 2] 校验内部仓并拉取远端最新...")
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
    # 工作区检查只针对我们的条目（脏了拦）；其余一切（含 .opencode 内别人的
    # skill/agent）不重要：本地改动直接还原（以远端为准），不卡同步。
    r = run_git(["status", "--porcelain", "-uno"], cwd=team_repo, capture=True)
    managed_dirty = []
    has_outside = False
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        p = line[3:] if len(line) > 3 else ""
        p = p.split(" -> ")[-1].strip('"')
        if any(p == m or p.startswith(m + "/") for m in managed):
            managed_dirty.append(line)
        else:
            has_outside = True
    if has_outside:
        # reset 清 staged（含新增），checkout 还原 worktree；残留的 untracked 不碍 pull
        run_git(["reset", "-q", "HEAD", "--", "."] + excludes, cwd=team_repo)
        if run_git(["checkout", "HEAD", "--", "."] + excludes,
                   cwd=team_repo).returncode != 0:
            fail(f"重置条目外本地改动失败（git checkout HEAD -- . + excludes: {excludes}）")
        print("  已重置我们条目之外的本地改动（含 .opencode 内别人的内容，以远端为准）")
    if managed_dirty:
        detail = "\n".join(f"    {l}" for l in managed_dirty)
        fail(f"内部仓我们条目内有未提交改动（工具不覆盖未知内容）:\n{detail}\n"
             f"  请先处理（git status / git diff 查看，提交或还原）后重跑")
    # 本地领先的提交分级：sync 遗留（可再生）和只动我们条目之外的提交（含
    # .opencode 内别人的内容，以远端为准）都直接丢弃对齐远端。改了我们条目的
    # 手工提交（如 config 维护）保留——全部可丢弃才整体 reset，混合时不动，
    # 交给 rebase（条目外冲突会被自动跳过）。
    r = run_git(["rev-list", "--count", f"origin/{cur_branch}..HEAD"],
                cwd=team_repo, capture=True)
    ahead = int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else 0
    if ahead > 0:
        r = run_git(["log", f"origin/{cur_branch}..HEAD", "--format=%H %s"],
                    cwd=team_repo, capture=True)
        drops, keeps = [], []
        for line in r.stdout.splitlines():
            if not line.strip():
                continue
            sha, subject = line.split(" ", 1)
            if subject.startswith("sync: design-dev-agent@") or outside_managed(
                    changed_files(team_repo, sha), managed):
                drops.append(subject)
            else:
                keeps.append(f"{sha[:8]} {subject}")
        if drops and not keeps:
            print(f"  本地有 {len(drops)} 个领先提交（sync 遗留或条目外改动），对齐远端:")
            for s in drops:
                print(f"    {s}")
            if run_git(["reset", "--hard", f"origin/{cur_branch}"],
                       cwd=team_repo).returncode != 0:
                fail(f"reset 到 origin/{cur_branch} 失败")
        elif drops and keeps:
            print("  [WARN] 本地领先提交混合（含我们条目内的手工改动，不能整体对齐远端）:")
            for s in drops:
                print(f"    可丢弃: {s}")
            for s in keeps:
                print(f"    保留: {s}")
    rebase_or_report(team_repo, "Step 2 拉取远端", managed)

    # 他人改动检测：上次 sync 提交之后，我们产出的条目是否被别人的提交动过。
    # 动过则同步会把他的改动静默覆盖掉（git 无冲突），必须拦下人工确认。
    # 注意 config 目录不参与：那是内网侧的合法维护点，本就只补缺不覆盖。
    guard_paths = [m for m in managed if not m.startswith(".opencode/_references")]
    r = run_git(["log", "-1", "--format=%H", "--grep=^sync:\\ design-dev-agent@"],
                cwd=team_repo, capture=True)
    last_sync = r.stdout.strip()
    if last_sync:
        r = run_git(["log", f"{last_sync}..HEAD", "--oneline", "--"] + guard_paths,
                    cwd=team_repo, capture=True)
        foreign = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        if foreign:
            detail = "\n".join(f"    {f}" for f in foreign)
            if not accept_foreign:
                fail(f"上次同步后有别人的提交改动过我们管理的文件（同步会覆盖这些改动）:\n{detail}\n"
                     f"  确认可覆盖后重跑并加 --accept-foreign；或先人工合并这些改动")
            print("  [WARN] 检测到别人对我们路径的改动，已 --accept-foreign 放行覆盖:")
            for f in foreign:
                print(f"    {f}")
    else:
        print("  （未找到上次同步基线，跳过他人改动检测——首次同步属正常）")
    print()

    # ── Step 3: 逐条目同步到 .opencode/（共享目录：只动自己的条目）──
    print("[Step 3] 同步到内部仓 .opencode/...")
    oc = team_repo / ".opencode"
    rules_path = oc / "_references" / "rules" / rules_dir
    for sub in ("skills", "agents", "commands"):
        (oc / sub).mkdir(parents=True, exist_ok=True)
    rules_path.mkdir(parents=True, exist_ok=True)

    # 已跟踪清单：镜像删除只针对已跟踪文件，别人放的未跟踪文件绝不碰
    r = run_git(["ls-files", "--"] + managed, cwd=team_repo, capture=True)
    tracked = set(r.stdout.splitlines())

    for s in skills:
        mirror_dir(export_dir / "skills" / s, oc / "skills" / s,
                   tracked=tracked, repo_prefix=f".opencode/skills/{s}")
        print(f"  + skill: {s}")
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
    print("  + 同步完成")
    print()

    # ── Step 4: 限定路径单 commit（无变更但本地有遗留未推提交则补推）──
    if run_git(["add", "-A", "--"] + managed, cwd=team_repo).returncode != 0:
        fail("git add 失败")

    r = run_git(["rev-list", "--count", "@{u}..HEAD"], cwd=team_repo, capture=True)
    unpushed = int(r.stdout.strip()) if r.returncode == 0 else 0

    if run_git(["diff", "--cached", "--quiet"], cwd=team_repo).returncode == 0:
        if unpushed == 0:
            print("  无变更，内部仓内容已是最新。")
            return 0
        print(f"  内容无变更，补推遗留的 {unpushed} 个提交...")
    else:
        r = run_git(["diff", "--cached", "--name-status"], cwd=team_repo, capture=True)
        changed = [l for l in r.stdout.splitlines() if l.strip()]
        print(f"[Step 4] 提交（{len(changed)} 个文件变更）...")
        for line in changed[:20]:
            print(f"  {line}")
        if len(changed) > 20:
            print(f"  ...（共 {len(changed)} 个）")
        if run_git(["commit", "-m", f"sync: design-dev-agent@{src_hash} {src_subject}"],
                   cwd=team_repo).returncode != 0:
            fail("commit 失败")
        print()

    # ── Step 5: push（被拒则 rebase 重试一次）──
    print("[Step 5] 推送到内部远端...")
    if run_git(["push"], cwd=team_repo).returncode != 0:
        print("  push 被拒（远端有新提交），rebase 后重试...")
        rebase_or_report(team_repo, "push 重试", managed)
        if run_git(["push"], cwd=team_repo).returncode != 0:
            fail("push 失败，请检查权限/网络")
    print()
    print("=" * 60)
    print(f"  ✅ 同步完成: design-dev-agent@{src_hash} → {cur_branch}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
