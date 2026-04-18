# nanoleaf-kde-sync

A focused Linux/KDE Plasma 6 port of Nanoleaf desktop screen mirroring:

**capture screen -> compute zone colours -> send USB frame to Nanoleaf device**.

## Scope (recovered baseline)

- OS/session: Linux + KDE Plasma 6
- Real capture backend: `kwin-dbus` only
- Device path: Nanoleaf USB HID driver (`NL82K1` / `NL82K2`)
- Optional safe mode: mock capture and/or mock device for first-run checks

Everything else was intentionally de-scoped so the core mirroring path remains understandable and maintainable.

## Primary install path (Arch / CachyOS)

```bash
cd packaging/arch
makepkg -si
```

No Docker, no AppImage installer flow, no duplicate install systems.

## First run

1) Generate beginner-safe config (real capture, mock device):
```bash
nanoleaf-kde-sync-init-config
```

2) Run diagnostics:
```bash
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
```

3) Switch to real device by editing:
`~/.config/nanoleaf-kde-sync/config.json`

Set:
- `"use_mock_device": false`
- `"device_vid": 14330` (`0x37fa`)
- `"device_pid": 33282` (`0x8202`) or `33281` (`0x8201`)

Then run:
```bash
nanoleaf-kde-sync-service
```

## Common failures

- **No frame capture:** Ensure KDE Plasma 6 Wayland session and screenshot permission prompt accepted.
- **USB permission denied:** Install `assets/udev/60-nanoleaf-kde-sync.rules`, reload udev, unplug/replug device.
- **Lights not matching order:** adjust `zone_offset`, `reverse_zones`, and `device_zone_count` in config.

## Non-goals

- Cloud features
- Enterprise architecture
- Multiple speculative runtime backends
- Release ceremony tooling inside the core project
