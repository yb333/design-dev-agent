"""Evaluation report generator — layered scoring report with actionable diagnostics."""

from __future__ import annotations

from typing import Any

_STATUS_ICON = {
    "pass": "\u2705",
    "fail": "\u274c",
    "SKIP": "\u26a0\ufe0f",
    "skip": "\u26a0\ufe0f",
}

_SEPARATORS = "=" * 60
_THIN_SEP = "-" * 60

LAYER_NAMES = {
    "structure": "\u7ed3\u6784\u5408\u89c4",
    "field_completeness": "\u5b57\u6bb5\u5b8c\u6574\u6027",
    "ddl_etl_consistency": "DDL/ETL\u4e00\u81f4\u6027",
    "etl_logic": "ETL\u903b\u8f91\u8986\u76d6",
    "safety": "\u5b89\u5168\u5408\u89c4",
}


def _icon(status: str) -> str:
    return _STATUS_ICON.get(status, "\u2753")


def _layer_display(layer_key: str) -> str:
    return LAYER_NAMES.get(layer_key, layer_key)


def generate_case_report(case_result: dict[str, Any]) -> None:
    case_name = case_result.get("case_name", "unknown")
    scope = case_result.get("scope", "unknown")
    results = case_result.get("results", [])
    layer_scores = case_result.get("layer_scores", {})
    scoring = case_result.get("scoring", {})
    duration = case_result.get("duration_seconds", 0.0)

    print(f"\n{_SEPARATORS}")
    print(f"  Eval Report: {case_name}")
    print(f"  Scope: {scope}")
    print(_SEPARATORS)

    if not scoring or not layer_scores:
        _print_flat_results(results, duration)
        return

    _print_layered_results(results, scoring, layer_scores, duration)


def _print_flat_results(results: list[dict], duration: float) -> None:
    for check in results:
        check_type = check.get("check_type", "unknown")
        status = str(check.get("status", "unknown"))
        detail = check.get("detail", "")
        evidence = check.get("evidence", "")

        print(f"  {_icon(status)} {check_type}: {detail}")
        if evidence:
            for line in evidence.split("\n"):
                print(f"     {line}")

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    print(_THIN_SEP)
    print(f"  Result: {passed}/{total} passed")
    print(f"  Duration: {duration}s")
    print(_SEPARATORS)


def _print_layered_results(
    results: list[dict],
    scoring: dict[str, Any],
    layer_scores: dict[str, Any],
    duration: float,
) -> None:
    layers_data = layer_scores.get("layers", {})

    for layer_key, max_pts in scoring.items():
        max_points = float(max_pts)
        layer_info = layers_data.get(layer_key, {})
        earned = float(layer_info.get("score", 0))

        layer_name = _layer_display(layer_key)
        detail = layer_info.get("detail", "")
        print(f"\n  \u2500\u2500 {layer_name} ({earned}/{max_points:.0f}) \u2500" + "\u2500" * (40 - len(layer_name)))

        layer_checks = [
            r for r in results if r.get("layer") == layer_key
        ]
        for check in layer_checks:
            status = str(check.get("status", "unknown"))
            detail_text = check.get("detail", "")
            evidence = check.get("evidence", "")
            score_val = check.get("score")

            score_str = f" [{score_val}%]" if score_val is not None else ""
            print(f"  {_icon(status)} {detail_text}{score_str}")
            if evidence:
                for line in evidence.split("\n"):
                    print(f"     {line}")

        if detail:
            print(f"  ({detail})")

    total = layer_scores.get("total", 0)
    max_total = layer_scores.get("max", 0)
    pct = layer_scores.get("percentage", 0)

    print(f"\n  \u2500\u2500 \u603b\u5206: {total}/{max_total} ({pct}%) \u2500" + "\u2500" * 40)

    recommendations = _generate_recommendations(results)
    if recommendations:
        print(f"\n  \u5b9a\u4f4d\u5efa\u8bae:")
        for rec in recommendations:
            print(f"    \u2192 {rec}")

    print(f"\n  Duration: {duration}s")
    print(_SEPARATORS)


def _generate_recommendations(results: list[dict]) -> list[str]:
    recs: list[str] = []
    for r in results:
        if r["status"] != "fail":
            continue
        check_type = r.get("check_type", "")
        detail = str(r.get("detail", ""))
        evidence = str(r.get("evidence", ""))

        if "Missing" in detail and "field" in check_type.lower():
            recs.append(f"\u5b57\u6bb5\u7f3a\u5931: {detail}")
        elif "rpt_code" in detail:
            recs.append(f"CASE WHEN \u8986\u76d6\u4e0d\u5b8c\u6574: {detail} \u2192 \u68c0\u67e5 ETL CASE WHEN \u662f\u5426\u8986\u76d6\u6240\u6709 rpt_code")
        elif "del_flag" in detail:
            recs.append(f"del_flag \u8fc7\u6ee4\u7f3a\u5931: {detail} \u2192 \u68c0\u67e5 JOIN/WHERE \u4e2d del_flag \u8fc7\u6ee4")
        elif "JOIN table" in detail:
            recs.append(f"JOIN \u8868\u8986\u76d6\u4e0d\u5b8c\u6574: {detail} \u2192 \u68c0\u67e5 ETL \u662f\u5426\u5173\u8054\u4e86\u6240\u6709\u6765\u6e90\u8868")
        elif "ELSE" in detail:
            recs.append(f"CASE WHEN \u7f3a\u5c11 ELSE: {detail} \u2192 \u786e\u4fdd\u6240\u6709 CASE WHEN \u6709 ELSE \u5206\u652f")
        elif evidence and "Missing" in evidence:
            for line in evidence.split("\n"):
                if line.strip():
                    recs.append(line.strip())
                    break

    return recs[:8]


def generate_suite_summary(suite_results: list[dict[str, Any]]) -> None:
    print(_SEPARATORS)
    print("  Eval Suite Summary")
    print(_SEPARATORS)

    if not suite_results:
        print("  No cases evaluated.")
        print(_SEPARATORS)
        return

    name_col = max(len("Case"), max(len(str(r["case_name"])) for r in suite_results))
    name_col = min(name_col, 40)

    header = f"  {'Case':<{name_col}} | {'Score':^8} | {'Pass Rate':^10} | Status"
    print(header)
    divider = f"  {'-' * name_col}-+-{'-' * 8}-+-{'-' * 10}-+--------"
    print(divider)

    for r in suite_results:
        name = str(r["case_name"])[:name_col]
        rate = r.get("pass_rate", 0.0)
        rate_str = f"{rate * 100:.1f}%"
        score = r.get("total_score")
        score_str = f"{score}" if score else "-"
        status = str(r.get("status", "FAIL"))

        if status == "PASS":
            status_display = "\u2705 PASS"
        elif status == "SKIP":
            status_display = "\u26a0\ufe0f SKIP"
        else:
            status_display = "\u274c FAIL"

        print(f"  {name:<{name_col}} | {score_str:^8} | {rate_str:^10} | {status_display}")

    print(_SEPARATORS)
