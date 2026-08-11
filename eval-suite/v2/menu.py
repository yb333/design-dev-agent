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
from dataclasses import dataclass
from pathlib import Path

# 项目根（menu.py 在 eval-suite/v2/，往上两级）
ROOT = Path(__file__).resolve().parents[2]
V2_DIR = Path(__file__).resolve().parent
EVAL_SUITE = ROOT / "eval-suite"
CASES_DIR = EVAL_SUITE / "cases"
CASES_REAL_DIR = EVAL_SUITE / "cases_real"
DELIVER_BASE = ROOT / "10_project_deliver"

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


@dataclass
class CaseInfo:
    """真实案例的发现结果（合并 cases_real 输入 + 10_project_deliver 产出）。"""

    name: str  # 资产名（= 10_project_deliver 目录名 = cases_real/{分类}/{资产}）
    category: str  # 分类目录名（deliver_only 无输入时默认"未分类"）
    input_dir: Path | None  # cases_real/{分类}/{资产}/，有 mapping.xlsx 才算，否则 None
    has_deliver: bool  # 10_project_deliver/{资产}/ddlc_design_dev/ts.json 存在
    has_checks: bool  # cases_real/{分类}/{资产}/checks.yaml 存在

    @property
    def status_tag(self) -> str:
        """列表展示用的状态标记。"""
        tags = []
        tags.append("✓输入" if self.input_dir else "✗输入")
        tags.append("✓产出" if self.has_deliver else "✗产出")
        if self.has_checks:
            tags.append("✓要点")
        return " ".join(tags)


UNCATEGORIZED = "未分类"  # deliver_only 案例的默认分类（后续可 mv 到合适分类）


def _discover_real_cases() -> list[CaseInfo]:
    """发现真实案例：合并 cases_real/{分类}/{资产}（输入）+ 10_project_deliver/{资产}（产出）。

    cases_real 支持分类二级结构；10_project_deliver 保持平铺（产出约定不变）。
    - 目录位置（cases_real/{分类}/{资产}）决定 category，不管里面有没有 mapping.xlsx
      —— 这样用户 seed 后 mv 到分类目录，即使还没补 mapping 也能按新分类识别
    - mapping.xlsx 是否存在决定 ✓输入 标记；checks.yaml 决定 ✓要点 标记
    - deliver_only 案例（只在 10_project_deliver 有产出）category 默认"未分类"
    """
    # 扫 cases_real/{分类}/{资产}/ 所有目录（目录位置决定 category）
    placed_cases: dict[str, tuple[str, Path]] = {}  # name -> (category, dir)
    if CASES_REAL_DIR.exists():
        for cat_dir in CASES_REAL_DIR.iterdir():
            if not cat_dir.is_dir():
                continue
            for asset_dir in cat_dir.iterdir():
                if asset_dir.is_dir():
                    placed_cases[asset_dir.name] = (cat_dir.name, asset_dir)

    # 产出目录：10_project_deliver/{资产}/（平铺）
    deliver_cases: set[str] = set()
    if DELIVER_BASE.exists():
        for d in DELIVER_BASE.iterdir():
            if d.is_dir() and (d / "ddlc_design_dev" / "ts.json").exists():
                deliver_cases.add(d.name)

    all_names = sorted(set(placed_cases) | deliver_cases)
    infos = []
    for n in all_names:
        cat, dir_for_cat = placed_cases.get(n, (UNCATEGORIZED, None))
        has_mapping = bool(dir_for_cat and (dir_for_cat / "mapping.xlsx").exists())
        has_checks = bool(dir_for_cat and (dir_for_cat / "checks.yaml").exists())
        infos.append(
            CaseInfo(
                name=n,
                category=cat,
                input_dir=dir_for_cat if has_mapping else None,
                has_deliver=n in deliver_cases,
                has_checks=has_checks,
            )
        )
    return infos


def _ensure_real_case_dir(info: CaseInfo) -> None:
    """确保 cases_real/{分类}/{资产}/ 存在（deliver_only 时建占位目录）。

    没有输入目录时，run.py/seed.py 靠 case_dir 拼 deliver 路径，
    占位目录让 resolve_case 能找到、checks.yaml 有地方放。
    deliver_only 案例落在"未分类"下，后续可 mv 到合适分类。
    """
    target = CASES_REAL_DIR / info.category / info.name
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        rel = target.relative_to(ROOT)
        if info.category == UNCATEGORIZED:
            print(f"  ℹ️ 已建占位: {rel}（未分类，后续可 mv 到合适分类）")
        else:
            print(f"  ℹ️ 已建真实案例目录: {rel}")
        print(f"     后续可补 mapping.xlsx + RS.md 作为输入")


def _pick_real_case(cases: list[CaseInfo]) -> CaseInfo | None:
    """让用户从真实案例列表选一个（带分类 + 状态标记）。"""
    options = [(f"[{c.category}] {c.name}  [{c.status_tag}]", "") for c in cases]
    _print_menu("选择真实案例（[分类] 资产名  ✓输入=有mapping ✓产出=有ts.md ✓要点=有checks）", options)
    idx = _ask_choice("选哪个", len(cases))
    return cases[idx - 1]


def _pick_source() -> bool:
    """选择用例来源：假设案例 / 真实案例。返回 True=真实案例。"""
    _print_menu("用例来源", [
        ("假设案例 (eval-suite/cases/)", "验证能力用的虚构数据，001-012 + T1~T3 陷阱"),
        ("真实案例", "扫 cases_real/ 输入 + 10_project_deliver/ 产出"),
    ])
    return _ask_choice("选哪个", 2) == 2


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
        is_real = _pick_source()

        # 发现案例（两种来源路径不同）
        if is_real:
            real_cases = _discover_real_cases()
            if not real_cases:
                print("\n  ⚠️ 无真实案例（cases_real/ 和 10_project_deliver/ 都没数据）")
                input("  按回车继续...")
                continue
            cases_dir_arg = f"--cases-dir={CASES_REAL_DIR.relative_to(ROOT)}"
            case_count = len(real_cases)
        else:
            case_paths = _list_cases(CASES_DIR)
            if not case_paths:
                print("\n  ⚠️ eval-suite/cases/ 下无用例")
                input("  按回车继续...")
                continue
            cases_dir_arg = f"--cases-dir={CASES_DIR.relative_to(ROOT)}"
            case_count = len(case_paths)

        # 选哪些用例
        _print_menu("评测范围", [
            ("全部用例", f"共 {case_count} 个"),
            ("单个用例", "手动选一个"),
        ])
        scope = _ask_choice("选哪个", 2)

        if action == 3:
            # seed（一次只处理一个）
            if scope == 1:
                print("\n  ℹ️ seed 一次只处理一个用例，请选单个。")
            if is_real:
                info = _pick_real_case(real_cases)
                _ensure_real_case_dir(info)
                _run(["seed.py", "--case", info.name, cases_dir_arg, "--review"])
            else:
                case = _pick_case(case_paths)
                if case:
                    _run(["seed.py", "--case", case.name, cases_dir_arg, "--review"])
        else:
            # 跑评测 / 只评测
            eval_only = action == 2
            extra = ["--eval-only"] if eval_only else []

            if scope == 1:
                # 全部：真实案例先确保占位目录都存在，让 run.py --all 能 resolve
                if is_real:
                    for info in real_cases:
                        _ensure_real_case_dir(info)
                _run(["run.py", "--all", cases_dir_arg] + extra)
            else:
                # 单个
                if is_real:
                    info = _pick_real_case(real_cases)
                    _ensure_real_case_dir(info)
                    if not eval_only:
                        skip = _ask_yes_no("跳过 AI 阶段？", default=False)
                        if skip:
                            extra.append("--skip-ai")
                    _run(["run.py", "--case", info.name, cases_dir_arg] + extra)
                else:
                    case = _pick_case(case_paths)
                    if case:
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
