# Real hardware setup (Linux/KDE)

This guide prepares `nanoleaf-kde-sync` for real USB hardware on KDE Plasma.

## 1) Install package

```bash
pip install .
```

## 2) Install udev rule

Use the helper script:

```bash
./scripts/setup_udev.sh
```

Or manually:

```bash
sudo install -m 0644 assets/udev/60-nanoleaf-kde-sync.rules /etc/udev/rules.d/60-nanoleaf-kde-sync.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
```

Reconnect the Nanoleaf USB device after reloading rules.

## 3) Configure real mode

Edit `~/.config/nanoleaf-kde-sync/config.json`:

- `use_mock_capture=false`
- `use_mock_device=false`
- `prefer_backend="kwin-dbus"` (recommended first)
- `device_vid=14330` (0x37fa)
- `device_pid=33281` (0x8201) or `33282` (0x8202)

## 4) Verify diagnostics

```bash
nanoleaf-kde-sync-doctor --device
```

## 5) Run smoke test

```bash
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync-smoke-test --send-test-frame
```

The second command sends one low-brightness test frame.

## CachyOS / Arch notes

- Ensure `python`, `python-pip`, and optional `base-devel` are installed.
- `plugdev` may not exist by default; create it if needed:

```bash
sudo groupadd -f plugdev
sudo usermod -aG plugdev "$USER"
```

Log out/in after group changes.
