#!/usr/bin/env python3
"""
status_task.py

Prints the current state of a .worklogs/<task>/ workflow.
Does not edit files or run models.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def read_optional(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def first_section(text: str, max_chars: int = 1200) -> str:
    text = text.strip()
    if not text:
        return "(missing)"
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... truncated ..."


def extract_verdict(review: str) -> str:
    marker = "## Verdict"
    if marker not in review:
        return "(no verdict found)"
    after = review.split(marker, 1)[1].strip()
    return after.splitlines()[0].strip() if after else "(empty verdict)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", help="Worklog task name, e.g. test-issue")
    args = parser.parse_args()

    worklog = Path.cwd() / ".worklogs" / args.task

    files = {
        "repro": worklog / "repro.md",
        "codex_prompt": worklog / "codex-prompt.md",
        "codex_output": worklog / "codex-output.md",
        "local_review": worklog / "local-review.md",
        "followup_prompt": worklog / "followup-prompt.md",
    }

    print(f"# Task status: {args.task}")
    print(f"Worklog: {worklog}")
    print()

    for name, path in files.items():
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        print(f"- {name}: {'yes' if exists else 'no'} ({size} bytes)")

    print()

    review = read_optional(files["local_review"])
    print(f"Verdict: {extract_verdict(review)}")
    print()

    if files["followup_prompt"].exists():
        print("Follow-up prompt: yes")
    else:
        print("Follow-up prompt: no")

    print("\n## Repro preview")
    print(first_section(read_optional(files["repro"])))

    print("\n## Local review preview")
    print(first_section(review))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
