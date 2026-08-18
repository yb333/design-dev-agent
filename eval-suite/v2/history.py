#!/usr/bin/env python3
"""历史数据分析：results/ 下全部快照的跨轮趋势与跨案例对比。

数据源（已持久化，每轮一份）：results/{case}/{时间戳}/result.json
含 timestamp / git_sha / score / deductions / stage_times / stage_loops /
checks / pipeline_steps。

用法:
    python eval-suite/v2/history.py --case dwb_x    # 单案例全量历史
    python eval-suite/v2/history.py --all           # 跨案例总览
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

_EVAL_SUITE = Path(__file__).resolve().parent.parent
_V2_DIR = Path(__file__).resolve().parent
for p in (str(_EVAL_SUITE), str(_V2_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import baseline

SEP = "=" * 60


def load_history(case_name: str) -> list[dict]:
    """读某案例全部快照（按时间升序）。"""
    return stability_snippets(case_name, limit=None)


def stability_snippets(case_name: str, limit: int | None) -> list[dict]:
    case_dir = baseline.RESULTS_DIR / baseline._safe_name(case_name)
    if not case_dir.exists():
        return []
    ts_dirs = sorted(
        [d for d in case_dir.iterdir() if d.is_dir() and (d / "result.json").exists()],
        key=lambda d: d.name,
    )
    if limit:
        ts_dirs = ts_dirs[-limit:]
    snaps = []
    for d in ts_dirs:
        try:
            snaps.append(json.loads((d / "result.json").read_text(encoding="utf-8")))
        except Exception:
            continue
    return snaps


def list_cases_with_history() -> list[str]:
    """有历史快照的案例名列表。"""
    if not baseline.RESULTS_DIR.exists():
        return []
    return sorted(
        d.name for d in baseline.RESULTS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("_")  # _live 等系统目录不算案例
    )


def _golden(snap: dict) -> str:
    for c in snap.get("checks", []):
        if c.get("layer") == "golden":
            d = c.get("detail", "")
            if d.startswith("命中 golden:"):
                return d.split("命中 golden:", 1)[1].strip()[:8]
            if d.startswith("未命中"):
                return "未命中"
            return "-"
    return "-"


def _total_secs(snap: dict) -> float:
    return sum((snap.get("stage_times") or {}).values())


def _loops_desc(snap: dict) -> str:
    loops = {k: v for k, v in (snap.get("stage_loops") or {}).items() if v > 1}
    if not loops:
        return "-"
    return " ".join(f"{k}×{v - 1}" for k, v in sorted(loops.items()))


def render_case_history(case_name: str) -> str:
    snaps = load_history(case_name)
    lines = [SEP, f"  历史分析: {case_name}（{len(snaps)} 轮）", SEP]
    if not snaps:
        lines.append("  无快照")
        return "\n".join(lines)

    # 轮次明细
    lines += ["", "── 轮次明细 ────────────────────────────────────────"]
    for i, s in enumerate(snaps, 1):
        ts = (s.get("timestamp") or "?")[5:16]  # MM-DD HH:MM
        score = s.get("score")
        score_s = f"{score}" if score is not None else "-"
        total = _total_secs(s)
        lines.append(
            f"  #{i:<3} {ts}  分数 {score_s:>3}  golden {_golden(s):<8} "
            f"总耗时 {total:6.0f}s  回路 {_loops_desc(s)}"
        )

    # 分数趋势
    scores = [s["score"] for s in snaps if s.get("score") is not None]
    if scores:
        lines += ["", "── 分数 ────────────────────────────────────────────"]
        recent = scores[-5:]
        lines.append(
            f"  min {min(scores)} / max {max(scores)} / avg {sum(scores) / len(scores):.0f}"
            f" ｜ 最近5轮: {' '.join(map(str, recent))}"
        )

    # 阶段耗时：全程 avg + 早期 vs 晚期（前半 vs 后半，看优化效果）
    stage_samples: dict[str, list[float]] = defaultdict(list)
    for s in snaps:
        for st, secs in (s.get("stage_times") or {}).items():
            stage_samples[st].append(float(secs))
    if stage_samples:
        lines += ["", "── 阶段耗时（全程 avg / 早期→晚期）─────────────────"]
        half = len(snaps) // 2
        early_snaps, late_snaps = snaps[:max(1, half)], snaps[max(1, half):] or snaps
        for st, vals in stage_samples.items():
            avg = sum(vals) / len(vals)

            def _avg_of(group):
                xs = [float(x) for s2 in group for x in [s2.get("stage_times", {}).get(st)] if x]
                return sum(xs) / len(xs) if xs else 0.0

            e, l = _avg_of(early_snaps), _avg_of(late_snaps)
            trend = "→" if abs(l - e) < 1 else ("↓变快" if l < e else "↑变慢")
            lines.append(f"  {st:<8} avg {avg:7.1f}s  早期 {e:7.1f}s → 晚期 {l:7.1f}s  {trend}")
        # 最耗时阶段
        top = max(stage_samples, key=lambda k: sum(stage_samples[k]) / len(stage_samples[k]))
        lines.append(f"  ▸ 最耗时阶段: {top}")

    # 回路统计（全程）
    loop_total: dict[str, int] = defaultdict(int)
    loop_rounds: dict[str, int] = defaultdict(int)
    for s in snaps:
        for st, occ in (s.get("stage_loops") or {}).items():
            if occ > 1:
                loop_total[st] += occ - 1
                loop_rounds[st] += 1
    lines += ["", "── 执行回路（全程）─────────────────────────────────"]
    if loop_total:
        for st in sorted(loop_total, key=lambda k: -loop_total[k]):
            lines.append(f"  {st}: 共 {loop_total[st]} 次回路 / {loop_rounds[st]}/{len(snaps)} 轮触发")
    else:
        lines.append("  （无回路记录——流程一次通过）")

    lines.append(SEP)
    return "\n".join(lines)


def render_all_cases() -> str:
    cases = list_cases_with_history()
    lines = [SEP, f"  跨案例总览（{len(cases)} 案例）", SEP]
    if not cases:
        lines.append("  results/ 下无快照")
        return "\n".join(lines)
    lines += ["", f"  {'案例':<28} {'轮次':>4} {'平均分':>6} {'最近分':>6} {'平均总耗时':>10} {'最耗时阶段':<10} 回路"]
    for c in cases:
        snaps = load_history(c)
        scores = [s["score"] for s in snaps if s.get("score") is not None]
        avg_score = f"{sum(scores) / len(scores):.0f}" if scores else "-"
        last_score = str(scores[-1]) if scores else "-"
        totals = [_total_secs(s) for s in snaps]
        avg_total = f"{sum(totals) / len(totals):.0f}s" if totals else "-"
        stage_samples: dict[str, list[float]] = defaultdict(list)
        for s in snaps:
            for st, secs in (s.get("stage_times") or {}).items():
                stage_samples[st].append(float(secs))
        top = max(stage_samples, key=lambda k: sum(stage_samples[k])) if stage_samples else "-"
        loop_n = sum(1 for s in snaps
                     if any(v > 1 for v in (s.get("stage_loops") or {}).values()))
        lines.append(
            f"  {c:<28} {len(snaps):>4} {avg_score:>6} {last_score:>6} "
            f"{avg_total:>10} {str(top):<10} {loop_n}/{len(snaps)}"
        )
    lines.append(SEP)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="历史数据分析（跨轮趋势/跨案例对比）")
    parser.add_argument("--case", default="", help="单案例全量历史")
    parser.add_argument("--all", action="store_true", help="跨案例总览")
    args = parser.parse_args()
    if args.all:
        print(render_all_cases())
        return 0
    if args.case:
        print(render_case_history(args.case))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
