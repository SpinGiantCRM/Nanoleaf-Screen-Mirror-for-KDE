# Install on Arch / CachyOS (KDE)

## Option A: Build local package from this repository

```bash
cd packaging/arch
makepkg -si
```

This installs:
- Python package + CLI commands (`nanoleaf-kde-sync`, `-service`, `-doctor`, `-smoke-test`, `-init-config`)
- desktop file (`/usr/share/applications/nanoleaf-kde-sync.desktop`)
- icon (`/usr/share/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg`)
- udev rule (`/usr/lib/udev/rules.d/60-nanoleaf-kde-sync.rules`)

## Option B: pip install (developer/manual path)

```bash
pip install -r docs/requirements.txt
pip install .
```

If you use pip, you still need to install the udev rule manually:

```bash
./scripts/setup_udev.sh
```

## First run (recommended order)

```bash
nanoleaf-kde-sync-init-config --mode full-mock
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync
```

Then switch to `capture-real` or `full-real` when capture/device checks pass.

## Mode presets

- `full-mock`: no KDE capture required, no USB required.
- `capture-real`: real screen capture + mock device.
- `full-real`: real screen capture + real USB device.

```bash
nanoleaf-kde-sync-init-config --mode capture-real --force
nanoleaf-kde-sync-init-config --mode full-real --force
```
