# Troubleshooting guide

Recommended install path on Arch/CachyOS KDE is `cd packaging/arch && makepkg -si`.
If you installed with AppImage on Arch/CachyOS, treat that path as experimental.

If normal install worked, start with tray app **Help / Troubleshooting**.

## 1) Common issues and the next step

### App starts but light strip does not react
- Open Settings and confirm **Real Nanoleaf mode** is enabled.
- Replug the USB cable once after installer ran udev setup.
- If only mock mode works, run `nanoleaf-kde-sync-doctor --device` before assuming hardware support is fully ready.

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

Interpretation note:
- `nanoleaf-kde-sync-doctor` and `nanoleaf-kde-sync-smoke-test` always validate mock/demo paths.
- Real USB readiness is only validated when `--device` checks and/or `--send-test-frame` succeed on your hardware.

## 3) Manual reset to safe mode (advanced)

```bash
nanoleaf-kde-sync-init-config --mode full-mock --force
```

Then reopen the tray app and choose Demo/Real mode again.
