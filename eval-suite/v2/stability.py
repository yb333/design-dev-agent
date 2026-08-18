"""稳定性报告：聚合 N 次运行快照（results/{case}/{ts}/result.json）。

回答三个问题：
1. N 次里多少轮全绿、多少轮有异常？
2. 哪些断言稳定（10/10 过 / 0/10 全挂）、哪些摇摆（时而过时而挂）？
3. golden 命中分布——在多个认可方案间摇摆 = 正常；出现"未命中"轮 = 越界待裁决。

零交互约定：报告只陈述事实，不做任何确认；异常轮产出物已留档
（results/{case}/{ts}/artifacts/，仅异常轮保留，省磁盘）。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import baseline


def load_recent_snapshots(case_name: str, n: int) -> list[dict]:
    """读该案例最近 n 份快照（按时间戳升序）。"""
    case_dir = baseline.RESULTS_DIR / baseline._safe_name(case_name)
    if not case_dir.exists():
        return []
    ts_dirs = sorted(
        [d for d in case_dir.iterdir() if d.is_dir() and (d / "result.json").exists()],
        key=lambda d: d.name,
    )
    snaps = []
    for d in ts_dirs[-n:]:
        try:
            snaps.append(json.loads((d / "result.json").read_text(encoding="utf-8")))
        except Exception:
            continue
    return snaps


def _golden_status(snap: dict) -> str:
    """从快照提取 golden 命中状态：'方案X' / '未命中' / '无golden'。"""
    for c in snap.get("checks", []):
        if c.get("layer") == "golden":
            detail = c.get("detail", "")
            if detail.startswith("命中 golden:"):
                return detail.split("命中 golden:", 1)[1].strip()
            if detail.startswith("未命中"):
                return "未命中"
            return "无golden"
    return "无golden"


def _snapshot_had_fail(snap: dict) -> bool:
    return any(c.get("status") == "fail" for c in snap.get("checks", [])) or any(
        s.get("status") == "fail" for s in snap.get("pipeline_steps", [])
    )


def classify_assertions(snaps: list[dict]) -> dict[str, list[dict]]:
    """断言级聚合：{(layer,key)} → pass/fail/skip 计数，并分类。

    分类：stable_pass（全过）/ stable_fail（全挂）/ flaky（摇摆）/ all_skip
    """
    agg: dict[tuple, dict] = defaultdict(lambda: {"pass": 0, "fail": 0, "skip": 0})
    for snap in snaps:
        seen: set[tuple] = set()
        for c in snap.get("checks", []):
            key = (c.get("layer", "?"), c.get("key", "?"))
            # 同一快照内同 key 多条（如多规则）只计一次，避免单轮重复放大
            status = c.get("status", "skip")
            if key in seen and status != "fail":
                continue
            agg[key][status] = agg[key].get(status, 0) + 1
            seen.add(key)
    rows: list[dict] = []
    for (layer, key), cnt in sorted(agg.items()):
        p, f = cnt.get("pass", 0), cnt.get("fail", 0)
        if f == 0 and p > 0:
            cls = "stable_pass"
        elif p == 0 and f > 0:
            cls = "stable_fail"
        elif p > 0 and f > 0:
            cls = "flaky"
        else:
            cls = "all_skip"
        rows.append({"layer": layer, "key": key, "pass": p, "fail": f, "skip": cnt.get("skip", 0),
                     "class": cls})
    return {"rows": rows}


def render_stability(case_name: str, snaps: list[dict]) -> str:
    """渲染稳定性报告文本。"""
    sep = "=" * 60
    lines: list[str] = []
    n = len(snaps)
    lines.append(sep)
    lines.append(f"  稳定性报告: {case_name}（{n} 次）")
    if n == 0:
        lines.append("  无快照可聚合")
        lines.append(sep)
        return "\n".join(lines)
    lines.append(f"  时间: {snaps[0].get('timestamp','?')} → {snaps[-1].get('timestamp','?')}"
                 f"   git: {snaps[-1].get('git_sha','?')}")
    lines.append(sep)

    # 每轮结果
    lines.append("")
    lines.append("── 每轮结果 ────────────────────────────────────────")
    for i, snap in enumerate(snaps, 1):
        stats = snap.get("layer_stats", {})
        p = sum(v.get("pass", 0) for v in stats.values())
        f = sum(v.get("fail", 0) for v in stats.values())
        gs = _golden_status(snap)
        icon = "✅" if not _snapshot_had_fail(snap) else "❌"
        ts_dir = snap.get("timestamp", "").replace(":", "-")
        archived = ""
        case_dir = baseline.RESULTS_DIR / baseline._safe_name(case_name) / ts_dir
        if (case_dir / "artifacts").exists():
            archived = f"  [产出已留档: .../{ts_dir}/artifacts]"
        sc = snap.get("score")
        score_part = f"  分数 {sc}" if sc is not None else ""
        lines.append(f"  #{i:<2} {icon} {p}通过/{f}失败{score_part}  golden: {gs}{archived}")

    # 分数趋势
    scores = [s.get("score") for s in snaps if s.get("score") is not None]
    if scores:
        lines.append("")
        lines.append("── 分数趋势 ─────────────────────────────────────────")
        lines.append("  " + " ".join(str(x) for x in scores))
        if len(scores) > 1:
            lines.append(f"  波动: min {min(scores)} / max {max(scores)} / 首末 {scores[0]}→{scores[-1]}")

    # 断言稳定性
    rows = classify_assertions(snaps)["rows"]
    by_cls: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cls[r["class"]].append(r)
    lines.append("")
    lines.append("── 断言稳定性 ──────────────────────────────────────")
    lines.append(f"  ✅ 稳定过 {len(by_cls.get('stable_pass', []))} 项")
    for r in by_cls.get("stable_fail", []):
        total = r["pass"] + r["fail"]
        lines.append(f"  ❌ 稳定挂 [{r['layer']}] {r['key']} — 0/{total}")
    for r in by_cls.get("flaky", []):
        total = r["pass"] + r["fail"]
        lines.append(f"  ⚠️ 摇摆   [{r['layer']}] {r['key']} — {r['pass']}/{total}（{r['fail']}次失败）")
    if not by_cls.get("stable_fail") and not by_cls.get("flaky"):
        lines.append("  （无不稳定项）")

    # golden 命中分布
    lines.append("")
    lines.append("── golden 命中分布 ─────────────────────────────────")
    dist: dict[str, int] = defaultdict(int)
    for snap in snaps:
        dist[_golden_status(snap)] += 1
    for name, cnt in sorted(dist.items(), key=lambda x: -x[1]):
        lines.append(f"  {name}: {cnt}/{n}")
    if dist.get("未命中"):
        lines.append("  ⚠️ 有越界轮（未命中任何 golden）——待人工裁决：")
        lines.append("     认可为新方案 → promote.py 手工沉淀新 golden；视为回归 → 去修")

    # 阶段耗时分布（真实=marker 估算 / 重放=步骤实测；跨轮 avg/min/max）
    stage_samples: dict[str, list[float]] = defaultdict(list)
    for snap in snaps:
        for stage, secs in (snap.get("stage_times") or {}).items():
            stage_samples[stage].append(float(secs))
    if stage_samples:
        lines.append("")
        lines.append("── 阶段耗时分布 ─────────────────────────────────────")
        order = [st for st, _ in __import__("real_pipe")._STAGE_MARKERS]
        known = [st for st in order if st in stage_samples]
        others = sorted(set(stage_samples) - set(known))
        for stage in known + others:
            vals = stage_samples[stage]
            avg = sum(vals) / len(vals)
            lines.append(
                f"  {stage:<8} avg {avg:7.1f}s  min {min(vals):7.1f}s  max {max(vals):7.1f}s  ({len(vals)}轮)"
            )

    # 流程阶段稳定性
    lines.append("")
    lines.append("── 流程阶段稳定性 ──────────────────────────────────")
    stage_pass: dict[str, int] = defaultdict(int)
    stage_total: dict[str, int] = defaultdict(int)
    for snap in snaps:
        seen = set()
        for s in snap.get("pipeline_steps", []):
            name = s.get("step", "?")
            if name in seen:
                continue
            stage_total[name] += 1
            if s.get("status") == "pass":
                stage_pass[name] += 1
            seen.add(name)
    for name in sorted(stage_total):
        p, t = stage_pass[name], stage_total[name]
        icon = "✅" if p == t else "⚠️"
        lines.append(f"  {icon} {name} {p}/{t}")

    lines.append(sep)
    return "\n".join(lines)
