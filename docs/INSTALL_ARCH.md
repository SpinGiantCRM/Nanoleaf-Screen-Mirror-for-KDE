# Arch/CachyOS install options

## Primary user path (recommended)
Use the Arch package build/install path:

```bash
cd packaging/arch
makepkg -si
```

This is the recommended end-user path on Arch/CachyOS KDE.

## Secondary path: standalone AppImage installer (experimental on Arch/CachyOS)

```bash
bash ./install-nanoleaf-kde-sync.sh ./nanoleaf-kde-sync.AppImage
```

Use this only if you explicitly want the release AppImage flow. It currently expects a matching Python 3.11 runtime on the target machine.

## Package install provides
- Python package + CLI commands
- Desktop entry: `/usr/share/applications/nanoleaf-kde-sync.desktop`
- Icon: `/usr/share/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg`
- udev rule: `/usr/lib/udev/rules.d/60-nanoleaf-kde-sync.rules`

## Advanced path: pip/source install (secondary)

```bash
pip install -r docs/requirements.txt
pip install .
./scripts/setup_udev.sh
```

Use this path only for development and debugging workflows.
