"""Evaluation runner — main entry point for running ETL eval cases.

Usage:
    python eval-suite/runner.py validate --case cases/001_商品中心宽表 --output docs/output/商品中心宽表/
    python eval-suite/runner.py run-all --cases-dir eval-suite/cases/ --output-base docs/output/
    python eval-suite/runner.py execute --case eval-suite/cases/001_商品中心宽表 --output docs/output/商品中心宽表/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

# Ensure eval-suite/ is on sys.path so validators can be imported
EVAL_SUITE_DIR = Path(__file__).resolve().parent
if str(EVAL_SUITE_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_SUITE_DIR))

from validators import (
    ArtifactValidator,
    DesignValidator,
    GoldenDiffValidator,
    SQLValidator,
    ExportValidator,
    ReviewValidator,
    ContentValidator,
)

from report import generate_case_report, generate_suite_summary

from opencode_client import OpenCodeClient

# ---------------------------------------------------------------------------
# Check status constants
# ---------------------------------------------------------------------------
PASS = "pass"
FAIL = "fail"
SKIP = "skip"

# ---------------------------------------------------------------------------
# Validator dispatch table
# ---------------------------------------------------------------------------
VALIDATORS: dict[str, type] = {
    "files_exist": ArtifactValidator,
    "design_structure": DesignValidator,
    "field_mapping_match": DesignValidator,
    "audit_fields_present": DesignValidator,
    "segment_strategy": DesignValidator,
    "ddl_structure": SQLValidator,
    "ddl_columns_match": SQLValidator,
    "etl_structure": SQLValidator,
    "ddl_etl_consistency": SQLValidator,
    "comment_style": SQLValidator,
    "field_completeness": ContentValidator,
    "etl_logic": ContentValidator,
    "safety": ContentValidator,
    "review_format": ReviewValidator,
    "review_conclusion": ReviewValidator,
    "review_mentions": ReviewValidator,
    "export_files_exist": ExportValidator,
    "export_sheets": ExportValidator,
    "golden_structure_match": GoldenDiffValidator,
}


def _compute_layer_scores(
    check_results: list[dict[str, object]],
    scoring: dict[str, object],
) -> dict[str, object]:
    """Compute per-layer scores from check results and scoring config."""
    layer_scores: dict[str, dict[str, object]] = {}

    for layer_name, max_points in scoring.items():
        max_pts = float(max_points)
        layer_checks = [
            r for r in check_results if r.get("layer") == layer_name
        ]
        if not layer_checks:
            layer_scores[layer_name] = {
                "score": max_pts,
                "max": max_pts,
                "detail": "no checks in layer",
            }
            continue

        scored = [r for r in layer_checks if "score" in r]
        if scored:
            avg_score = sum(float(r["score"]) for r in scored) / len(scored)
            earned = round(max_pts * avg_score / 100, 1)
        else:
            passed_n = sum(1 for r in layer_checks if r["status"] == PASS)
            total_n = len(layer_checks)
            avg_rate = passed_n / total_n if total_n else 1.0
            earned = round(max_pts * avg_rate, 1)

        layer_scores[layer_name] = {
            "score": earned,
            "max": max_pts,
        }

    total_score = sum(
        float(v["score"]) for v in layer_scores.values()
    )
    total_max = sum(
        float(v["max"]) for v in layer_scores.values()
    )
    return {
        "layers": layer_scores,
        "total": round(total_score, 1),
        "max": round(total_max, 1),
        "percentage": round(total_score / total_max * 100, 1) if total_max else 0,
    }


def run_single_case(
    case_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Run all checks for a single eval case.

    Args:
        case_dir: Path to the case directory containing expectations.json.
        output_dir: Absolute path to the actual output directory.

    Returns:
        Dict containing case results and metadata.
    """
    expectations_path = case_dir / "expectations.json"
    if not expectations_path.exists():
        return {
            "case_name": case_dir.name,
            "scope": "unknown",
            "error": f"expectations.json not found in {case_dir}",
            "total_checks": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "pass_rate": 0.0,
            "results": [],
            "duration_seconds": 0.0,
        }

    with open(expectations_path, encoding="utf-8") as f:
        expectations = json.load(f)

    case_name = expectations.get("name", case_dir.name)
    scope = expectations.get("scope", "unknown")
    checks = expectations.get("checks", [])
    case_golden_dir = expectations.get("golden_dir", "")

    start_time = time.monotonic()
    check_results: list[dict[str, object]] = []

    for check in checks:
        check_type = check.get("type", "")
        check_layer = check.get("layer", "")
        validator_cls = VALIDATORS.get(check_type)

        if validator_cls is None:
            check_results.append({
                "check_type": check_type,
                "status": SKIP,
                "detail": f"Unknown check type: {check_type}",
                "evidence": "",
                "layer": check_layer,
            })
            continue

        try:
            validator = validator_cls()
            golden_dir = None
            check_golden = check.get("golden_dir", case_golden_dir)
            if check_golden:
                golden_dir = EVAL_SUITE_DIR / check_golden

            result = validator.validate(
                output_dir=output_dir,
                golden_dir=golden_dir,
                check_config=check,
            )

            if isinstance(result, list):
                check_results_list = result
            else:
                check_results_list = [result]

            for cr in check_results_list:
                if hasattr(cr, "to_dict"):
                    cr_dict = cr.to_dict()
                elif isinstance(cr, dict):
                    cr_dict = cr
                else:
                    cr_dict = {
                        "check_type": check_type,
                        "status": SKIP,
                        "detail": f"Unexpected result type: {type(cr)}",
                        "evidence": "",
                    }
                if not cr_dict.get("check_type"):
                    cr_dict["check_type"] = check_type
                cr_dict["layer"] = check_layer
                check_results.append(cr_dict)
        except FileNotFoundError as exc:
            check_results.append({
                "check_type": check_type,
                "status": SKIP,
                "detail": f"File not found: {exc}",
                "evidence": "",
                "layer": check_layer,
            })
        except Exception as exc:  # noqa: BLE001 — keep running other checks
            check_results.append({
                "check_type": check_type,
                "status": FAIL,
                "detail": f"Validator error: {exc}",
                "evidence": "",
                "layer": check_layer,
            })

    duration = time.monotonic() - start_time

    passed = sum(1 for r in check_results if r["status"] == PASS)
    failed = sum(1 for r in check_results if r["status"] == FAIL)
    skipped = sum(1 for r in check_results if r["status"] == SKIP)
    total = len(check_results)
    pass_rate = passed / total if total > 0 else 0.0

    scoring = expectations.get("scoring", {})
    layer_scores = _compute_layer_scores(check_results, scoring)

    return {
        "case_name": case_name,
        "scope": scope,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_checks": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": round(pass_rate, 4),
        "results": check_results,
        "scoring": scoring,
        "layer_scores": layer_scores,
        "duration_seconds": round(duration, 2),
    }


def save_result(results_dir: Path, case_result: dict[str, Any]) -> None:
    """Save case result to results/{case_name}/result.json.

    Args:
        results_dir: Base results directory (eval-suite/results/).
        case_result: The case result dict from run_single_case.
    """
    # Sanitize case name for use as directory
    safe_name = case_result["case_name"].replace("/", "_").replace(" ", "_")
    case_result_dir = results_dir / safe_name
    case_result_dir.mkdir(parents=True, exist_ok=True)

    result_path = case_result_dir / "result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(case_result, f, ensure_ascii=False, indent=2)


def find_cases(cases_dir: Path) -> list[Path]:
    """Discover all case directories containing expectations.json.

    Args:
        cases_dir: Base directory to scan.

    Returns:
        List of case directory paths, sorted by name.
    """
    cases: list[Path] = []
    if not cases_dir.exists():
        return cases

    for child in sorted(cases_dir.iterdir()):
        if child.is_dir() and (child / "expectations.json").exists():
            cases.append(child)
        # Also check one level deeper (e.g., skills/coder/001_xxx)
        elif child.is_dir():
            for grandchild in sorted(child.iterdir()):
                if grandchild.is_dir() and (grandchild / "expectations.json").exists():
                    cases.append(grandchild)

    return cases


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a single case against its expectations."""
    case_dir = Path(args.case).resolve()
    output_dir = Path(args.output).resolve()

    if not case_dir.exists():
        print(f"Error: Case directory not found: {case_dir}", file=sys.stderr)
        return 1

    if not output_dir.exists():
        print(f"Error: Output directory not found: {output_dir}", file=sys.stderr)
        return 1

    results_dir = EVAL_SUITE_DIR / "results"

    result = run_single_case(case_dir, output_dir)
    save_result(results_dir, result)
    generate_case_report(result)

    return 0 if result["failed"] == 0 else 1


def cmd_run_all(args: argparse.Namespace) -> int:
    """Scan and validate all cases found in cases_dir."""
    cases_dir = Path(args.cases_dir).resolve()
    output_base = Path(args.output_base).resolve()

    cases = find_cases(cases_dir)
    if not cases:
        print(f"No cases found in {cases_dir}", file=sys.stderr)
        return 1

    results_dir = EVAL_SUITE_DIR / "results"
    all_results: list[dict[str, Any]] = []

    for case_dir in cases:
        case_name = case_dir.name
        print(f"\n{'=' * 60}")
        print(f"  Case: {case_name}")

        # Try to derive output dir from case name or use output_base
        output_dir = output_base / case_name

        if not output_dir.exists():
            print(f"  Output directory not found: {output_dir}")
            print(f"  Run the case manually first, then validate.")
            print(f"  Command: cd {EVAL_SUITE_DIR.parent} && opencode")
            print(f"  Prompt: (see {case_dir}/expectations.json)")
            all_results.append({
                "case_name": case_name,
                "scope": "unknown",
                "total_checks": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "pass_rate": 0.0,
                "status": "SKIP",
            })
            continue

        result = run_single_case(case_dir, output_dir)
        save_result(results_dir, result)
        generate_case_report(result)

        all_results.append({
            "case_name": result["case_name"],
            "scope": result["scope"],
            "total_checks": result["total_checks"],
            "passed": result["passed"],
            "failed": result["failed"],
            "skipped": result["skipped"],
            "pass_rate": result["pass_rate"],
            "status": "PASS" if result["failed"] == 0 else "FAIL",
        })

    print()
    generate_suite_summary(all_results)

    failed_count = sum(1 for r in all_results if r["status"] == "FAIL")
    return 1 if failed_count > 0 else 0


# Command scopes that map to slash commands (sent via send_command)
COMMAND_SCOPES = {"ulw-pipe", "design"}


def resolve_prompt(prompt: str, case_dir: Path) -> str:
    """Replace @filename references in prompt with absolute paths.

    Finds patterns like @input.xlsx or @subdir/file.xlsx and resolves
    them relative to case_dir.
    """
    def _replace(match: re.Match[str]) -> str:
        filename = match.group(1)
        resolved = (case_dir / filename).resolve()
        return f"@{resolved}"

    return re.sub(r"@([^\s]+)", _replace, prompt)


def cmd_execute(args: argparse.Namespace) -> int:
    """Execute a case by calling OpenCode, then validate the output."""
    case_dir = Path(args.case).resolve()
    output_dir = Path(args.output).resolve()
    workdir = Path(args.workdir).resolve() if args.workdir else EVAL_SUITE_DIR.parent
    timeout = args.timeout
    auto_confirm = args.auto_confirm

    # 1. Read expectations.json
    expectations_path = case_dir / "expectations.json"
    if not expectations_path.exists():
        print(f"Error: expectations.json not found in {case_dir}", file=sys.stderr)
        return 1

    with open(expectations_path, encoding="utf-8") as f:
        expectations = json.load(f)

    case_name = expectations.get("name", case_dir.name)
    scope = expectations.get("scope", "unknown")
    prompt = expectations.get("prompt", "")

    if not prompt:
        print(f"Error: No 'prompt' field in {expectations_path}", file=sys.stderr)
        return 1

    # 2. Resolve @file references in prompt
    prompt = resolve_prompt(prompt, case_dir)

    print(f"[eval] Case: {case_name}")
    print(f"[eval] Scope: {scope}")
    print(f"[eval] Workdir: {workdir}")
    print(f"[eval] Output: {output_dir}")
    print()

    # 3. Clean existing output
    if not args.skip_execute and output_dir.exists():
        print(f"[eval] Cleaning existing output: {output_dir}")
        shutil.rmtree(output_dir, ignore_errors=True)

    # 4. Skip execution if requested
    if not args.skip_execute:
        client = OpenCodeClient()

        # 4. Check sidecar health
        print("[eval] Checking sidecar health...")
        if not client.health_check():
            print(
                "Error: OpenCode sidecar is not running.\n"
                "  Start it via the desktop app or: opencode serve\n"
                "  Then re-run this command.",
                file=sys.stderr,
            )
            return 1
        print("[eval] Sidecar is healthy ✓")

        # 5. Create session
        print(f"[eval] Creating session...")
        try:
            session_id = client.create_session(
                title=f"Eval: {case_name}",
                directory=str(workdir),
            )
        except Exception as exc:
            print(f"Error: Failed to create session: {exc}", file=sys.stderr)
            return 1
        print(f"[eval] Session created: {session_id}")

        # 6. Send prompt/command with AUTO_CONFIRM
        if auto_confirm:
            os.environ["AUTO_CONFIRM"] = "true"

        try:
            if scope in COMMAND_SCOPES:
                full_prompt = f"/{scope} {prompt}"
                print(f"[eval] Sending prompt: /{scope} ...")
                client.send_prompt_async(
                    session_id=session_id,
                    content=full_prompt,
                    directory=str(workdir),
                )
            else:
                print(f"[eval] Sending prompt...")
                client.send_prompt_async(
                    session_id=session_id,
                    content=prompt,
                    directory=str(workdir),
                )
        except Exception as exc:
            print(f"Error: Failed to send prompt/command: {exc}", file=sys.stderr)
            client.delete_session(session_id)
            return 1

        # 7. Poll for completion
        print(f"[eval] Waiting for completion (timeout: {timeout}s)...")
        completed = client.wait_for_completion(
            session_id=session_id,
            timeout=timeout,
            directory=str(workdir),
        )
        elapsed = int(time.time() - time.monotonic()) if not completed else 0
        if completed:
            print(f"[eval] Session completed ✓")
        else:
            print(f"[eval] Session did not complete within timeout — proceeding to validation")

    # 8. Validate output (reuse existing logic)
    print()
    print("[eval] Running validation...")
    result = run_single_case(case_dir, output_dir)

    results_dir = EVAL_SUITE_DIR / "results"
    save_result(results_dir, result)
    generate_case_report(result)

    return 0 if result["failed"] == 0 else 1


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="ETL evaluation suite runner",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate sub-command
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a single case against expectations",
    )
    validate_parser.add_argument(
        "--case",
        required=True,
        help="Path to case directory (containing expectations.json)",
    )
    validate_parser.add_argument(
        "--output",
        required=True,
        help="Absolute path to the actual output directory",
    )

    # run-all sub-command
    run_all_parser = subparsers.add_parser(
        "run-all",
        help="Scan and validate all cases",
    )
    run_all_parser.add_argument(
        "--cases-dir",
        required=True,
        help="Base directory containing case subdirectories",
    )
    run_all_parser.add_argument(
        "--output-base",
        required=True,
        help="Base output directory (case subdirs expected underneath)",
    )

    # execute sub-command
    execute_parser = subparsers.add_parser(
        "execute",
        help="Execute a case via OpenCode then validate output",
    )
    execute_parser.add_argument(
        "--case",
        required=True,
        help="Path to case directory (containing expectations.json)",
    )
    execute_parser.add_argument(
        "--output",
        required=True,
        help="Absolute path to the output directory",
    )
    execute_parser.add_argument(
        "--workdir",
        default=None,
        help="Working directory for OpenCode (default: project root)",
    )
    execute_parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Max wait time for OpenCode completion in seconds (default: 1800)",
    )
    execute_parser.add_argument(
        "--auto-confirm",
        action="store_true",
        default=True,
        help="Set AUTO_CONFIRM=true env var (default: true for execute mode)",
    )
    execute_parser.add_argument(
        "--no-auto-confirm",
        dest="auto_confirm",
        action="store_false",
        help="Do not set AUTO_CONFIRM env var",
    )
    execute_parser.add_argument(
        "--skip-execute",
        action="store_true",
        default=False,
        help="Skip OpenCode execution, only validate (useful when already run)",
    )

    args = parser.parse_args()

    if args.command == "validate":
        return cmd_validate(args)
    elif args.command == "run-all":
        return cmd_run_all(args)
    elif args.command == "execute":
        return cmd_execute(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
