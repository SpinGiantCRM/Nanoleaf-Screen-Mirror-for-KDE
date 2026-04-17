# Real hardware setup (Linux/KDE)

This guide prepares `nanoleaf-kde-sync` for **real Nanoleaf USB hardware** on KDE Plasma.

## 1) Install the app

### Arch/CachyOS package path

```bash
cd packaging/arch
makepkg -si
```

### pip path

```bash
pip install -r docs/requirements.txt
pip install .
```

## 2) Install/activate udev rule

Package installs the rule automatically in `/usr/lib/udev/rules.d/`.

For pip/manual installs, use:

```bash
./scripts/setup_udev.sh
```

Or manually:

```bash
sudo install -m 0644 assets/udev/60-nanoleaf-kde-sync.rules /etc/udev/rules.d/60-nanoleaf-kde-sync.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
```

Reconnect the Nanoleaf USB device after rule reload.

## 3) Generate full-real config preset

```bash
nanoleaf-kde-sync-init-config --mode full-real --force
```

Then verify/update:

- `use_mock_capture=false`
- `use_mock_device=false`
- `prefer_backend="kwin-dbus"` (recommended first)
- `device_vid=14330` (`0x37fa`)
- `device_pid=33281` (`0x8201`) or `33282` (`0x8202`)

Config path: `~/.config/nanoleaf-kde-sync/config.json`

## 4) Verify diagnostics

```bash
nanoleaf-kde-sync-doctor --device
```

Expected in real mode:
- HID enumeration passes
- device probe reports model + zone count

## 5) Run smoke test

```bash
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync-smoke-test --send-test-frame
```

Second command sends one low-brightness test frame.

## 6) Start tray runtime and confirm status

```bash
nanoleaf-kde-sync
```

From tray **Status**, verify:
- capture mode/backend
- device mode = `real-usb`
- device connection/discovery
- no persistent last error

## Arch/CachyOS notes

- Required packages are pulled by PKGBUILD dependencies.
- `plugdev` may not exist by default; create/add user if needed:

```bash
sudo groupadd -f plugdev
sudo usermod -aG plugdev "$USER"
```

Log out/in after group changes.

If checks fail, continue in `docs/TROUBLESHOOTING.md`.
