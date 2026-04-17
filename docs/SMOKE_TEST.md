# Manual smoke test checklist

Run this after first install, mode changes, or hardware setup changes.

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
