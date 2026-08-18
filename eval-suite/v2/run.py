#!/usr/bin/env python3
"""评测 v2 CLI 入口。

用法:
    python eval-suite/v2/run.py --case 002             # 全流程（跑流水线 + 评测）
    python eval-suite/v2/run.py --case 002 --eval-only  # 只评测（已有产出）
    python eval-suite/v2/run.py --all                    # 跑全部用例
    python eval-suite/v2/run.py --case 002 --repeat 10   # 稳定性：连跑10次出稳定性报告
    python eval-suite/v2/run.py --case 002 --skip-ai     # 跳过 AI（只跑脚本链路）
    python eval-suite/v2/run.py --case 002 --timeout-ai 3600 --timeout-script 300

输出: 分层报告到 stdout；--repeat 额外出稳定性报告，异常轮产出物留档
（results/{case}/{ts}/artifacts/，仅异常轮保留）。
golden 层：案例目录有 golden/ 就比对（命中任一即过；全不中=越界待人裁决）。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

# 让 `from v2.xxx import` 和 `from checks_schema import` 都能工作
ROOT = Path(__file__).resolve().parents[2]
EVAL_SUITE = Path(__file__).resolve().parents[1]
V2_DIR = Path(__file__).resolve().parent
for p in (str(EVAL_SUITE), str(V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from checks_schema import load_checks  # noqa: E402
from engine import run_evaluation, LAYER_GOLDEN  # noqa: E402
from pipeline import (  # noqa: E402
    DEFAULT_TIMEOUT_AI,
    DEFAULT_TIMEOUT_SCRIPT,
    run_pipeline,
)
from real_pipe import DEFAULT_TIMEOUT_PIPE, run_real_pipe  # noqa: E402
from report_v2 import render_report  # noqa: E402
from _paths import find_deliver, find_mapping_file, find_rs_file  # noqa: E402
import baseline  # noqa: E402
import golden  # noqa: E402
import stability  # noqa: E402


CASES_DIR_DEFAULT = EVAL_SUITE / "cases"
DELIVER_BASE = ROOT / "10_project_deliver"


def select_executor(replay: bool, skip_ai: bool) -> str:
    """执行方式选择：real=真实入口（默认，/new-pipe 命令）| replay=分阶段重放（诊断）。

    --skip-ai 只在重放模式有意义（真实入口不可能跳过 AI）→ 请求 skip-ai 自动降级 replay。
    """
    return "replay" if (replay or skip_ai) else "real"


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
    """判断目录是否为有效案例（有输入 mapping 文件或 10_project_deliver 同名产出）。"""
    has_input = find_mapping_file(d) is not None
    has_deliver = find_deliver(DELIVER_BASE, d.name) is not None
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


def _attach_golden(result, deliver: Path, case_dir: Path) -> None:
    """挂 golden 命中层（案例无 golden 时该层 SKIP，不影响其他层）。"""
    result.add_layer(LAYER_GOLDEN, golden.golden_check(deliver, case_dir))


def _result_has_fail(result) -> bool:
    return any(
        r.status.value == "fail"
        for checks in result.layer_results.values()
        for r in checks
    ) or any(s.status.value == "fail" for s in (result.pipeline_steps or []))


def _fail_summary_line(result, pipeline_steps) -> str:
    """--all 失败清单用的一行摘要。"""
    failed_steps = [s.step for s in (pipeline_steps or []) if s.status.value == "fail"]
    failed_checks = [
        c for checks in result.layer_results.values() for c in checks if c.status.value == "fail"
    ]
    if not failed_steps and not failed_checks:
        return ""
    parts = []
    if failed_steps:
        parts.append("流程挂: " + ",".join(failed_steps[:3]))
    if failed_checks:
        brief = "; ".join(c.detail.split("\n")[0][:60] for c in failed_checks[:3])
        parts.append(f"断言挂{len(failed_checks)}条: {brief}")
    return " | ".join(parts)


def _archive_anomalous_artifacts(case_name: str, snapshot, deliver: Path) -> str:
    """异常轮产出物留档（仅失败/越界轮调用，稳定轮不占磁盘）。"""
    try:
        ts_dir = (
            baseline.RESULTS_DIR
            / baseline._safe_name(case_name)
            / snapshot.timestamp.replace(":", "-")
        )
        dest = ts_dir / "artifacts"
        shutil.copytree(deliver, dest, dirs_exist_ok=True)
        return str(dest)
    except Exception as e:
        return f"(留档失败: {e})"


def _run_pipeline_for(case_dir: Path, deliver: Path, executor: str, skip_ai: bool,
                      timeout_ai: float, timeout_script: float, timeout_pipe: float):
    """按执行方式跑流程：real=真实入口单步 / replay=分阶段重放。"""
    if executor == "real":
        return run_real_pipe(case_dir, DELIVER_BASE, timeout_pipe)
    return run_pipeline(
        case_dir, deliver, skip_ai=skip_ai, timeout_ai=timeout_ai, timeout_script=timeout_script
    )


def _resolve_appid_quiet(schema: str) -> str:
    """按 schema 查 appid（schema_apps.json 标准源）；查不到返回空串不抛异常。"""
    if not schema:
        return ""
    try:
        import pipeline as _pipeline

        if str(_pipeline.SHARED_REFS) not in sys.path:
            sys.path.insert(0, str(_pipeline.SHARED_REFS))
        from config_paths import resolve_appid

        return resolve_appid(schema) or ""
    except Exception:
        return ""


def _resolve_replay_deliver(case_dir: Path, case_name: str, timeout_script: float) -> Path:
    """重放模式无既有产出时，推导三层产出目录 {appid}/{schema}/{case}/ddlc_design_dev。

    路径推导与 new-pipe 同源：schema 从 mapping 目标表（preprocess 产物）读，
    appid 查 schema_apps.json。先预处理到暂存目录，推导后把 _internal 搬过去。
    """
    import json as _json

    from pipeline import _preprocess

    staging = DELIVER_BASE / "_replay_staging" / case_name
    from _paths import find_mapping_file, find_rs_file

    mapping = find_mapping_file(case_dir)
    if not mapping:
        raise RuntimeError(f"案例目录没有 mapping 文件（*.xlsx/xls 名含 mapping）: {case_dir}")
    ok, detail = _preprocess(staging, mapping, find_rs_file(case_dir), timeout_script)
    rs_input = staging / "_internal" / "rs_input.json"
    if not rs_input.exists():
        raise RuntimeError(
            f"重放定位失败：preprocess 未产出 rs_input（{detail.splitlines()[0][:150]}）"
        )
    data = _json.loads(rs_input.read_text(encoding="utf-8"))
    schema = data.get("meta", {}).get("target", {}).get("f_table", {}).get("schema", "")
    appid = _resolve_appid_quiet(schema)
    if not schema or not appid:
        raise RuntimeError(
            f"重放定位失败：无法确定三层目录（schema='{schema}' appid='{appid}'）。"
            "schema 从 mapping 目标表推导；appid 需要 schema_apps.json 配置该 schema——"
            "配置后重试，或先跑一次真实入口让 new-pipe 建好目录"
        )
    deliver = DELIVER_BASE / appid / schema / case_name / "ddlc_design_dev"
    deliver.mkdir(parents=True, exist_ok=True)
    # 搬运暂存 _internal（重放的 preprocess 会再跑一遍写入 deliver，这里只为目录成型）
    if not (deliver / "_internal" / "rs_input.json").exists():
        shutil.copytree(staging / "_internal", deliver / "_internal", dirs_exist_ok=True)
    return deliver


def _prepare_deliver_for(deliver: Path | None, executor: str, case_dir: Path, case_name: str,
                         timeout_script: float) -> Path:
    """跑流程前确保 deliver 就绪：重放无产出时推导三层路径并建目录；真实入口不动。"""
    if executor != "replay":
        return deliver or (DELIVER_BASE / "_未定位" / case_name / "ddlc_design_dev")
    deliver = deliver or _resolve_replay_deliver(case_dir, case_name, timeout_script)
    deliver.mkdir(parents=True, exist_ok=True)
    return deliver


def _run_repeat(
    case_dir: Path,
    case_name: str,
    deliver: Path,
    config,
    executor: str,
    skip_ai: bool,
    repeat: int,
    timeout_ai: float,
    timeout_script: float,
    timeout_pipe: float,
) -> tuple[int, str]:
    """稳定性模式：连跑 N 次，聚合稳定性报告。评测零交互，不问任何问题。"""
    pipeline_ok_runs = 0
    for i in range(1, repeat + 1):
        print(f"\n{'=' * 60}\n  [重复 {i}/{repeat}] {case_name}（{executor}）\n{'=' * 60}")
        deliver = _prepare_deliver_for(deliver, executor, case_dir, case_name, timeout_script)
        pipeline_steps = _run_pipeline_for(
            case_dir, deliver, executor, skip_ai, timeout_ai, timeout_script, timeout_pipe
        )
        if executor == "real":
            # 真实入口的产出目录由 new-pipe 自建（三层），跑完重新定位
            deliver = find_deliver(DELIVER_BASE, case_name) or deliver
        pipeline_failed = any(s.status.value == "fail" for s in pipeline_steps)
        if not pipeline_failed:
            pipeline_ok_runs += 1

        result = run_evaluation(deliver, config, pipeline_steps)
        _attach_golden(result, deliver, case_dir)

        snapshot = baseline.snapshot_from_result(result)
        snapshot.case_name = case_name
        baseline.save_snapshot(snapshot)

        stats = result.summary()
        p = sum(v["pass"] for v in stats.values())
        f = sum(v["fail"] for v in stats.values())
        golden_results = result.layer_results.get("golden", [])
        gs = golden_results[0].detail.split("\n")[0] if golden_results else "无golden"
        print(f"  ▸ 本轮: ✅{p} ❌{f}  golden: {gs}")

        if pipeline_failed or _result_has_fail(result):
            dest = _archive_anomalous_artifacts(case_name, snapshot, deliver)
            print(f"  ▸ 异常轮，产出已留档: {dest}")

    snaps = stability.load_recent_snapshots(case_name, repeat)
    print(stability.render_stability(case_name, snaps))
    # 稳定性模式是测量不是闸门：只要不是"每轮流水线都崩"就返回 0（细节看报告）
    rc = 0 if pipeline_ok_runs > 0 else 1
    return rc, f"{repeat}轮完成（{pipeline_ok_runs}轮流水线正常，详见稳定性报告）"


def run_one_case(
    case_dir: Path,
    eval_only: bool,
    skip_ai: bool,
    repeat: int = 1,
    replay: bool = False,
    timeout_ai: float = DEFAULT_TIMEOUT_AI,
    timeout_script: float = DEFAULT_TIMEOUT_SCRIPT,
    timeout_pipe: float = DEFAULT_TIMEOUT_PIPE,
) -> tuple[int, str]:
    """跑单个用例。返回 (退出码, 失败摘要行——全过时为空)。"""
    case_name = case_dir.name
    # 三层产出定位（{appid}/{schema}/{资产}）；无产出时 None——
    # 重放模式由 _prepare_deliver_for 推导，真实入口跑完重定位，eval-only 直接报错
    deliver = find_deliver(DELIVER_BASE, case_name)
    checks_path = case_dir / "checks.yaml"

    config = load_checks(checks_path)
    if not config.case_name:
        config.case_name = case_name

    executor = select_executor(replay, skip_ai)

    # 稳定性模式
    if repeat > 1:
        if eval_only:
            print("[v2] ❌ --repeat 与 --eval-only 互斥（稳定性要重跑流水线）", file=sys.stderr)
            return 1, "参数冲突"
        return _run_repeat(
            case_dir, case_name, deliver, config, executor, skip_ai, repeat,
            timeout_ai, timeout_script, timeout_pipe,
        )

    pipeline_steps = None
    if not eval_only:
        deliver = _prepare_deliver_for(deliver, executor, case_dir, case_name, timeout_script)
        mode_desc = "真实入口 /new-pipe" if executor == "real" else "重放诊断 --replay"
        print(f"[v2] 跑流水线（{mode_desc}）: {case_name}")
        pipeline_steps = _run_pipeline_for(
            case_dir, deliver, executor, skip_ai, timeout_ai, timeout_script, timeout_pipe
        )
        if executor == "real":
            # 真实入口的产出目录由 new-pipe 自建（三层），跑完重新定位再评测
            deliver = find_deliver(DELIVER_BASE, case_name) or deliver
            print(f"[v2] 产出定位: {deliver}")
        # 流程层失败提示
        failed = [s for s in pipeline_steps if s.status.value == "fail"]
        if failed:
            print(f"[v2] ⚠️ 流水线有 {len(failed)} 阶段失败，继续评测已有产出")
    else:
        if not deliver:
            print(
                f"[v2] ❌ 三层产出不存在: 10_project_deliver/{{appid}}/{{schema}}/{case_name}"
                f"/ddlc_design_dev（去掉 --eval-only 先跑真实入口）",
                file=sys.stderr,
            )
            return 1, "产出不存在"
        print(f"[v2] 只评测: {case_name} ← {deliver}")

    # 评测（result.case_name 用 checks.yaml 的展示名，报告友好）
    result = run_evaluation(deliver, config, pipeline_steps)
    _attach_golden(result, deliver, case_dir)

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

    has_fail = _result_has_fail(result)
    return (1 if has_fail else 0), _fail_summary_line(result, pipeline_steps)


def main() -> int:
    parser = argparse.ArgumentParser(description="评测 v2")
    parser.add_argument("--case", default="", help="用例（如 002 或完整目录名）")
    parser.add_argument("--all", action="store_true", help="跑全部用例")
    parser.add_argument("--eval-only", action="store_true", help="只评测，不跑流水线")
    parser.add_argument("--skip-ai", action="store_true", help="跳过 AI 阶段（只跑脚本链路）")
    parser.add_argument("--repeat", type=int, default=1,
                        help="稳定性模式：连跑 N 次并出稳定性报告（默认 1=普通单跑）")
    parser.add_argument("--replay", action="store_true",
                        help="分阶段重放模式（诊断用）；默认真实入口 /new-pipe")
    parser.add_argument("--timeout-pipe", type=int, default=DEFAULT_TIMEOUT_PIPE,
                        help=f"真实入口整条流程超时秒数（默认 {DEFAULT_TIMEOUT_PIPE}）")
    parser.add_argument("--timeout-ai", type=int, default=DEFAULT_TIMEOUT_AI,
                        help=f"重放模式 AI 阶段超时秒数（默认 {DEFAULT_TIMEOUT_AI}）")
    parser.add_argument("--timeout-script", type=int, default=DEFAULT_TIMEOUT_SCRIPT,
                        help=f"重放模式脚本阶段超时秒数（默认 {DEFAULT_TIMEOUT_SCRIPT}）")
    parser.add_argument("--opencode", default="",
                        help="agent 启动器完整路径（默认先找 nga 再找 opencode；"
                             "解析不到时显式指定，如内网 nga 或 Windows 的 "
                             "C:/Users/xx/AppData/Roaming/npm/opencode.cmd）")
    parser.add_argument(
        "--cases-dir",
        default="",
        help="用例目录（默认 eval-suite/cases/；内网真实用例用 eval-suite/cases_real/）",
    )
    args = parser.parse_args()

    if args.opencode:
        os.environ["EVAL_OPENCODE"] = args.opencode

    cases_dir = Path(args.cases_dir) if args.cases_dir else CASES_DIR_DEFAULT

    if args.all:
        # 扫描兼容一级（cases/{资产}）和二级（cases_real/{分类}/{资产}）
        # 后者覆盖内网真实案例分类组织 + "只有产出没有输入目录"的 deliver_only 场景
        cases = _scan_all_cases(cases_dir)
        if not cases:
            print(f"[v2] 无用例: {cases_dir}", file=sys.stderr)
            return 1
        exit_code = 0
        failures: list[tuple[str, str]] = []
        for case_dir in cases:
            print(f"\n{'=' * 60}\n  {case_dir.name}\n{'=' * 60}")
            rc, line = run_one_case(
                case_dir, args.eval_only, args.skip_ai,
                repeat=args.repeat,
                replay=args.replay,
                timeout_ai=args.timeout_ai,
                timeout_script=args.timeout_script,
                timeout_pipe=args.timeout_pipe,
            )
            exit_code = exit_code or rc
            if rc:
                failures.append((case_dir.name, line))
        # 失败清单（哪里报错一眼可见；逐案详情往上翻或看 results/ 存档）
        if failures:
            print(f"\n{'=' * 60}\n  失败清单（{len(failures)}/{len(cases)} 案例）\n{'=' * 60}")
            for name, line in failures:
                print(f"  ❌ {name}: {line or '见上方报告'}")
        return exit_code

    if not args.case:
        parser.print_help()
        return 1

    case_dir = resolve_case(args.case, cases_dir)
    if not case_dir or not case_dir.exists():
        print(f"[v2] ❌ 用例不存在: {args.case}（在 {cases_dir} 找不到）", file=sys.stderr)
        return 1

    rc, _ = run_one_case(
        case_dir, args.eval_only, args.skip_ai,
        repeat=args.repeat,
        replay=args.replay,
        timeout_ai=args.timeout_ai,
        timeout_script=args.timeout_script,
        timeout_pipe=args.timeout_pipe,
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
