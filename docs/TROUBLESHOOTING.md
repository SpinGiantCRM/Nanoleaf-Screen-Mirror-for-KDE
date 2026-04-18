# Troubleshooting guide

If normal install worked, start with tray app **Help / Troubleshooting**.

## 1) Common issues and the next step

### App starts but light strip does not react
- Open Settings and confirm **Real Nanoleaf mode** is enabled.
- Replug the USB cable once after installer ran udev setup.

### Permission denied / HID open errors
- Re-run installer helper so it can install/update:
  - `/etc/udev/rules.d/60-nanoleaf-kde-sync.rules`
- Log out/in if permissions still look stale.

### KDE capture authorization errors
- Launch from installed menu entry (it includes required KDE authorization key).
- If needed, log out/in once after desktop entry changes.

## 2) Advanced diagnostics (optional)
Use these only when needed:

```bash
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync-doctor --device
```

## 3) Manual reset to safe mode (advanced)

```bash
nanoleaf-kde-sync-init-config --mode full-mock --force
```

Then reopen the tray app and choose Demo/Real mode again.
