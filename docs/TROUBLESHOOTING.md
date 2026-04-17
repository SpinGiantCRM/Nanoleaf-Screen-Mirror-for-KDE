# Troubleshooting guide

Use this checklist before opening a bug report.

## 1) Capture baseline diagnostics

```bash
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
```

If real USB mode is enabled, also run:

```bash
nanoleaf-kde-sync-doctor --device
```

## 2) Common failure patterns

### KWin capture errors
- Confirm you are in a KDE Plasma session.
- Confirm `DBUS_SESSION_BUS_ADDRESS` is present.
- Confirm desktop autostart entry includes:
  - `X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2`
- Re-login after updating the desktop entry.

### USB/HID permission errors
- Arch package path installs udev rule into:
  - `/usr/lib/udev/rules.d/60-nanoleaf-kde-sync.rules`
- pip/manual path must install rule from:
  - `assets/udev/60-nanoleaf-kde-sync.rules`
- Reload rules and reconnect the device:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
```

### Device not discovered
- Verify USB cable/power.
- Verify configured VID/PID in `~/.config/nanoleaf-kde-sync/config.json`.
- Confirm visibility in `lsusb`.
- Run `nanoleaf-kde-sync-doctor --device` again.

### Tray start failures
- Use tray **Status** and **Run Doctor** actions.
- Reset to safe known-good mode:

```bash
nanoleaf-kde-sync-init-config --mode full-mock --force
```

Then move to `capture-real` and `full-real` one step at a time.

## 3) What to include in bug reports

Include:
- exact version/tag
- install path (Arch package or pip/source)
- output from doctor + smoke-test
- minimal reproduction steps
- relevant tray status summary (`last_error`, `guidance`, capture/device mode)
