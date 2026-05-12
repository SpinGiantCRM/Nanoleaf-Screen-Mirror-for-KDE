# code-audit

## Description

Use this skill for inspection-only or diagnostics-first tasks that identify likely defects, stale docs, risky assumptions, or verification gaps.

## When to use it

- The prompt asks to audit, inspect, triage, compare behavior, or prepare a fix backlog.
- The next implementation step is unclear without reading code/tests/docs.
- The task needs a concise handoff rather than a runtime change.

## Constraints

- Prefer source, tests, and existing docs over assumptions.
- Do not infer PR details beyond local metadata.
- Do not turn AGENTS.md into a large bug list.
- Separate confirmed facts from hypotheses.
- Avoid touching application code unless the prompt explicitly asks for implementation.

## Verification expectations

- Cite inspected files in the final response when answering questions.
- Run `git diff --check` if documentation files changed.
- Note any missing hardware/session verification.
