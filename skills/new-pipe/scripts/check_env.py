#!/usr/bin/env python3
"""check_env——dws-engineer 步骤 0 的环境探针（安装指纹 / 关键文件存在性）。

抓的故障类（都在流程第一秒暴露，不等到 designer 写盘时半路爆）：
  1. 安装滞后：装的仓版本旧/缺文件（_install_meta.json 对账 + 关键文件存在性）
  2. Python 解释器不满足（<3.10，管线脚本用了新语法）

用法:
  python3 check_env.py            # 安装环境（~/.config/opencode/skills/... 布局）
  python3 check_env.py --skill-root /path/to/repo/skills   # 本地仓布局（.git 对账当前 commit）

退出码: 0=通过, 1=不符（报错带原因与修复指引）
"""

import sys
import json
import subprocess
import argparse
from pathlib import Path
from datetime import datetime, timedelta

HERE = Path(__file__).resolve().parent


def _find_config_dir(skill_base: Path) -> Path:
    """安装布局: ~/.config/opencode/skills/new-pipe → config = skills 上两级。"""
    return skill_base.parent.parent


def _find_repo_root(skill_base: Path) -> Path | None:
    """本地仓布局：向上找 .git（skills 目录在仓内）。"""
    for p in [skill_base.parent, *skill_base.parents]:
        if (p / ".git").exists():
            return p
    return None


def _git_commit(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return "unknown"


def check(skill_root_arg: str = "") -> list[str]:
    problems = []

    # 1. Python 版本（管线脚本按 3.10+ 写）
    if sys.version_info < (3, 10):
        problems.append(f"Python {sys.version_info.major}.{sys.version_info.minor} < 3.10（管线脚本需要 3.10+）")

    # 2. 布局定位：--skill-root（本地仓）或安装布局（脚本自身路径推算）
    skill_base = (Path(skill_root_arg).resolve() / "new-pipe") if skill_root_arg else HERE.parent
    skills_root = skill_base.parent

    # 3. 关键文件存在性（skills 侧）
    must_exist = [
        skill_base / "SKILL.md",
        skills_root / "design-dev-shared" / "scripts" / "preprocess.py",
        skills_root / "dws-design" / "scripts" / "assemble_ts.py",
        skills_root / "dws-coding" / "scripts" / "slice_ts.py",
    ]
    for f in must_exist:
        if not f.exists():
            problems.append(f"缺文件: {f}（安装不完整——重跑 install.py）")

    # 4. agents 定义存在（安装布局：config/agents；本地仓：agents/）
    agent_candidates = [_find_config_dir(skill_base) / "agents" / "dws-engineer.md"]
    repo = _find_repo_root(skill_base)
    if repo:
        agent_candidates.append(repo / "agents" / "dws-engineer.md")
    if not any(p.exists() for p in agent_candidates):
        problems.append("缺 agents/dws-engineer.md（编排 agent 未安装——重跑 install.py）")

    # 5. 安装指纹（安装环境由 install.py 写 _install_meta.json；本地仓直接对账 git）
    meta_path = _find_config_dir(skill_base) / "_install_meta.json"
    if repo:
        commit = _git_commit(repo)
        print(f"[仓布局] 当前 commit: {commit}")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("commit") and meta["commit"] != commit and meta.get("install_scope") == "repo":
                problems.append(
                    f"安装指纹过时：安装于 {meta.get('installed_at','?')}（{meta.get('commit')}），"
                    f"当前仓 {commit}——重跑 install.py")
    elif meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        print(f"[安装指纹] commit={meta.get('commit','?')} 安装于 {meta.get('installed_at','?')}")
        try:
            ts = datetime.fromisoformat(meta.get("installed_at", ""))
            if datetime.now() - ts > timedelta(days=30):
                print("[提示] 安装超过 30 天，建议核对仓版本后重跑 install.py")
        except ValueError:
            pass
    else:
        problems.append("缺 _install_meta.json（非 install.py 安装或安装损坏——重跑 install.py）")

    return problems


def main():
    ap = argparse.ArgumentParser(description="dws-engineer 环境探针（安装指纹/关键文件存在性）")
    ap.add_argument("--skill-root", default="", help="skills 根目录（本地仓调试用；默认按安装布局从脚本路径推算）")
    args = ap.parse_args()

    problems = check(args.skill_root)
    if problems:
        print("[环境不符] dws-engineer 步骤 0 探针未通过:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)
    print("[环境OK] 安装指纹/关键文件/python 版本均符合，继续执行剧本")


if __name__ == "__main__":
    main()
