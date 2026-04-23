# Auto Backend Selection

This document describes how backend auto-selection should be interpreted during smoke and release testing.

## Effective backend decision model

When `prefer_backend=auto`, runtime selects a backend using:

1. explicit configuration overrides (if set), then
2. cached probe winner (when valid for current signature), then
3. fresh probe results, then
4. fallback backend when probe is unavailable.

## Selection reason values

Expected values in tooling output:

- `explicit`
- `cached-probe`
- `fresh-probe`
- `fallback`

## Operational guidance

- Use `nanoleaf-kde-sync-doctor --capture` when `fallback` appears unexpectedly.
- Use smoke tests to confirm one-frame capture before long sessions.
- Record backend decisions in RC evidence when behavior differs across environments.

## Related docs

- `docs/SMOKE_TEST.md`
- `docs/TROUBLESHOOTING.md`
