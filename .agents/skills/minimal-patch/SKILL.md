# minimal-patch

## Description

Use this skill whenever the requested task is a focused bug fix, cleanup, or documentation update that should avoid broad refactors.

## When to use it

- The prompt asks for a specific implementation/fix.
- The affected area is known or can be isolated with targeted tests.
- A docs-only or narrow behavior patch is sufficient.

## Constraints

- Inspect the live repo before editing; do not assume old state.
- Avoid architecture rewrites and unrelated cleanup.
- Do not create planning-only docs unless explicitly requested.
- Do not claim issues are fixed without verification or a clearly stated limitation.
- Keep AGENTS.md concise and put changing context in `docs/ai/`.

## Verification expectations

- Run `git diff --check` for every patch.
- Run the smallest relevant tests/checks for touched files.
- For docs-only changes, use existing markdown checks only if configured.
