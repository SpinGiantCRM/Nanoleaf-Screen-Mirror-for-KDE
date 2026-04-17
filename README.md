# nanoleaf-kde-sync

`nanoleaf-kde-sync` mirrors KDE Plasma screen colors to supported Nanoleaf USB light devices on Linux.

This repo is now in a **first usable app** state: mock mode remains default/safe, real capture + real hardware workflows are documented, and a built-in diagnostics flow is available.

## What currently works

- KDE tray app to start/stop runtime service and edit settings.
- Capture pipeline with KWin DBus ScreenShot2 + legacy fallback support.
- Optional kmsgrab-style backend path.
- Real Nanoleaf USB HID TLV protocol implementation.
- Device model + strip length probe during startup.
- Mock-first workflow for capture and/or device.
- Runtime status visibility (capture backend/mode, device mode, last error).
- CLI diagnostics (`nanoleaf-kde-sync-doctor`) and smoke test (`nanoleaf-kde-sync-smoke-test`).

## Supported real hardware

- Nanoleaf Pegboard Desk Dock (`VID=0x37FA`, `PID=0x8201`, model `NL82K1`)
- Nanoleaf PC Screen Mirror Light Strip (`VID=0x37FA`, `PID=0x8202`, model `NL82K2`)

Unsupported model strings fail startup with an explicit message.

## Requirements

- Linux (KDE Plasma session strongly recommended)
- Python 3.11+
- Python packages: `numpy`, `PyQt6`, `dbus-next`, `hidapi`

Install:

```bash
pip install -r docs/requirements.txt
pip install .
```

## First-run modes (important)

Config file: `~/.config/nanoleaf-kde-sync/config.json`

1. **Full mock (default + safest)**
   - `use_mock_capture=true`
   - `use_mock_device=true`
2. **Real capture + mock device**
   - `use_mock_capture=false`
   - `use_mock_device=true`
   - `prefer_backend="kwin-dbus"`
3. **Real capture + real device**
   - `use_mock_capture=false`
   - `use_mock_device=false`
   - `prefer_backend="kwin-dbus"`
   - set `device_vid/device_pid`

## Run commands

- Tray app: `nanoleaf-kde-sync`
- Service only: `nanoleaf-kde-sync-service`
- Diagnostics: `nanoleaf-kde-sync-doctor`
- Deep device diagnostics: `nanoleaf-kde-sync-doctor --device`
- Smoke test: `nanoleaf-kde-sync-smoke-test`
- Smoke test + one test LED frame: `nanoleaf-kde-sync-smoke-test --send-test-frame`

## KDE/autostart + ScreenShot2 authorization

Copy desktop file:

```bash
mkdir -p ~/.config/autostart
cp docs/nanoleaf-kde-sync.desktop ~/.config/autostart/
```

This desktop entry includes:

`X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2`

Re-login after changing this value.

## Linux USB permission setup (udev)

- Rule file: `assets/udev/60-nanoleaf-kde-sync.rules`
- Helper script: `scripts/setup_udev.sh`
- Full guide: `docs/HARDWARE_SETUP.md`

Quick path:

```bash
./scripts/setup_udev.sh
```

## Manual smoke-test workflow

See `docs/SMOKE_TEST.md` for the full checklist.

Minimal path:

```bash
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync-doctor --device
nanoleaf-kde-sync-smoke-test --send-test-frame
```

## Troubleshooting

### No DBus capture / KWin unavailable

- Confirm running inside KDE Plasma session.
- Check `DBUS_SESSION_BUS_ADDRESS` exists.
- Run `nanoleaf-kde-sync-doctor` and inspect `kwin-screenshot2` status.
- Ensure desktop authorization key is present in `.desktop` file.

### HID permission denied

- Install udev rule and reload (`./scripts/setup_udev.sh`).
- Reconnect device.
- Confirm user group access (`plugdev` or active ACL via `uaccess`).

### Device not found

- Verify cable/device power.
- Validate VID/PID in config.
- Run `lsusb` and `nanoleaf-kde-sync-doctor --device`.

### Unsupported model

- Only `NL82K1`/`NL82K2` are accepted currently.
- Use mock device mode for unsupported hardware.

### Blank/no LED updates

- Confirm service running from tray status.
- Confirm `device_discovered=true` in tray status.
- Run smoke test with `--send-test-frame` to separate mapping vs transport issues.
- Ensure brightness is non-zero in hardware state.

## Known limitations

- KWin behavior varies by Plasma version/session policy.
- Runtime button event actions are not wired yet.
- Packaging is still manual (`pip install .`) rather than distro-native packages.
- Performance tuning is intentionally conservative in this release-candidate stage.

## Additional docs

- `docs/HARDWARE_SETUP.md`
- `docs/SMOKE_TEST.md`
- `docs/TECHNICAL_DESIGN.md`
- `docs/CHANGELOG.md`
