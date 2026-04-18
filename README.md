# Nanoleaf Screen Mirror for KDE

Nanoleaf Screen Mirror for KDE brings Nanoleaf desktop mirroring to Linux on KDE Plasma 6.

It captures the active display, maps sampled colors to Nanoleaf zones, and sends frames to supported Nanoleaf USB devices.

## Features

- KDE Plasma 6 screen capture support
- Nanoleaf USB HID output (`NL82K1` / `NL82K2`)
- Configuration bootstrap and diagnostics commands
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

## Troubleshooting

- **No frame capture**: Ensure you are running KDE Plasma 6 Wayland and accepted the screenshot permission prompt.
- **USB permission denied**: Install and reload the udev rule:

  ```bash
  sudo install -Dm0644 assets/udev/60-nanoleaf-kde-sync.rules /etc/udev/rules.d/60-nanoleaf-kde-sync.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=hidraw --action=add
  ```

  Then unplug and reconnect the device.

- **Zone order mismatch**: Adjust `zone_offset`, `reverse_zones`, and `device_zone_count` in the config.

## Supported environment

- Linux
- KDE Plasma 6 (Wayland)
- Nanoleaf USB device with supported VID/PID
