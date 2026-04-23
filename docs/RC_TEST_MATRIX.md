# RC Test Matrix

Use this matrix to track required release-candidate coverage.

## Required dimensions

- Distros/sessions: Arch (Wayland/X11), CachyOS (Wayland/X11)
- Modes: `full-mock`, `capture-real`, `full-real` (or N/A with reason)
- Checks: Doctor, Smoke, tray lifecycle, and calibration parity evidence

## Matrix template

| Date (UTC) | RC version | Env ID | Distro | Session | Mode | Doctor | Smoke | Tray lifecycle | Calibration parity | Tester | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| YYYY-MM-DD | vX.Y.Z-rcN | A1 | Arch | Wayland | full-mock | pass/fail | pass/fail | pass/fail | pass/fail | @handle |  |

## Completion rule

All required rows/modes must have linked evidence before tagging a release.
