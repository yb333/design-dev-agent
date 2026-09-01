#!/usr/bin/env python3
"""设计开发 Agent 安装器 — 把 agent + skill + command 安装到 opencode 全局目录。

用法：
    python install.py              # 全局安装（~/.config/opencode/）
    python install.py --local      # 项目级安装（.opencode/）
    python install.py --check      # 只检查不安装
"""

import os
import sys
import json
import shutil
import subprocess
import traceback
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent

# config 跟 skill 同根（rules 子目录名从 config_paths 取，避免硬编码漂移）
sys.path.insert(0, str(SCRIPT_DIR / "skills" / "design-dev-shared" / "scripts"))
from config_paths import RULES_DIR_NAME


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
    agents_dir = base / "agents"
    if not agents_dir.exists():
        return []
    return [f.name for f in sorted(agents_dir.glob("*.md"))]


def collect_requirements(base: Path) -> list[str]:
    """汇总 requirements.txt"""
    reqs = set()
    req_file = base / "requirements.txt"
    if req_file.exists():
        for line in req_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                reqs.add(line)
    return sorted(reqs)


def copy_dir(src: Path, dst: Path):
    """复制目录，排除缓存。"""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        "__pycache__", ".venv", ".git", ".DS_Store", "*.pyc", ".pytest_cache"
    ))


def run():
    """主逻辑（不含 try/except，由 main 包裹）"""

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

    print(f"  Skills:   {', '.join(skills) if skills else '(无)'}")
    print(f"  Agents:   {', '.join(agents) if agents else '(无)'}")
    print(f"  Commands: {', '.join(commands) if commands else '(无)'}")

    if not skills and not agents:
        print("  未找到任何可安装组件")
        return 1
    print()

    if check_only:
        print("检查模式，不执行安装。")
        return 0

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
        print("  preprocess.py 需要 openpyxl + pandas，请手动安装：")
        print("  pip install openpyxl pandas")
    else:
        py_parts = python_cmd.split()
        ver = subprocess.run(py_parts + ["--version"], capture_output=True, text=True)
        print(f"  {python_cmd} ({ver.stdout.strip()})")

        # 依赖装进 find_python 找到的解释器（= PATH 上跑运行时的那个）。
        # ★ 曾用自建 venv 装检——venv 装完无任何运行时路径使用（死件），检测对象
        #   错位：环境真身（agent bash 的 python）无人对账。权威闸门=check_env
        #   步骤0（跑在运行时解释器里逐包对账），install 只是便利安装。
        reqs = collect_requirements(SCRIPT_DIR)
        if not reqs:
            print("  无额外依赖")
        else:
            print(f"  检查依赖（对 {python_cmd}）: {', '.join(reqs)}")
            import re as _re
            need = []
            for req in reqs:
                m = _re.match(r"^([A-Za-z0-9_.-]+)(.*)$", req)
                pkg, constraint = (m.group(1), m.group(2).strip()) if m else (req, "")
                r_chk = subprocess.run(
                    [f"{python_cmd}", "-c", f"import importlib.metadata as im; print(im.version('{pkg}'))"],
                    capture_output=True, text=True)
                if r_chk.returncode != 0:
                    print(f"  ✗ {pkg}: 未安装")
                    need.append(pkg)
                    continue
                installed = r_chk.stdout.strip()
                cm = _re.match(r"^>=\s*([\d.]+)$", constraint) if constraint else None
                vt = lambda v: tuple(int(x) if x.isdigit() else x for x in _re.split(r"[.-]", v))
                if cm and vt(installed) < vt(cm.group(1)):
                    print(f"  ⚠ {pkg}: 已装 {installed}，需 {constraint}，升级")
                    need.append(pkg)
                else:
                    print(f"  ✓ {pkg}: {installed}（满足 {constraint or '已装'}）")
            if need:
                print(f"  安装/升级: {', '.join(need)}")
                r_req = subprocess.run(
                    [f"{python_cmd}", "-m", "pip", "install", "--upgrade"] + need,
                    capture_output=True, text=True)
                if r_req.returncode != 0:
                    print(f"  ✗ 依赖安装失败!")
                    print(f"  stderr: {r_req.stderr[:500]}")
                    print(f"  stdout: {r_req.stdout[:300]}")
                    print()
                    print("  请手动运行:")
                    print(f"    {python_cmd} -m pip install --upgrade {' '.join(need)}")
                    return 1
                print("  ✓ 依赖安装完成")
            else:
                print("  ✓ 所有依赖版本满足，跳过安装")
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
    # design-dev-shared 是纯公共设施库（无 SKILL.md，scan_skills 扫不到，必须单独拷）：
    # 共用入口（preprocess/check_db/assemble_ddl/resolve_appid）+ 公共库（dws_db/run_ut/sql_parse 等）。
    # 各 pipe 的专属管线脚本随自己 skill 目录整拷（scan_skills 覆盖，scripts/ 在 skill 目录内），
    # 靠 ../../design-dev-shared 相对路径 bootstrap 推算公共库，不拷 shared 会 import 失败。
    shared_src = SCRIPT_DIR / "skills" / "design-dev-shared"
    if shared_src.exists():
        copy_dir(shared_src, skills_dir / "design-dev-shared")
        print("  ✓ design-dev-shared（公共设施：共用入口+公共库，无 SKILL.md 单独拷）")
    print()

    # ── 5. 安装 agents + commands ──
    print("[5/5] 安装 agents + commands...")
    agents_dir = config_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for a in agents:
        src = SCRIPT_DIR / "agents" / a
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
    # requirements.txt 进安装布局（check_env 步骤0 依赖对账的清单——不拷则探针无处可读）
    req_src = SCRIPT_DIR / "requirements.txt"
    if req_src.exists():
        shutil.copy2(str(req_src), str(config_dir / "requirements.txt"))
        print("  ✓ requirements.txt（依赖对账清单）")
    print()

    # ── 6. 数据库配置初始化 ──（config 跟 skill 同根：global→~/.config/opencode，local→<cwd>/.opencode）
    rules_dir = config_dir / "_references" / "rules" / RULES_DIR_NAME
    rules_dir.mkdir(parents=True, exist_ok=True)
    db_config = rules_dir / "db-sources.json"
    db_example = SCRIPT_DIR / "skills" / "dws-coding" / "assets" / "db-sources.example.json"
    if not db_config.exists() and db_example.exists():
        shutil.copy2(str(db_example), str(db_config))
        print("[6/6] 数据库配置初始化...")
        print(f"  ✓ 已创建 {db_config}")
        print(f"  ⚠️  请编辑此文件，填入真实的数据库连接信息（host/port/user/password）")
        print()
    elif db_config.exists():
        print("[6/6] 数据库配置已存在，跳过（不覆盖）")
        print()
    else:
        print("[6/6] 数据库配置 example 未找到，跳过")
        print()

    # ── 7. 平台配置初始化（exporter 用）──
    pf_config = rules_dir / "platform_config.json"
    pf_example = SCRIPT_DIR / "skills" / "dws-coding" / "assets" / "platform_config.example.json"
    if not pf_config.exists() and pf_example.exists():
        shutil.copy2(str(pf_example), str(pf_config))
        print("[7/8] 平台配置初始化...")
        print(f"  ✓ 已创建 {pf_config}")
        print(f"  ⚠️  请编辑此文件，填入项目/子项目编码（部署到平台时用）")
        print()
    elif pf_config.exists():
        print("[7/8] 平台配置已存在，跳过（不覆盖）")
        print()
    else:
        print("[7/8] 平台配置 example 未找到，跳过")
        print()

    # ── 8. 调度任务路径配置初始化（assemble_ts 用，设计阶段确定 project/task_group）──
    sc_config = rules_dir / "schedule_config.json"
    sc_example = SCRIPT_DIR / "skills" / "dws-design" / "assets" / "schedule_config.example.json"
    if not sc_config.exists() and sc_example.exists():
        shutil.copy2(str(sc_example), str(sc_config))
        print("[8/9] 调度任务路径配置初始化...")
        print(f"  ✓ 已创建 {sc_config}")
        print(f"  ⚠️  请编辑此文件，填入各 schema 的默认 project_name/task_group")
        print()
    elif sc_config.exists():
        print("[8/9] 调度任务路径配置已存在，跳过（不覆盖）")
        print()
    else:
        print("[8/9] 调度任务路径配置 example 未找到，跳过")
        print()

    # ── 9. schema↔appid 映射初始化（deliver 目录层 + export job 参数的标准源）──
    sa_config = rules_dir / "schema_apps.json"
    sa_example = SCRIPT_DIR / "skills" / "dws-design" / "assets" / "schema_apps.example.json"
    if not sa_config.exists() and sa_example.exists():
        shutil.copy2(str(sa_example), str(sa_config))
        print("[9/10] schema↔appid 映射初始化...")
        print(f"  ✓ 已创建 {sa_config}")
        print(f"  ⚠️  请编辑此文件，填入每个 appid 下的 schemas（一个 appid 多个 schema；deliver 目录层 + 平台 appid 都从这读）")
        print()
    elif sa_config.exists():
        print("[9/10] schema↔appid 映射已存在，跳过（不覆盖）")
        print()
    else:
        print("[9/10] schema↔appid example 未找到，跳过")
        print()

    # ── 10. 安装指纹（dws-engineer 步骤 0 探针对账用：装的哪个 commit、何时装）──
    import datetime
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=SCRIPT_DIR,
                                capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = "unknown"
    meta = {
        "commit": commit,
        "installed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "skills": skills,
        "agents": agents,
        "commands": commands,
    }
    (config_dir / "_install_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[10/10] 安装指纹: {config_dir / '_install_meta.json'}（commit={commit}）")
    print()

    # ── 完成 ──
    print("=" * 55)
    print("  ✓ 安装完成！")
    print("=" * 55)
    print()
    print(f"  安装位置: {config_dir}")
    print(f"  Skills:   {len(skills)} 个")
    print(f"  Agents:   {len(agents)} 个")
    print(f"  Commands: {len(commands)} 个")
    print()
    print("测试：在 opencode/codeagent 里输入")
    print("  /new-pipe @mapping文件 @RS文件")
    print()

    return 0


def main():
    """入口：包 try/except，任何崩溃都不闪退"""
    exit_code = 0
    try:
        exit_code = run()
    except Exception:
        print()
        print("=" * 55)
        print("  ✗ 安装出错！")
        print("=" * 55)
        traceback.print_exc()
        exit_code = 1

    # Windows 下始终暂停（不闪退）
    if os.name == "nt":
        input("\n按回车退出...")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
