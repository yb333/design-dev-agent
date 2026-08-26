"""评测报告渲染：分层 + 归因 + 与上轮对比。

P1：流程层 + 产物层。design/code 层显示 SKIP。
首跑无 baseline 时显示「无基线」（baseline 对比 P3 实现）。
"""

from __future__ import annotations

from datetime import datetime

from engine import EvalResult, LAYER_NAMES, LAYER_PIPELINE


def render_report(result: EvalResult, diff=None) -> str:
    """渲染单用例评测报告，返回字符串。

    Args:
        result: 评测结果。
        diff: baseline 对比结果（BaselineDiff 或 None）。
    """
    lines: list[str] = []
    sep = "=" * 60

    lines.append(sep)
    lines.append(f"  评测报告: {result.case_name}")
    lines.append(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(sep)

    stats = result.summary()

    # 流程层（带耗时）
    if result.pipeline_steps:
        lines.append("")
        lines.append("── 流程层 ──────────────────────────────────────────")
        for s in result.pipeline_steps:
            symbol = _icon(s.status)
            lines.append(f"  {symbol} {s.step:<18} {s.duration_seconds:>6.1f}s  {s.detail}")
        total_dur = sum(s.duration_seconds for s in result.pipeline_steps)
        passed = sum(1 for s in result.pipeline_steps if s.status.value == "pass")
        failed = sum(1 for s in result.pipeline_steps if s.status.value == "fail")
        lines.append(f"  {'─'*50}")
        lines.append(f"  流程: ✅{passed}通过  ❌{failed}失败  总耗时 {total_dur:.1f}s")

    # 各断言层
    for layer, name in LAYER_NAMES.items():
        if layer == LAYER_PIPELINE:
            continue  # 流程层已单独渲染
        checks = result.layer_results.get(layer, [])
        if not checks:
            continue
        s = stats.get(layer, {"pass": 0, "fail": 0, "skip": 0})
        header = f"── {name} ({s['pass']}/{s['pass']+s['fail']+s['skip']}) "
        lines.append("")
        lines.append(header + "─" * max(0, 50 - len(header)))
        for c in checks:
            symbol = _icon(c.status)
            lines.append(f"  {symbol} {c.detail}")
        # 归因
        failed = [c for c in checks if c.status.value == "fail"]
        if failed:
            owner = _owner(layer)
            lines.append(f"  → 归因: {owner}")

    # 总分（P1 简单统计，P3 加 baseline 对比）
    lines.append("")
    lines.append("── 总览 ───────────────────────────────────────────")
    total_pass = sum(s["pass"] for s in stats.values())
    total_fail = sum(s["fail"] for s in stats.values())
    total_skip = sum(s["skip"] for s in stats.values())
    lines.append(f"  断言: ✅{total_pass}通过  ❌{total_fail}失败  ⏭️{total_skip}跳过")

    # baseline 对比
    lines.append("")
    if diff is None or not diff.has_baseline:
        lines.append("  与上轮对比: 无基线（首跑）")
    else:
        lines.append(f"  与上轮对比: {diff.baseline_timestamp} (sha:{diff.baseline_git_sha})")
        if diff.regressions:
            lines.append(f"    ❌ 回退 {len(diff.regressions)} 项:")
            for r in diff.regressions[:5]:
                lines.append(f"       {r}")
        if diff.new_failures:
            lines.append(f"    ⚠️ 新增失败 {len(diff.new_failures)} 项:")
            for r in diff.new_failures[:5]:
                lines.append(f"       {r}")
        if diff.fixes:
            lines.append(f"    ✅ 修复 {len(diff.fixes)} 项:")
            for r in diff.fixes[:5]:
                lines.append(f"       {r}")
        if not diff.regressions and not diff.new_failures and not diff.fixes:
            lines.append("    → 无变化")

    lines.append(sep)
    return "\n".join(lines)


def _icon(status) -> str:
    """状态图标。status 是 CheckStatus 或 str。"""
    v = status.value if hasattr(status, "value") else str(status)
    return {"pass": "✅", "fail": "❌", "skip": "⏭️"}.get(v, "❓")


def _owner(layer: str) -> str:
    """失败归因到责任主体。"""
    return {
        "pipeline": "脚本/契约/案例数据（看具体阶段）",
        "artifacts": "脚本（assemble_ts/assemble_ddl 等）",
        "design": "designer 角色（或 design skill）",
        "code": "coder 角色（或 coding skill）",
        "golden": "待人工裁决（可能新合理方案 → promote 沉淀；可能回归 → 修）",
        "discipline": "agent 绕过流程自建脚本（待人裁决：修流程堵根因 / 修案例）",
    }.get(layer, "未知")
