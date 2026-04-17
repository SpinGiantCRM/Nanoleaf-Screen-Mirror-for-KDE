# Install on Arch / CachyOS (KDE)

## Recommended path: package build/install

```bash
cd packaging/arch
makepkg -si
```

Package install provides:
- Python package + CLI commands
- Desktop entry: `/usr/share/applications/nanoleaf-kde-sync.desktop`
- Icon: `/usr/share/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg`
- udev rule: `/usr/lib/udev/rules.d/60-nanoleaf-kde-sync.rules`

## Alternate path: pip/source install

```bash
pip install -r docs/requirements.txt
pip install .
```

For pip/source installs, install udev rules manually:

```bash
./scripts/setup_udev.sh
```

## First run order

```bash
nanoleaf-kde-sync-init-config --mode full-mock
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync
```

Then switch modes only after checks pass:

```bash
nanoleaf-kde-sync-init-config --mode capture-real --force
nanoleaf-kde-sync-init-config --mode full-real --force
```

## KDE autostart and capture authorization

```bash
mkdir -p ~/.config/autostart
cp /usr/share/applications/nanoleaf-kde-sync.desktop ~/.config/autostart/
```

Verify the desktop file contains:

`X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2`

Re-login after changing desktop authorization entries.

## If checks fail

Use troubleshooting guide:
- `docs/TROUBLESHOOTING.md`
