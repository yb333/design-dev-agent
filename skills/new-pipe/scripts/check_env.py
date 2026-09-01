#!/usr/bin/env python3
"""check_env——dws-engineer 步骤 0 的环境探针（安装指纹 / 关键文件存在性）。

抓的故障类（都在流程第一秒暴露，不等到 designer 写盘时半路爆）：
  1. 安装滞后：装的仓版本旧/缺文件（_install_meta.json 对账 + 关键文件存在性）
  2. Python 解释器不满足（<3.10，管线脚本用了新语法）
  3. 运行时依赖不满足（本解释器逐包对账 requirements.txt——实证案例：openpyxl
     3.1.2 + 新 pandas 在 pd.ExcelFile() 即抛 ImportError，被 preprocess 包成
     "mapping 无法加载"才暴露）

用法:
  python check_env.py              # 安装环境（Win/Unix 通用）（~/.config/opencode/skills/... 布局）
  python check_env.py --skill-root /path/to/repo/skills   # 本地仓布局（.git 对账当前 commit）

退出码: 0=通过, 1=不符（报错带原因与修复指引）
"""

import sys
import re
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


def _ver_tuple(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"[.-]", v))


def check_requirements(req_text: str) -> list[str]:
    """运行时解释器逐包对账 requirements 文本（本函数就跑在运行时解释器里，零歧义）。

    缺包/版本不满足 → 带精确修复命令的 problem。约束只判 `>=`（requirements
    现状全为此形态）；其他形态不判（宁放过）。
    """
    import importlib.metadata as im
    problems, missing, upgrade = [], [], []
    for raw in req_text.splitlines():
        line = raw.split("#")[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*(.*)$", line)
        if not m:
            continue
        pkg, constraint = m.group(1), m.group(2).strip()
        try:
            installed = im.version(pkg)
        except Exception:
            missing.append(pkg)
            continue
        cm = re.match(r"^>=\s*([\d.]+)$", constraint) if constraint else None
        if cm and _ver_tuple(installed) < _ver_tuple(cm.group(1)):
            upgrade.append(f"{pkg}（已装 {installed}，需 {constraint}）")
    if missing:
        problems.append(f"缺依赖包: {', '.join(missing)}——修复: python -m pip install {' '.join(missing)}")
    if upgrade:
        pkgs = [u.split("（")[0] for u in upgrade]
        problems.append(f"依赖版本不满足: {'; '.join(upgrade)}——修复: python -m pip install --upgrade {' '.join(pkgs)}")
    return problems


def check(skill_root_arg: str = "") -> list[str]:
    problems = []

    # 1. Python 版本（管线脚本按 3.10+ 写）
    if sys.version_info < (3, 10):
        problems.append(f"Python {sys.version_info.major}.{sys.version_info.minor} < 3.10（管线脚本需要 3.10+）")

    # 2. 布局定位：--skill-root（本地仓）或安装布局（脚本自身路径推算）
    skill_base = (Path(skill_root_arg).resolve() / "new-pipe") if skill_root_arg else HERE.parent
    skills_root = skill_base.parent
    # 部署形态：项目仓内（生产——启动目录=项目 git 仓，内容随仓走，无安装动作）
    # vs 全局安装（自测——install.py 到 ~/.config/opencode/，有安装版本漂移）
    repo = _find_repo_root(skill_base)
    fix_hint = "更新项目仓（git pull）" if repo else "重跑 install.py"

    # 3. 关键文件存在性（skills 侧）
    must_exist = [
        skill_base / "SKILL.md",
        skills_root / "design-dev-shared" / "scripts" / "preprocess.py",
        skills_root / "dws-design" / "scripts" / "assemble_ts.py",
        skills_root / "dws-coding" / "scripts" / "slice_ts.py",
    ]
    for f in must_exist:
        if not f.exists():
            problems.append(f"缺文件: {f}（内容不完整——{fix_hint}）")

    # 4. agents 定义存在（项目仓：repo/agents；全局安装：config/agents）
    agent_candidates = [_find_config_dir(skill_base) / "agents" / "dws-engineer.md"]
    if repo:
        agent_candidates.append(repo / "agents" / "dws-engineer.md")
    if not any(p.exists() for p in agent_candidates):
        problems.append(f"缺 agents/dws-engineer.md（编排 agent 缺失——{fix_hint}）")

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

    # 6. 运行时依赖对账（当前解释器逐包查——install 曾对自建 venv 检测，运行时真身无人看）
    req_path = (repo / "requirements.txt") if repo else (_find_config_dir(skill_base) / "requirements.txt")
    if req_path.exists():
        problems.extend(check_requirements(req_path.read_text(encoding="utf-8")))
    else:
        print("[提示] 未找到 requirements.txt（老安装布局）——重跑 install.py 补齐；依赖对账跳过")

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
    print("[环境OK] 安装指纹/关键文件/python 版本/依赖均符合，继续执行剧本")


if __name__ == "__main__":
    main()
