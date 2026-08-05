#!/usr/bin/env python3
"""评测 v2 交互式菜单入口（傻瓜式，无需记参数）。

直接运行即可：
    python eval-suite/v2/menu.py        # mac/linux
    双击 eval.bat / eval.sh             # 一键启动

菜单引导选择：做什么 → 哪些用例 → 用例来源，自动组装参数调 run.py/seed.py。
所有路径基于项目根的相对路径，不在固定目录也能跑。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# 项目根（menu.py 在 eval-suite/v2/，往上两级）
ROOT = Path(__file__).resolve().parents[2]
V2_DIR = Path(__file__).resolve().parent
EVAL_SUITE = ROOT / "eval-suite"

SEP = "═" * 56


# ============================================================
# 交互辅助
# ============================================================


def _print_menu(title: str, options: list[tuple[str, str]]) -> None:
    """打印菜单。options = [(编号显示, 描述)]。"""
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)
    for i, (label, desc) in enumerate(options, 1):
        print(f"  [{i}] {label}")
        if desc:
            print(f"      {desc}")
    print()


def _ask_choice(prompt: str, max_n: int) -> int:
    """让用户选 1~max_n，返回选中的数字。输入错误重新问。"""
    while True:
        raw = input(f"{prompt} (1-{max_n}, q退出): ").strip()
        if raw.lower() == "q":
            print("已退出。")
            sys.exit(0)
        if raw.isdigit() and 1 <= int(raw) <= max_n:
            return int(raw)
        print(f"  ⚠️ 输入无效，请选 1-{max_n}")


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    """是/否选择。"""
    hint = "[Y/n]" if default else "[y/N]"
    raw = input(f"{prompt} {hint}: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "是")


# ============================================================
# 用例扫描
# ============================================================


def _list_cases(cases_dir: Path) -> list[Path]:
    """扫描用例目录，返回含 mapping.xlsx 的子目录列表。"""
    if not cases_dir.exists():
        return []
    return sorted(
        [d for d in cases_dir.iterdir() if d.is_dir() and (d / "mapping.xlsx").exists()]
    )


def _pick_case(cases: list[Path]) -> Path | None:
    """让用户选单个用例。"""
    if not cases:
        print(f"  ⚠️ 该目录无用例（需要 mapping.xlsx）")
        return None
    options = [(d.name, "") for d in cases]
    _print_menu("选择用例", options)
    idx = _ask_choice("选哪个", len(cases))
    return cases[idx - 1]


def _pick_cases_dir() -> Path:
    """选择用例来源：假设案例 / 真实案例。"""
    real_dir = EVAL_SUITE / "cases_real"
    has_real = bool(_list_cases(real_dir))
    options = [
        ("假设案例 (eval-suite/cases/)", "验证能力用的虚构数据，001-012"),
    ]
    if has_real:
        options.append(("真实案例 (eval-suite/cases_real/)", "内网本地放的真实业务数据"))
    _print_menu("用例来源", options)
    idx = _ask_choice("选哪个", len(options))
    if idx == 1:
        return EVAL_SUITE / "cases"
    return real_dir


# ============================================================
# 主流程
# ============================================================


def _run(args: list[str]) -> int:
    """调 run.py / seed.py，带参数。返回退出码。"""
    print(f"\n→ 执行: {' '.join(args)}\n")
    return subprocess.call([sys.executable, str(V2_DIR / args[0])] + args[1:], cwd=str(ROOT))


def main() -> int:
    os.chdir(str(ROOT))  # 切到项目根，保证相对路径生效

    while True:
        _print_menu("设计开发 Agent 评测系统", [
            ("跑评测", "跑流水线(designer+coder) + 评测打分 + 对比上轮"),
            ("只评测已有产出", "不重跑流水线，对 10_project_deliver 里的产出打分"),
            ("生成断言草稿 (seed)", "从已跑通的产出抽取事实，生成 checks.yaml 草稿"),
            ("退出", ""),
        ])
        action = _ask_choice("做什么", 4)
        if action == 4:
            print("再见 👋")
            return 0

        # 选用例来源
        cases_dir = _pick_cases_dir()
        cases = _list_cases(cases_dir)
        if not cases:
            print(f"\n  ⚠️ {cases_dir} 下无用例。")
            input("  按回车继续...")
            continue

        # 选哪些用例
        _print_menu("评测范围", [
            ("全部用例", f"共 {len(cases)} 个"),
            ("单个用例", "手动选一个"),
        ])
        scope = _ask_choice("选哪个", 2)

        # 组装参数
        cases_dir_arg = f"--cases-dir={cases_dir.relative_to(ROOT)}"

        if action == 3:
            # seed
            if scope == 1:
                print("\n  ℹ️ seed 一次只处理一个用例，请选单个。")
            case = _pick_case(cases)
            if case:
                _run(["seed.py", "--case", case.name, cases_dir_arg, "--review"])
        else:
            # 跑评测 / 只评测
            eval_only = action == 2
            extra = ["--eval-only"] if eval_only else []

            if scope == 1:
                _run(["run.py", "--all", cases_dir_arg] + extra)
            else:
                case = _pick_case(cases)
                if case:
                    # 跑全流程时问要不要跳过 AI
                    if not eval_only:
                        skip = _ask_yes_no("跳过 AI 阶段？", default=False)
                        if skip:
                            extra.append("--skip-ai")
                    _run(["run.py", "--case", case.name, cases_dir_arg] + extra)

        # 跑完问要不要继续
        print(f"\n{SEP}")
        if _ask_yes_no("\n还要做别的吗？", default=True):
            continue
        print("再见 👋")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n已中断。再见 👋")
        sys.exit(130)
