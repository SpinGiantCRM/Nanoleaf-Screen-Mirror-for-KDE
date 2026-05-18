#!/usr/bin/env python3
"""
make_codex_prompt.py

Reads a worklog issue file, asks the local Ollama model to create a Codex-ready
implementation prompt, and writes it to .worklogs/<task>/codex-prompt.md.

This does not edit project source code.
This does not run Codex.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_MODEL = "qwen3-coder-30b-a3b-goose-4k"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return path.read_text(encoding="utf-8")


def call_ollama(model: str, prompt: str) -> str:
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a local code-quality controller for a Codex workflow. "
                    "You are not the implementation agent. Your job is to turn the user's "
                    "issue report into a precise Codex task. Be strict, specific, and concise. "
                    "Do not invent evidence. If information is missing, tell Codex what to inspect "
                    "or what to reproduce."
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
            "Check that `systemctl status ollama` is active."
        ) from exc

    result = json.loads(raw)
    return result["message"]["content"].strip()


def build_controller_prompt(task_name: str, repro_md: str, agents_md: str | None) -> str:
    agents_section = agents_md if agents_md else "No AGENTS.md was found."

    return f"""
Create a Codex-ready prompt for this repo task.

Task name:
{task_name}

Issue report:
---
{repro_md}
---

Repo instructions, if available:
---
{agents_section}
---

Write a prompt for Codex that includes:
1. The problem summary.
2. Expected behaviour.
3. Actual behaviour.
4. Reproduction-first instruction.
5. The likely areas Codex should inspect, but mark them as hypotheses.
6. Specific tests Codex should add or update.
7. Explicit constraints:
   - make the smallest safe change
   - preserve existing behaviour unless directly related
   - do not rewrite unrelated systems
   - do not fake passing tests
   - run relevant checks
8. Required final output from Codex:
   - summary of changes
   - tests/checks run
   - remaining risks
   - manual smoke-test checklist

Return only the Codex prompt. Do not wrap it in markdown fences.
""".strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", help="Worklog task name, e.g. test-issue")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model to use. Default: {DEFAULT_MODEL}",
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    worklog_dir = repo_root / ".worklogs" / args.task
    repro_path = worklog_dir / "repro.md"
    output_path = worklog_dir / "codex-prompt.md"
    agents_path = repo_root / "AGENTS.md"

    try:
        repro_md = read_text(repro_path)
        agents_md = read_text(agents_path) if agents_path.exists() else None
        prompt = build_controller_prompt(args.task, repro_md, agents_md)
        codex_prompt = call_ollama(args.model, prompt)

        output_path.write_text(codex_prompt + "\n", encoding="utf-8")

        print(f"Wrote: {output_path}")
        print()
        print("Preview:")
        print("-" * 60)
        print(codex_prompt[:2000])
        if len(codex_prompt) > 2000:
            print("\n... preview truncated ...")
        print("-" * 60)
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
