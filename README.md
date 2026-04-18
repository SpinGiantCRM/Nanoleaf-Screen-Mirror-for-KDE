# nanoleaf-kde-sync

`nanoleaf-kde-sync` mirrors KDE Plasma screen colors to supported Nanoleaf USB light devices on Linux.

## Primary install path (recommended for Arch/CachyOS KDE users)

Use the Arch package workflow:

```bash
cd packaging/arch
makepkg -si
```

This path keeps Python/runtime dependencies consistent on Arch-family systems and installs:
- the CLI and tray app entry points
- desktop launcher + icon
- udev rule for Nanoleaf USB access
- docs under `/usr/share/doc/nanoleaf-kde-sync/`

After install:
- initialize first-run config (safe Demo mode):
  - `nanoleaf-kde-sync-init-config --mode full-mock`
- run diagnostics:
  - `nanoleaf-kde-sync-doctor`
  - `nanoleaf-kde-sync-smoke-test`

## Troubleshooting (if something breaks)
- Open `docs/TROUBLESHOOTING.md`
- In the tray app, use **Help / Troubleshooting**

## Advanced / developer paths (secondary)
These are still supported, but **not the recommended user path**:
- AppImage installer (experimental on Arch/CachyOS): `install-nanoleaf-kde-sync.sh`
- pip/source setup and developer tooling: `docs/README.md`

## Project status

Release candidate focused on:
- Arch/CachyOS + KDE first-run usability
- KWin capture path + capture fallback
- Nanoleaf USB real driver path
- AppImage + installer based onboarding
