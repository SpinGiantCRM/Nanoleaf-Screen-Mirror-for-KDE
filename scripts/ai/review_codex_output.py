#!/usr/bin/env python3
"""
review_codex_output.py

Reads a worklog issue, Codex prompt, and Codex output.
Asks the local Ollama model to review whether Codex handled the task properly.
Writes:
- .worklogs/<task>/local-review.md
- .worklogs/<task>/followup-prompt.md, if another Codex pass is recommended

This does not edit project source code.
This does not run Codex.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_MODEL = "qwen3-coder-30b-a3b-goose-4k"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
CODEX_MODES = ("read-only", "implementation")


def read_optional(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        return result.stdout.strip()
    except Exception as exc:
        return f"Could not run git {' '.join(args)}: {exc}"


def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    head = text[: max_chars // 3]
    tail = text[-(max_chars * 2 // 3) :]
    return (
        head
        + "\n\n...[middle omitted to fit local model context]...\n\n"
        + tail
    )


def call_ollama(model: str, prompt: str) -> str:
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a strict local quality reviewer for a Codex workflow. "
                    "You do not write code. You judge whether Codex handled the task well, "
                    "whether it followed constraints, whether tests/checks are missing, "
                    "and whether another Codex pass is needed. Be concise, specific, "
                    "and sceptical. Do not invent facts."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "options": {
            "temperature": 0.2,
            "top_p": 0.8,
            "num_ctx": 4096,
        },
    }

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Could not reach Ollama at http://localhost:11434. "
            "Check that Ollama is running."
        ) from exc

    result = json.loads(raw)
    return result["message"]["content"].strip()


def build_review_prompt(
    task: str,
    codex_mode: str,
    repro: str,
    codex_prompt: str,
    codex_output: str,
    git_status: str,
    git_diff_stat: str,
) -> str:
    codex_output = trim_text(codex_output, 12000)

    return f"""
Review this Codex workflow result.

Task:
{task}

Codex mode:
{codex_mode}

Mode rules:
- If Codex mode is read-only, Codex was not allowed to edit files.
- In read-only mode, no git diff is expected.
- In read-only mode, do not fail the run only because no files changed.
- In read-only mode, judge whether Codex produced a useful implementation plan.
- In read-only mode, if the issue has enough evidence and Codex produced a useful plan, verdict must be needs_implementation_pass.
- In read-only mode, if more logs, screenshots, reproduction steps, or environment details are needed before implementation, verdict must be needs_user_evidence.
- If Codex mode is implementation, Codex was expected to make focused code changes and run/update relevant checks where practical.
- In implementation mode, if no relevant files changed, verdict should usually be failed or needs_another_codex_pass.
- Implementation mode should only be approved if the diff is focused, relevant, safe, and credibly checked.

Original issue:
---
{repro}
---

Prompt sent to Codex:
---
{codex_prompt}
---

Current git status:
---
{git_status}
---

Current git diff stat:
---
{git_diff_stat}
---

Codex output, trimmed if needed:
---
{codex_output}
---

You must judge whether Codex handled the task correctly.

Return the review in this exact structure:

# Local Review

## Verdict
Choose one:
- approve
- needs_implementation_pass
- needs_another_codex_pass
- needs_user_evidence
- failed

## Reason
Briefly explain the verdict.

## Problems Found
List concrete issues, or write "None found".

## Missing Tests Or Checks
List missing tests/checks, or write "None found".

## Follow-up Codex Prompt
If verdict is needs_implementation_pass, write the exact implementation-mode prompt to send Codex next.
If verdict is needs_another_codex_pass, write the exact corrective prompt to send Codex next.
If not needed, write "None".

Follow-up prompt requirements:
- Make clear whether the next pass is implementation or corrective implementation.
- Keep the task focused.
- Tell Codex to only change files needed for this task.
- Tell Codex to avoid broad refactors.
- Tell Codex to add/update tests where practical.
- Tell Codex to run relevant checks where practical.
- Tell Codex to summarise changed files, risks, and manual smoke tests.

## Manual Smoke Test Checklist
List what Chase should manually test on the real CachyOS/KDE/Wayland/Nanoleaf setup.
""".strip()


def extract_followup(review: str) -> str:
    marker = "## Follow-up Codex Prompt"
    if marker not in review:
        return ""

    section = review.split(marker, 1)[1]
    next_marker = "\n## "
    if next_marker in section:
        section = section.split(next_marker, 1)[0]

    followup = section.strip()
    if followup.lower() in {"none", "none."}:
        return ""

    return followup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", help="Worklog task name, e.g. test-issue")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model to use. Default: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--codex-mode",
        choices=CODEX_MODES,
        default="read-only",
        help=(
            "How Codex was run. read-only means planning/review only; "
            "implementation means edits were expected."
        ),
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    worklog_dir = repo_root / ".worklogs" / args.task

    repro_path = worklog_dir / "repro.md"
    prompt_path = worklog_dir / "codex-prompt.md"
    codex_output_path = worklog_dir / "codex-output.md"
    review_path = worklog_dir / "local-review.md"
    followup_path = worklog_dir / "followup-prompt.md"

    if not repro_path.exists():
        print(f"ERROR: Missing {repro_path}", file=sys.stderr)
        return 1
    if not prompt_path.exists():
        print(f"ERROR: Missing {prompt_path}", file=sys.stderr)
        return 1
    if not codex_output_path.exists():
        print(f"ERROR: Missing {codex_output_path}", file=sys.stderr)
        return 1

    repro = read_optional(repro_path)
    codex_prompt = read_optional(prompt_path)
    codex_output = read_optional(codex_output_path)

    git_status = run_git(["status", "--short"])
    git_diff_stat = run_git(["diff", "--stat"])

    review_prompt = build_review_prompt(
        task=args.task,
        codex_mode=args.codex_mode,
        repro=repro,
        codex_prompt=codex_prompt,
        codex_output=codex_output,
        git_status=git_status,
        git_diff_stat=git_diff_stat,
    )

    try:
        review = call_ollama(args.model, review_prompt)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    review_path.write_text(review + "\n", encoding="utf-8")

    followup = extract_followup(review)
    if followup:
        followup_path.write_text(followup + "\n", encoding="utf-8")
    elif followup_path.exists():
        followup_path.unlink()

    print(f"Wrote: {review_path}")
    print(f"Codex mode: {args.codex_mode}")
    if followup:
        print(f"Wrote: {followup_path}")
    else:
        print("No follow-up prompt generated.")

    print()
    print(review)

    return 0



if __name__ == "__main__":
    raise SystemExit(main())
