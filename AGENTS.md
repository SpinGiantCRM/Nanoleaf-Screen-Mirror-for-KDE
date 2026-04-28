# AGENTS.md

This file defines durable repo rules for Codex contributors so prompts do not need to repeat the same project context.

## Project operating rules (stable)

- Scope: one Nanoleaf USB Edge Strip only (single-device product assumptions).
- Manual LED/zone count is authoritative for runtime, mapping, setup, and calibration.
- Do **not** introduce multi-device architecture.
- Do **not** introduce a generic mapping engine.
- Do **not** add automatic LED-count detection/promotion.
- Do **not** add a plugin framework.
- Do **not** perform architecture rewrites unless diagnostics clearly prove they are required.
- Environment assumptions: KDE Plasma 6 + Wayland on Arch/CachyOS-style setups.
- Capture backend policy: prefer `kwin-dbus`; treat `xdg-portal` as fallback/manual benchmark path unless diagnostics prove a better default.
- Do **not** add extra FPS control knobs; use existing Target capture/output FPS settings.
- Do **not** add extra priority settings; use existing `performance_priority` only.
- Do **not** use `SCHED_FIFO`/`SCHED_RR` scheduling modes.
- Priority-setting failures must degrade gracefully and must not crash the app.
- **Stop** must stop mirroring while keeping the tray app running.
- Setup/calibration/manual test-pattern flows require exclusive LED output ownership.
- HDR/colour guardrails:
  - Neutral grey/white should remain neutral and visible.
  - Black should map to off.
  - Do **not** apply global desaturation/averaging/smoothing hacks that break neutral handling.
- UI guardrails:
  - Keep normal Settings focused and clean for daily use.
  - Put advanced/diagnostic tools in Advanced/Troubleshooting surfaces.
  - Save/Apply should apply changes and keep the Settings window open.

## Delivery discipline

- Do not create planning-only docs when the prompt asks for an implementation/fix.
- Implement the smallest concrete step instead.
- Only create plan docs when the user explicitly requests plan-only output.

## Validation commands (CI-aligned)

- `python -m pytest -q --timeout=60 --timeout-method=thread --durations=25`
- `python -m pytest -q --timeout=60 --timeout-method=thread --durations=25 --cov=nanoleaf_sync --cov-report=term-missing --cov-fail-under=70`
- `ruff check src/ tests/ --select E9,F63,F7,F82`
- `mypy src/nanoleaf_sync/tools/config_init.py src/nanoleaf_sync/tools/output_format.py --ignore-missing-imports --follow-imports=silent`

## PR history and lessons

Use this section for behavioral guidance. Keep entries compact; no long PR body copies.

### Focused implementation + tests (good)

- #316 — focused UI implementation — separates advanced from regular settings with targeted coverage — lesson: deliver requested UI behavior with concrete tests.
- #315 — focused UX/diagnostics fix — Save/apply behavior and formatter corrections with tests — lesson: small, precise fixes plus coverage are high-signal.
- #314 — lifecycle regression fix — Stop behavior preserves tray app lifecycle — lesson: protect runtime lifecycle invariants with regression tests.
- #313 — CI reliability fix — timeout/root-cause fix plus guardrails — lesson: stabilize CI by fixing root causes and adding prevention checks.
- #310 — regression recovery — fixes optimization regression from prior PR — lesson: fast rollback/fix path with explicit regression coverage is good practice.
- #308 — diagnostics-driven performance instrumentation — fixes runtime FPS attribution and visibility — lesson: instrument first, then optimize with evidence.

### Mixed/risky examples (use caution)

- #312 — mixed/risky — useful UI feature landed, but full test run did not complete in task context — lesson: targeted tests help, but full-suite confidence is preferred before merge.
- #311 — good optimization with caveat — HID write-path optimization and diagnostics improvements — lesson: performance wins should still be validated by full-suite/CI where practical.
- #309 — risky optimization change — performance-oriented controls caused a later regression — lesson: performance changes require fallback behavior and diagnostics-backed safety checks.

### Bad example (avoid by default)

- #317 — docs/planning deferral — planning-only menu revamp doc landed when implementation should have followed — lesson: avoid docs-only deferral unless user explicitly requests plan-only output.

### Exhaustive PR index

All PR numbers currently discoverable from local git merge metadata are indexed in one-line form at:

- `docs/PR_HISTORY.md`

If a PR title is unavailable from local metadata, do not infer beyond metadata.
