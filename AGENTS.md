# AGENTS.md

## Project overview
Real-time screen mirroring to Nanoleaf Aurora/Lines/Canvas LED controllers over USB HID. KDE Plasma 6 + Wayland, PyQt6 system tray, kwin-DBUS capture backend. Single-device (one USB strip), not a generic LED controller platform.

This file defines durable repo rules for AI contributors. These rules apply regardless of which agent reads them.

## Workflow

This project uses a two-agent pipeline:

1. **opencode** (current session) — research, code comprehension, diagnostics analysis. Writes task specs to `.opencode/task-spec.md`. Does NOT write code directly.
2. **freebuff** (interactive TUI) — executes code changes from specs in `.opencode/task-spec.md`. OpenCode's `prompt-engineer` skill is used to craft token-efficient freebuff prompts.

The user copy-pastes the freebuff invocation snippet from the spec into freebuff's input.

## First reads

1. `AGENTS.md` for stable rules.
2. `docs/ai/current-state.md` for current backlog/order.
3. `docs/ai/repo-map.md` for where to patch and verify.
4. The relevant `.agents/skills/*/SKILL.md` for task-specific workflow reminders.

Always inspect the live repo before editing. Do not assume old repo state.

## Project operating rules

- Scope: one Nanoleaf USB Edge Strip only; keep single-device product assumptions.
- Manual LED/zone count is authoritative for runtime, mapping, setup, and calibration.
- Do **not** introduce multi-device architecture, a generic mapping engine, automatic LED-count detection/promotion, or a plugin framework.
- Do **not** perform architecture rewrites unless diagnostics clearly prove they are required.
- Environment assumptions: KDE Plasma 6 + Wayland on Arch/CachyOS-style setups.
- Capture backend policy: prefer `kwin-dbus`; treat `xdg-portal` as fallback/manual benchmark path unless diagnostics prove a better default.
- Do **not** add extra FPS control knobs; use existing Target capture/output FPS settings.
- Do **not** add extra priority settings; use existing `performance_priority` only.
- Do **not** use `SCHED_FIFO`/`SCHED_RR`; priority-setting failures must degrade gracefully and must not crash the app.
- **Stop** must stop mirroring while keeping the tray app running.
- Setup/calibration/manual test-pattern flows require exclusive LED output ownership.
- HDR/colour guardrails: neutral grey/white should remain neutral and visible; black should map to off; avoid global desaturation/averaging/smoothing hacks that break neutral handling.
- UI guardrails: keep normal Settings focused for daily use; put advanced/diagnostic tools in Advanced/Troubleshooting surfaces; Save/Apply applies changes and keeps Settings open.

## Delivery discipline

- opencode delivers: `.opencode/task-spec.md` with copy-paste-ready freebuff snippet, plus any research findings.
- freebuff delivers: working code changes with passing CI commands.
- Do not create planning-only docs when the prompt asks for implementation.
- Do not write code directly unless the user explicitly says so (light-coding skill).
- Do not claim an issue is fixed without tests or clearly stated verification limits.

## Validation commands

- `python -m pytest -q --timeout=60 --timeout-method=thread --durations=25`
- `python -m pytest -q --timeout=60 --timeout-method=thread --durations=25 --cov=nanoleaf_sync --cov-report=term-missing --cov-fail-under=70`
- `ruff check src/ tests/ --select E9,F63,F7,F82`
- `mypy src/nanoleaf_sync --ignore-missing-imports --follow-imports=silent`
- Documentation-only patches should at least run `git diff --check`.

## PR history

Use `docs/PR_HISTORY.md` for the local PR metadata index. If a PR title is unavailable from local metadata, do not infer beyond metadata.
