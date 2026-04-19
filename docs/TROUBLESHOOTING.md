# Troubleshooting

## Quick triage

Run:

```bash
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
```

If both commands pass but mirroring still fails, continue with the sections below.

## Common issues

### KWin screenshot authorization errors

If you see `NoAuthorized` / `NotAuthorized`, launch from the desktop entry or tray app so KDE policy applies `X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2`.

### No HID device found

1. Confirm USB IDs with `lsusb` (Nanoleaf USB: `37fa:8201` or `37fa:8202`).
2. Ensure udev rule is installed:

```bash
sudo install -Dm0644 assets/udev/60-nanoleaf-kde-sync.rules /etc/udev/rules.d/60-nanoleaf-kde-sync.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --action=add
```

3. Replug device.

### Colors look wrong on HDR display

Open tray **Settings** and adjust:
- HDR transfer (`srgb` / `pq`)
- HDR primaries (`bt709` / `bt2020`)
- HDR max nits

Start with `srgb + bt709` if your desktop is SDR, then tune brightness conservatively.

### Zone order mismatch

Use tray **Settings**:
- Reverse strip orientation
- Zone offset
- Mapping preview line

If the strip is mounted upside-down, enable reverse first, then fine-tune the offset.
