#!/usr/bin/env python3
"""DWS ETL cross-platform skill runner.

Usage:
    dws-run <skill> <action> [args...]

Actions:
    dws-run designer excel_parser --input file.xlsx       Execute a script
    dws-run designer read references/best-practices.md    Print file contents
    dws-run designer path                                 Print skill directory

Skill short names:
    designer         dws-pipeline-designer
    coder            dws-pipeline-coder
    reviewer         dws-pipeline-reviewer
    code-reviewer    dws-pipeline-code-reviewer
    tester           dws-pipeline-tester
    exporter         dws-pipeline-exporter
    analyzer         dws-pipeline-sql-analyzer
    shared           dws-pipeline-shared
    optimizer        dws-pipeline-optimizer
    optimizer-coder  dws-pipeline-optimizer-coder
"""

import sys
import subprocess
from pathlib import Path


SKILL_MAP = {
    "designer": "dws-pipeline-designer",
    "coder": "dws-pipeline-coder",
    "reviewer": "dws-pipeline-reviewer",
    "code-reviewer": "dws-pipeline-code-reviewer",
    "tester": "dws-pipeline-tester",
    "exporter": "dws-pipeline-exporter",
    "analyzer": "dws-pipeline-sql-analyzer",
    "shared": "dws-pipeline-shared",
    "optimizer": "dws-pipeline-optimizer",
    "optimizer-coder": "dws-pipeline-optimizer-coder",
}

SPECIAL_COMMANDS = {"read", "path", "help"}


def skill_dir(skill_short: str) -> Path:
    full_name = SKILL_MAP.get(skill_short, skill_short)
    if not full_name.startswith("dws-pipeline-"):
        full_name = f"dws-pipeline-{full_name}"
    return Path.home() / ".config" / "opencode" / "skills" / full_name


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: dws-run <skill> <action> [args...]\n"
            "Actions: <script_name> | read <path> | path | help",
            file=sys.stderr,
        )
        sys.exit(1)

    skill_short = sys.argv[1]
    action = sys.argv[2]
    args = sys.argv[3:]

    sdir = skill_dir(skill_short)

    # --- path: print skill directory ---
    if action == "path":
        if not sdir.exists():
            print(f"Error: skill directory not found: {sdir}", file=sys.stderr)
            sys.exit(1)
        print(sdir)
        return

    # --- help: list available scripts ---
    if action == "help":
        if not sdir.exists():
            print(f"Error: skill directory not found: {sdir}", file=sys.stderr)
            sys.exit(1)
        refs = sdir / "references"
        print(f"Skill: {skill_short} -> {sdir}")
        print("Available scripts in references/:")
        if refs.exists():
            for f in sorted(refs.glob("*.py")):
                print(f"  {f.stem}")
        else:
            print("  (no references directory)")
        return

    # --- read: print file contents ---
    if action == "read":
        if not args:
            print("Usage: dws-run <skill> read <relative-path>", file=sys.stderr)
            sys.exit(1)
        file_path = sdir / args[0]
        if not file_path.exists():
            print(f"Error: file not found: {file_path}", file=sys.stderr)
            sys.exit(1)
        try:
            content = file_path.read_text(encoding="utf-8")
            print(content, end="")
        except Exception as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # --- default: execute a script via run.py ---
    run_py = sdir / "run.py"
    if not run_py.exists():
        print(f"Error: {run_py} not found", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run([sys.executable, str(run_py), action] + args)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
