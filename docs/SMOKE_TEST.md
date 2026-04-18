# Manual smoke test checklist

Run this after first install, mode changes, or hardware setup changes.
On Arch/CachyOS KDE, run from the package install path (`makepkg -si`) for the most reliable runtime.

For RC coverage across distros/sessions/modes, execute this checklist per matrix row in `docs/RC_TEST_MATRIX.md`.

## RC matrix execution mapping (commands + expected outputs)

Use this sequence exactly for each matrix row and mode under test:

```bash
nanoleaf-kde-sync-init-config --mode <full-mock|capture-real|full-real> --force
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync-doctor --device                 # required for full-real
nanoleaf-kde-sync-smoke-test --send-test-frame    # required for full-real
nanoleaf-kde-sync
```

Expected command outcomes:

- `nanoleaf-kde-sync-init-config ...`: mode is written successfully to config (exit code `0`).
- `nanoleaf-kde-sync-doctor`: dependency/session checks complete successfully for the selected mode (exit code `0`).
- `nanoleaf-kde-sync-smoke-test`: valid capture frame output is printed (for example, frame shape/dimensions) and command exits `0`.
- `nanoleaf-kde-sync-doctor --device` (`full-real`): real device is discovered/initialized and model + zone details are printed.
- `nanoleaf-kde-sync-smoke-test --send-test-frame` (`full-real`): one low-brightness test frame is sent successfully (exit code `0`).
- `nanoleaf-kde-sync` tray lifecycle: Start/Stop/Status works without freezing; status reflects current mode/backend and no persistent `last_error`.

After each run, record pass/fail in the RC run artifact table in `docs/RC_TEST_MATRIX.md` (or copy that table into the release PR body).

## 0) Optional reset to known-safe mode

```bash
nanoleaf-kde-sync-init-config --mode full-mock --force
```

## 1) Doctor baseline

```bash
nanoleaf-kde-sync-doctor
```

Purpose: dependency/session/KWin authorization sanity checks.

## 2) Capture validation

```bash
nanoleaf-kde-sync-smoke-test
```

Expected: prints a valid frame shape from active capture backend.
If you are in full-mock mode this validates pipeline health, not physical USB output.

## 3) Real-device probe (only when `use_mock_device=false`)

```bash
nanoleaf-kde-sync-doctor --device
```

Expected: real device initializes and prints model + zone count.

## 4) Safe LED write test (optional but recommended)

```bash
nanoleaf-kde-sync-smoke-test --send-test-frame
```

Expected: one low-brightness RGB test frame reaches the strip.

## 5) Tray runtime verification

```bash
nanoleaf-kde-sync
```

In tray:
- Start service
- Open **Status**
- Confirm:
  - running state
  - capture mode/backend
  - device mode + connection/discovery state
  - `last_error` empty or transient

## Interpreting failures

- Doctor fails before smoke test: fix environment/config first.
- Smoke test capture fails but device probe passes: capture backend/session issue.
- Device probe fails but capture passes: USB permissions/cable/device issue.
- Tray start fails: use tray status guidance + rerun doctor.

For a full support checklist, see `docs/TROUBLESHOOTING.md`.
