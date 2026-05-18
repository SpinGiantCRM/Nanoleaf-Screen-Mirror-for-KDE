# runtime-debug

## Description

Use this skill for bugs involving live mirroring, Start/Stop behavior, frame processing, capture backend behavior, HID output, runtime status, or tray/service lifecycle.

## When to use it

- Runtime loop hangs, crashes, or reports misleading status.
- Stop should halt mirroring without quitting the tray app.
- Capture, HID write timing, output ownership, or priority behavior is implicated.
- A fix needs runtime diagnostics or hardware/session verification notes.

## Constraints

- Keep the single Nanoleaf USB Edge Strip assumption.
- Do not add new FPS or priority knobs.
- Do not use `SCHED_FIFO`/`SCHED_RR`.
- Keep priority failures non-fatal.
- Preserve exclusive LED ownership for setup/calibration/manual test-pattern flows.
- Prefer diagnostics-backed fixes over runtime rewrites.

## Verification expectations

- Run targeted tests for touched runtime/capture/device/tray code.
- Run `git diff --check`.
- If behavior changes broadly, run the CI-aligned pytest/ruff/mypy commands from `AGENTS.md` as practical.
- State whether real KDE Plasma 6 / Wayland and Nanoleaf hardware testing is still required.
