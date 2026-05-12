# Current AI handoff state

This file is a compact handoff for future Codex runs. It is not a promise that bugs are fixed, and it must not replace inspecting the live repository.

## Before every patch

- Read `AGENTS.md` first for durable project rules.
- Read `docs/ai/repo-map.md` to find the likely files for the task.
- Inspect the live repo and relevant tests before editing; do **not** assume old repo state.
- Keep fixes narrow and diagnostics-backed.
- Real KDE Plasma 6 / Wayland testing with an actual Nanoleaf USB Edge Strip is still required for runtime confidence, especially for capture authorization, HID behavior, calibration output, lifecycle handling, and packaging/install flows.

## Known backlog, high level

The current backlog clusters around these areas:

1. HID/protocol/device reliability: enumeration, open-path behavior, write pacing, command framing, diagnostics, and graceful handling of permission/busy/device errors.
2. Config validation/loading: schema migration, defaults, manual LED/zone count authority, mode consistency, reset/init behavior, and user-facing validation messages.
3. Calibration and mapping: exclusive LED output during setup/test patterns, corner anchors, zone ordering, stale calibration detection, and preserving neutral/HDR color guardrails.
4. Runtime loop and lifecycle: Start/Stop semantics, output ownership, reinitialization paths, performance attribution, priority failure handling, and tray/service robustness.
5. Capture backends: `kwin-dbus` default behavior, shell-vs-desktop authorization diagnostics, `xdg-portal` fallback/manual benchmarking, probe cache clarity, and capture dimension handling.
6. Doctor/tooling: actionable output for capture/device/config problems, smoke-test accuracy, reset/autostart behavior, and concise troubleshooting guidance.
7. Packaging and CI: Arch/CachyOS install metadata, udev helper behavior, release/version checks, desktop-entry permissions, and keeping CI fast and representative.

## Recommended patch order

1. Reproduce or inspect diagnostics for the target problem; add/adjust the smallest failing test where practical.
2. Fix safety-critical lifecycle/output ownership issues before tuning or UX polish.
3. Address HID/device and capture authorization issues before assuming runtime-loop defects.
4. Fix config validation/migration issues before calibration or runtime code that depends on config shape.
5. Fix calibration/mapping correctness before color-style or performance tuning.
6. Improve doctor/smoke-test output after the underlying behavior and failure modes are understood.
7. Update packaging/CI last, unless the user request is specifically about install/release reliability.

## Verification expectations

- Prefer targeted tests for the touched component plus `git diff --check`.
- Run the CI-aligned commands from `AGENTS.md` when behavior changes or when touching shared runtime/config/capture code.
- For docs-only patches, lightweight markdown hygiene and `git diff --check` are enough unless the repo already has a markdown lint command configured.
- State clearly when verification is limited by lack of KDE/Wayland session or Nanoleaf hardware.
