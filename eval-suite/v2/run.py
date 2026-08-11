#!/usr/bin/env python3
"""评测 v2 CLI 入口。

用法:
    python eval-suite/v2/run.py --case 002            # 全流程（跑流水线 + 评测）
    python eval-suite/v2/run.py --case 002 --eval-only # 只评测（已有产出）
    python eval-suite/v2/run.py --all                   # 跑全部用例
    python eval-suite/v2/run.py --case 002 --skip-ai    # 跳过 AI（只跑脚本链路）

输出: 分层报告到 stdout。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 让 `from v2.xxx import` 和 `from checks_schema import` 都能工作
ROOT = Path(__file__).resolve().parents[2]
EVAL_SUITE = Path(__file__).resolve().parents[1]
V2_DIR = Path(__file__).resolve().parent
for p in (str(EVAL_SUITE), str(V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# v2 包内 import（用相对 import 需以包形式跑，这里兼容直接跑）
from checks_schema import load_checks  # noqa: E402
from engine import run_evaluation  # noqa: E402
from pipeline import run_pipeline  # noqa: E402
from report_v2 import render_report  # noqa: E402
import baseline  # noqa: E402


CASES_DIR_DEFAULT = EVAL_SUITE / "cases"
DELIVER_BASE = ROOT / "10_project_deliver"


def resolve_case(case_arg: str, cases_dir: Path) -> Path:
    """把 --case 解析成案例目录。

    支持三种结构：
    - 一级精确 cases_dir/{case_arg}（假设案例 cases/{资产}）
    - 数字前缀（002 → 002_dwb_xxx）
    - 二级分类 cases_dir/{分类}/{case_arg}（真实案例 cases_real）
    """
    if not cases_dir.exists():
        return Path()
    # 1. 一级精确匹配
    exact = cases_dir / case_arg
    if exact.exists():
        return exact
    # 2. 数字前缀匹配（002 → 002_dwb_xxx）
    if re.match(r"^\d+$", case_arg):
        for d in sorted(cases_dir.iterdir()):
            if d.is_dir() and d.name.startswith(f"{case_arg}_"):
                return d
    # 3. 二级分类匹配（cases_real/{分类}/{case_arg}）
    for cat_dir in sorted(cases_dir.iterdir()):
        if not cat_dir.is_dir():
            continue
        candidate = cat_dir / case_arg
        if candidate.is_dir():
            return candidate
    return Path()


def _is_case_dir(d: Path) -> bool:
    """判断目录是否为有效案例（有输入 mapping.xlsx 或 10_project_deliver 同名产出）。"""
    has_input = (d / "mapping.xlsx").exists()
    has_deliver = (DELIVER_BASE / d.name / "ddlc_design_dev" / "ts.json").exists()
    return has_input or has_deliver


def _scan_all_cases(cases_dir: Path) -> list[Path]:
    """扫描全部案例，兼容一级（cases/{资产}）和二级（cases_real/{分类}/{资产}）。

    一级目录若是有效案例直接收；否则当分类目录扫其下的二级资产目录。
    """
    results: list[Path] = []
    if not cases_dir.exists():
        return results
    for entry in sorted(cases_dir.iterdir()):
        if not entry.is_dir():
            continue
        if _is_case_dir(entry):
            results.append(entry)
        else:
            # 当分类目录处理，扫二级
            for sub in sorted(entry.iterdir()):
                if sub.is_dir() and _is_case_dir(sub):
                    results.append(sub)
    return results


def run_one_case(case_dir: Path, eval_only: bool, skip_ai: bool) -> int:
    """跑单个用例。"""
    case_name = case_dir.name
    deliver = DELIVER_BASE / case_name / "ddlc_design_dev"
    checks_path = case_dir / "checks.yaml"

    config = load_checks(checks_path)
    if not config.case_name:
        config.case_name = case_name

    pipeline_steps = None
    if not eval_only:
        deliver.mkdir(parents=True, exist_ok=True)
        print(f"[v2] 跑流水线: {case_name} → {deliver}")
        pipeline_steps = run_pipeline(case_dir, deliver, skip_ai=skip_ai)
        # 流程层失败提示
        failed = [s for s in pipeline_steps if s.status.value == "fail"]
        if failed:
            print(f"[v2] ⚠️ 流水线有 {len(failed)} 阶段失败，继续评测已有产出")
    else:
        if not deliver.exists():
            print(f"[v2] ❌ 产出目录不存在: {deliver}（去掉 --eval-only 先跑流水线）", file=sys.stderr)
            return 1
        print(f"[v2] 只评测: {case_name} ← {deliver}")

    # 评测（result.case_name 用 checks.yaml 的展示名，报告友好）
    result = run_evaluation(deliver, config, pipeline_steps)

    # baseline 对比（存档前先找上轮，对比后再存本次）
    # baseline 统一用 case_dir.name（目录名稳定唯一），不用展示名
    prev = baseline.find_latest_baseline(case_name)
    diff = baseline.diff_against_baseline(result, prev)

    # 存档：snapshot 用目录名，保证查找一致
    snapshot = baseline.snapshot_from_result(result)
    snapshot.case_name = case_name
    saved_path = baseline.save_snapshot(snapshot)
    print(f"[v2] baseline 已存档: {saved_path.name}")

    print(render_report(result, diff))

    # 退出码：有 FAIL 返回 1
    has_fail = any(
        r.status.value == "fail"
        for checks in result.layer_results.values()
        for r in checks
    ) or any(s.status.value == "fail" for s in (result.pipeline_steps or []))
    return 1 if has_fail else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="评测 v2")
    parser.add_argument("--case", default="", help="用例（如 002 或完整目录名）")
    parser.add_argument("--all", action="store_true", help="跑全部用例")
    parser.add_argument("--eval-only", action="store_true", help="只评测，不跑流水线")
    parser.add_argument("--skip-ai", action="store_true", help="跳过 AI 阶段（只跑脚本链路）")
    parser.add_argument(
        "--cases-dir",
        default="",
        help="用例目录（默认 eval-suite/cases/；内网真实用例用 eval-suite/cases_real/）",
    )
    args = parser.parse_args()

    cases_dir = Path(args.cases_dir) if args.cases_dir else CASES_DIR_DEFAULT

    if args.all:
        # 扫描兼容一级（cases/{资产}）和二级（cases_real/{分类}/{资产}）
        # 后者覆盖内网真实案例分类组织 + "只有产出没有输入目录"的 deliver_only 场景
        cases = _scan_all_cases(cases_dir)
        if not cases:
            print(f"[v2] 无用例: {cases_dir}", file=sys.stderr)
            return 1
        exit_code = 0
        for case_dir in cases:
            print(f"\n{'='*60}\n  {case_dir.name}\n{'='*60}")
            rc = run_one_case(case_dir, args.eval_only, args.skip_ai)
            exit_code = exit_code or rc
        return exit_code

    if not args.case:
        parser.print_help()
        return 1

    case_dir = resolve_case(args.case, cases_dir)
    if not case_dir or not case_dir.exists():
        print(f"[v2] ❌ 用例不存在: {args.case}（在 {cases_dir} 找不到）", file=sys.stderr)
        return 1

    return run_one_case(case_dir, args.eval_only, args.skip_ai)


if __name__ == "__main__":
    sys.exit(main())
