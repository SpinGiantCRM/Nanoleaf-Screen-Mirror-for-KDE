# Arch/CachyOS install options

## Primary user path (recommended)
Use the AppImage installer flow from the repository root README:

```bash
bash ./install-nanoleaf-kde-sync.sh ./nanoleaf-kde-sync.AppImage
```

This is the only recommended end-user path.

## Advanced path: Arch package build (secondary)

```bash
cd packaging/arch
makepkg -si
```

Package install provides:
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
