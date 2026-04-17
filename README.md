# nanoleaf-kde-sync

`nanoleaf-kde-sync` mirrors KDE Plasma screen colors to supported Nanoleaf USB light devices on Linux.

This repository is in **release-candidate** shape for first real-user installs on **Arch/CachyOS + KDE**.

## Install paths

### Arch/CachyOS package (recommended)

```bash
cd packaging/arch
makepkg -si
```

See the full guide: `docs/INSTALL_ARCH.md`.

### pip install path

```bash
pip install -r docs/requirements.txt
pip install .
```

## What gets installed / available commands

- Tray app: `nanoleaf-kde-sync`
- Service only: `nanoleaf-kde-sync-service`
- Diagnostics: `nanoleaf-kde-sync-doctor`
- Smoke test: `nanoleaf-kde-sync-smoke-test`
- First-run config helper: `nanoleaf-kde-sync-init-config`

## First run (recommended order)

1) Generate config safely:

```bash
nanoleaf-kde-sync-init-config --mode full-mock
```

2) Validate environment:

```bash
nanoleaf-kde-sync-doctor
```

3) Validate capture/device path:

```bash
nanoleaf-kde-sync-smoke-test
```

4) Launch tray app:

```bash
nanoleaf-kde-sync
```

## Mode presets

The helper command supports fast mode switching:

- `full-mock` (default): mock capture + mock device
- `capture-real`: real capture + mock device
- `full-real`: real capture + real USB device

```bash
nanoleaf-kde-sync-init-config --mode capture-real --force
nanoleaf-kde-sync-init-config --mode full-real --force
```

Config location: `~/.config/nanoleaf-kde-sync/config.json`

## KDE/autostart + ScreenShot2 authorization

Desktop file: `docs/nanoleaf-kde-sync.desktop`

```bash
mkdir -p ~/.config/autostart
cp docs/nanoleaf-kde-sync.desktop ~/.config/autostart/
```

It includes:

`X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2`

Re-login after changing this value.

## USB / udev setup

- Rule file: `assets/udev/60-nanoleaf-kde-sync.rules`
- Helper script: `scripts/setup_udev.sh`
- Full guide: `docs/HARDWARE_SETUP.md`

Quick path:

```bash
./scripts/setup_udev.sh
```

## Supported real hardware

- Nanoleaf Pegboard Desk Dock (`VID=0x37FA`, `PID=0x8201`, model `NL82K1`)
- Nanoleaf PC Screen Mirror Light Strip (`VID=0x37FA`, `PID=0x8202`, model `NL82K2`)

Unsupported model strings fail startup with an explicit message.

## How to tell what works

- Capture working: `nanoleaf-kde-sync-smoke-test` prints a valid frame shape.
- USB working: `nanoleaf-kde-sync-doctor --device` reports model + zone count.
- Runtime working: tray **Status** shows running state, mode, and device connection/discovery.

## Troubleshooting

### KWin capture unavailable

- Confirm KDE Plasma session.
- Confirm `DBUS_SESSION_BUS_ADDRESS` exists.
- Run `nanoleaf-kde-sync-doctor` and inspect `kwin-screenshot2`.
- Ensure desktop authorization key is present.

### HID permission denied

- Install/reload udev rule (`./scripts/setup_udev.sh`).
- Reconnect device.
- Confirm user group/ACL access (`plugdev` or `uaccess`).

### Device not found

- Verify cable + power.
- Validate `device_vid/device_pid` in config.
- Run `lsusb` and `nanoleaf-kde-sync-doctor --device`.

### Startup fails in tray

- Use tray **Status** and **Run Doctor**.
- If needed, reset config quickly:
  `nanoleaf-kde-sync-init-config --mode full-mock --force`

## Known limitations (RC)

- KWin behavior can vary across Plasma versions/policies.
- Runtime button-event actions are still prototype-grade.
- Packaging path is Arch-family only in this release candidate.
- Advanced effects/animations are intentionally out of scope.

## Additional docs

- `docs/INSTALL_ARCH.md`
- `docs/HARDWARE_SETUP.md`
- `docs/SMOKE_TEST.md`
- `docs/RELEASE_CHECKLIST.md`
- `docs/TECHNICAL_DESIGN.md`
- `docs/CHANGELOG.md`
