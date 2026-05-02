#!/usr/bin/env python3
"""
run_codex_prompt.py

Reads .worklogs/<task>/codex-prompt.md and sends it to Codex CLI.
Default mode is read-only for safety.
Writes Codex output to .worklogs/<task>/codex-output.md.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


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
    worklog_dir = repo_root / ".worklogs" / args.task
    prompt_path = worklog_dir / "codex-prompt.md"
    output_path = worklog_dir / "codex-output.md"

    if not prompt_path.exists():
        print(f"ERROR: Missing prompt file: {prompt_path}", file=sys.stderr)
        return 1

    prompt = prompt_path.read_text(encoding="utf-8")

    if args.sandbox == "read-only":
        prompt = (
            prompt
            + "\n\nSAFETY MODE: Do not edit files. Summarize the task and explain what you would do."
        )

    cmd = [
        "codex",
        "exec",
        "--sandbox",
        args.sandbox,
        prompt,
    ]

    print(f"Running Codex with sandbox={args.sandbox}")
    print(f"Prompt: {prompt_path}")
    print(f"Output: {output_path}")
    print()

    result = subprocess.run(
        cmd,
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    output_path.write_text(result.stdout, encoding="utf-8")

    print(result.stdout)
    print()
    print(f"Wrote: {output_path}")

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
