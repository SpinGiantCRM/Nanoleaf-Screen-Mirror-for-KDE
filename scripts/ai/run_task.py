#!/usr/bin/env python3
"""
run_task.py

Runs the safe local AI → Codex → local review workflow for a worklog task.

Default mode:
- generate Codex prompt
- run Codex in read-only mode
- review Codex output
- show task status

This does not edit source code unless --sandbox workspace-write is explicitly used.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_step(label: str, cmd: list[str]) -> int:
    print()
    print("=" * 80)
    print(f"STEP: {label}")
    print("=" * 80)
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        print()
        print(f"FAILED: {label} exited with code {result.returncode}", file=sys.stderr)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", help="Worklog task name, e.g. test-issue")
    parser.add_argument(
        "--sandbox",
        default="read-only",
        choices=["read-only", "workspace-write"],
        help="Codex sandbox mode. Default: read-only.",
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    worklog = repo_root / ".worklogs" / args.task
    repro = worklog / "repro.md"

    if not repro.exists():
        print(f"ERROR: Missing {repro}", file=sys.stderr)
        return 1

    codex_mode = "implementation" if args.sandbox == "workspace-write" else "read-only"

    steps = [
        (
            "Generate Codex prompt with local model",
            ["python", "scripts/ai/make_codex_prompt.py", args.task],
        ),
        (
            f"Run Codex with sandbox={args.sandbox}",
            ["python", "scripts/ai/run_codex_prompt.py", args.task, "--sandbox", args.sandbox],
        ),
        (
            f"Review Codex output with local model, codex-mode={codex_mode}",
            [
                "python",
                "scripts/ai/review_codex_output.py",
                args.task,
                "--codex-mode",
                codex_mode,
            ],
        ),
        (
            "Show task status",
            ["python", "scripts/ai/status_task.py", args.task],
        ),
    ]

    for label, cmd in steps:
        code = run_step(label, cmd)
        if code != 0:
            return code

    print()
    print("=" * 80)
    print("Workflow complete.")
    print("=" * 80)
    print(f"Worklog: {worklog}")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
