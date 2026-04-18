# RC test matrix (Arch + CachyOS)

This matrix defines required manual RC validation before tagging a release candidate.
Use it together with `docs/SMOKE_TEST.md` and record each run in the result log section at the end of this document.

## Target environments

| ID | Distro | Version / channel | KDE Plasma | Session type |
|---|---|---|---|---|
| A1 | Arch Linux | Latest stable snapshot on test day | Plasma 6.x | Wayland |
| A2 | Arch Linux | Latest stable snapshot on test day | Plasma 6.x | X11 |
| C1 | CachyOS | Latest stable snapshot on test day | Plasma 6.x | Wayland |
| C2 | CachyOS | Latest stable snapshot on test day | Plasma 6.x | X11 |

> Minimum RC gate: execute at least one Arch and one CachyOS run in each supported mode (`full-mock`, `capture-real`, `full-real`) and include both Wayland and X11 evidence.

## Mode scenarios and expected outcomes

Run all scenarios below per environment where hardware availability allows.
If hardware is unavailable, mark as `N/A` and provide reason.

| Scenario | Config command | Doctor expectation | Smoke expectation | Tray lifecycle expectation |
|---|---|---|---|---|
| `full-mock` | `nanoleaf-kde-sync-init-config --mode full-mock --force` | `nanoleaf-kde-sync-doctor` completes with dependency/session checks passing; no hard failure on missing USB device | `nanoleaf-kde-sync-smoke-test` prints capture frame info and exits `0` | Launch tray with `nanoleaf-kde-sync`; Start/Stop/Status updates work without freeze; status shows mock device mode |
| `capture-real` | `nanoleaf-kde-sync-init-config --mode capture-real --force` | `nanoleaf-kde-sync-doctor` validates real capture backend/session readiness | `nanoleaf-kde-sync-smoke-test` reports real capture frame shape; no device write required | Tray Start runs pipeline with real capture + mock/safe device path; Status remains healthy |
| `full-real` | `nanoleaf-kde-sync-init-config --mode full-real --force` | `nanoleaf-kde-sync-doctor --device` identifies real device model and zone count | `nanoleaf-kde-sync-smoke-test --send-test-frame` sends one low-brightness frame and exits `0` | Tray Start/Stop works end-to-end with real capture + USB device; Status shows connected device and empty/transient `last_error` |

## Required command set per matrix row

Use these exact commands in order (substitute the mode from the row under test):

```bash
nanoleaf-kde-sync-init-config --mode <full-mock|capture-real|full-real> --force
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync-doctor --device                 # required for full-real
nanoleaf-kde-sync-smoke-test --send-test-frame    # required for full-real
nanoleaf-kde-sync
```

Expected outcomes for sign-off:

1. `doctor` returns exit code `0` for the intended scenario checks.
2. `smoke-test` returns exit code `0` and reports valid frame/capture output.
3. `full-real` runs confirm real USB initialization and a successful test-frame write.
4. Tray app Start/Stop/Status lifecycle is functional with no UI freeze.

## RC result log artifact (lightweight)

Record every RC run here (or mirror this table into the release PR description).
This log is required before creating a tag.

| Date (UTC) | RC version | Env ID | Mode | Doctor | Smoke | Tray lifecycle | Tester | Notes |
|---|---|---|---|---|---|---|---|---|
| YYYY-MM-DD | vX.Y.Z-rcN | A1/A2/C1/C2 | full-mock/capture-real/full-real | ✅/❌/N/A | ✅/❌/N/A | ✅/❌/N/A | @handle | link to logs/screenshots/issues |
