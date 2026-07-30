#!/usr/bin/env python3
"""设计开发 Agent 安装器 — 把 agent + skill + command 安装到 opencode 全局目录。

用法：
    python install.py              # 全局安装（~/.config/opencode/）
    python install.py --local      # 项目级安装（.opencode/）
    python install.py --check      # 只检查不安装
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def find_python() -> str:
    """找到 Python 3.10+ 解释器"""
    candidates = ["python3", "python"] if os.name != "nt" else ["py -3", "python", "python3"]
    for cmd in candidates:
        parts = cmd.split()
        try:
            r = subprocess.run(
                parts + ["-c", "import sys; exit(0 if sys.version_info >= (3,10) else 1)"],
                capture_output=True,
            )
            if r.returncode == 0:
                return cmd
        except FileNotFoundError:
            continue
    return ""


def scan_skills(base: Path) -> list[str]:
    """扫描所有含 SKILL.md 的目录"""
    skills = []
    for d in sorted(base.iterdir()):
        if d.is_dir() and (d / "SKILL.md").exists():
            skills.append(d.name)
    return skills


def scan_agents(base: Path) -> list[str]:
    """扫描所有 .md agent 定义文件"""
    agents_dir = base / ".opencode" / "agents"
    if not agents_dir.exists():
        return []
    return [f.name for f in sorted(agents_dir.glob("*.md"))]


def collect_requirements(base: Path) -> list[str]:
    """汇总所有 skill 的 requirements.txt"""
    reqs = set()
    req_file = base / "requirements.txt"
    if req_file.exists():
        for line in req_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                reqs.add(line)
    return sorted(reqs)


def copy_dir(src: Path, dst: Path):
    """复制目录，排除缓存"""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        "__pycache__", ".venv", ".git", ".DS_Store", "*.pyc", ".pytest_cache"
    ))


def main():
    mode = "global"
    check_only = False
    for arg in sys.argv[1:]:
        if arg in ("-l", "--local"):
            mode = "local"
        elif arg in ("-c", "--check"):
            check_only = True
        elif arg in ("-h", "--help"):
            print(__doc__)
            return

    print("=" * 55)
    print("  设计开发 Agent 安装器")
    print("=" * 55)
    print()

    # ── 1. 扫描组件 ──
    print("[1/5] 扫描组件...")
    skills = scan_skills(SCRIPT_DIR / "skills")
    agents = scan_agents(SCRIPT_DIR)
    commands = []
    cmd_dir = SCRIPT_DIR / "commands"
    if cmd_dir.exists():
        commands = [f.name for f in sorted(cmd_dir.glob("*.md"))]

    print(f"  Skills:  {', '.join(skills) if skills else '(无)'}")
    print(f"  Agents:  {', '.join(agents) if agents else '(无)'}")
    print(f"  Commands:{', '.join(commands) if commands else '(无)'}")

    if not skills and not agents:
        print("  未找到任何可安装组件")
        sys.exit(1)
    print()

    if check_only:
        print("检查模式，不执行安装。")
        return

    # ── 2. 目标目录 ──
    if mode == "global":
        config_dir = Path.home() / ".config" / "opencode"
    else:
        config_dir = Path.cwd() / ".opencode"

    dest_label = f"全局 ({config_dir})" if mode == "global" else f"项目级 ({config_dir})"
    print(f"[2/5] 安装目标: {dest_label}")
    config_dir.mkdir(parents=True, exist_ok=True)
    print()

    # ── 3. Python + 依赖 ──
    print("[3/5] 检测 Python + 依赖...")
    python_cmd = find_python()
    if not python_cmd:
        print("  ⚠ 未找到 Python 3.10+，跳过依赖安装")
        print("  请手动安装 Python 后再运行 requirements.txt")
    else:
        py_parts = python_cmd.split()
        ver = subprocess.run(py_parts + ["--version"], capture_output=True, text=True)
        print(f"  {python_cmd} ({ver.stdout.strip()})")

        # venv
        venv_dir = config_dir / "venv"
        if not venv_dir.exists():
            print(f"  创建虚拟环境: {venv_dir}")
            subprocess.run(py_parts + ["-m", "venv", str(venv_dir)], check=True)

        if os.name == "nt":
            venv_py = venv_dir / "Scripts" / "python.exe"
        else:
            venv_py = venv_dir / "bin" / "python"

        reqs = collect_requirements(SCRIPT_DIR)
        if reqs:
            print(f"  安装依赖: {', '.join(reqs)}")
            subprocess.run([str(venv_py), "-m", "pip", "install", "--upgrade", "pip", "--quiet"],
                           capture_output=True)
            r = subprocess.run([str(venv_py), "-m", "pip", "install"] + reqs + ["--quiet"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(f"  ⚠ 依赖安装有警告: {r.stderr[:200]}")
            else:
                print(f"  ✓ 依赖安装完成")
        else:
            print("  无额外依赖")
    print()

    # ── 4. 安装 skill ──
    print("[4/5] 安装 skill...")
    skills_dir = config_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    for s in skills:
        src = SCRIPT_DIR / "skills" / s
        dst = skills_dir / s
        copy_dir(src, dst)
        print(f"  ✓ {s}")
    print()

    # ── 5. 安装 agents + commands ──
    print("[5/5] 安装 agents + commands...")
    agents_dir = config_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for a in agents:
        src = SCRIPT_DIR / ".opencode" / "agents" / a
        dst = agents_dir / a
        shutil.copy2(src, dst)
        print(f"  ✓ agent: {a}")

    commands_dir = config_dir / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    for c in commands:
        src = cmd_dir / c
        dst = commands_dir / c
        shutil.copy2(src, dst)
        print(f"  ✓ command: {c}")
    print()

    # ── 完成 ──
    print("=" * 55)
    print("  安装完成！")
    print("=" * 55)
    print()
    print(f"  安装位置: {config_dir}")
    print(f"  Skills:   {len(skills)} 个")
    print(f"  Agents:   {len(agents)} 个")
    print(f"  Commands: {len(commands)} 个")
    print()
    print("测试方法：")
    print("  1. 打开 opencode / codeagent")
    print("  2. 输入测试 prompt（见下方或 README）")
    print()


if __name__ == "__main__":
    main()
