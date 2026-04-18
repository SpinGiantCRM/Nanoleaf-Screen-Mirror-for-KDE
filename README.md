# nanoleaf-kde-sync

A focused Linux/KDE Plasma 6 port of Nanoleaf desktop screen mirroring:

**capture screen -> compute zone colours -> send USB frame to Nanoleaf device**.

## Scope (recovered baseline)

- OS/session: Linux + KDE Plasma 6
- Real capture backend: `kwin-dbus` only
- Device path: Nanoleaf USB HID driver (`NL82K1` / `NL82K2`)
- Optional diagnostics mode: mock capture for first-run checks

Everything else was intentionally de-scoped so the core mirroring path remains understandable and maintainable.

## Primary install path (Arch / CachyOS)

```bash
cd packaging/arch
makepkg -si
```

No Docker, no AppImage installer flow, no duplicate install systems.

## First run

1) Generate default config (real capture + real USB device):
```bash
nanoleaf-kde-sync-init-config
```

2) Run diagnostics:
```bash
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
```

3) Verify device IDs in `~/.config/nanoleaf-kde-sync/config.json`:
- `"device_vid": 14330` (`0x37fa`)
- `"device_pid": 33282` (`0x8202`) or `33281` (`0x8201`)

Then run:
```bash
nanoleaf-kde-sync-service
```

## Common failures

- **No frame capture:** Ensure KDE Plasma 6 Wayland session and screenshot permission prompt accepted.
- **USB permission denied:** Install and reload the udev rule with:
  ```bash
  sudo install -Dm0644 assets/udev/60-nanoleaf-kde-sync.rules /etc/udev/rules.d/60-nanoleaf-kde-sync.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=hidraw --action=add
  ```
  Then unplug/replug the device. If it still fails, check `journalctl -f` and try `udevadm test /sys/class/hidraw/hidraw0`.
- **Lights not matching order:** adjust `zone_offset`, `reverse_zones`, and `device_zone_count` in config.

## Non-goals

- Cloud features
- Enterprise architecture
- Multiple speculative runtime backends
- Release ceremony tooling inside the core project
