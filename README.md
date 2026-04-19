# Nanoleaf Screen Mirror for KDE

Nanoleaf Screen Mirror for KDE brings Nanoleaf desktop mirroring to Linux on KDE Plasma 6.

It captures the active display, maps sampled colors to Nanoleaf zones, and sends frames to supported Nanoleaf USB devices.

## Features

- KDE Plasma 6 screen capture support
- Nanoleaf USB HID output (`NL82K1` / `NL82K2`)
- Configuration bootstrap and diagnostics commands
- Tray-managed autostart enable/disable with KDE desktop authorization marker
- Guided strip alignment controls (zone count, reverse, offset, preview mapping)
- User-facing HDR tuning controls (transfer, primaries, max nits)
- Simple service entrypoint for continuous mirroring

## Installation (Arch / CachyOS)

```bash
cd packaging/arch
makepkg -si
```

## Quick start

1. Generate a default configuration:

```bash
nanoleaf-kde-sync-init-config
```

2. Run diagnostics:

```bash
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
```

3. Confirm device IDs in `~/.config/nanoleaf-kde-sync/config.json`:

- `"device_vid": 14330` (`0x37fa`)
- `"device_pid": 33282` (`0x8202`) or `33281` (`0x8201`)

4. Start mirroring:

```bash
nanoleaf-kde-sync-service
```

5. Optional autostart management:

```bash
nanoleaf-kde-sync-autostart status
nanoleaf-kde-sync-autostart enable
nanoleaf-kde-sync-autostart disable
```

## Troubleshooting

- **No frame capture**: Ensure you are running KDE Plasma 6 Wayland and accepted the screenshot permission prompt.
- **ScreenShot2 authorization error (`...NoAuthorized` / `...NotAuthorized`)**:
  launching `nanoleaf-kde-sync-service` directly from a terminal can be denied by KDE policy.
  Prefer launching from the installed desktop entry/tray workflow so KDE can apply the
  `X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2` authorization context.
- **USB permission denied**: Install and reload the udev rule:

  ```bash
  sudo install -Dm0644 assets/udev/60-nanoleaf-kde-sync.rules /etc/udev/rules.d/60-nanoleaf-kde-sync.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=hidraw --action=add
  ```

  Then unplug and reconnect the device.

- **Zone order mismatch**: Open tray **Settings** and use the Zone alignment preview while tuning reverse/offset.
- **HDR looks washed out or too dim**: Open tray **Settings** and adjust HDR transfer/primaries/max nits.

## Supported environment

- Linux
- KDE Plasma 6 (Wayland)
- Nanoleaf USB device with supported VID/PID
