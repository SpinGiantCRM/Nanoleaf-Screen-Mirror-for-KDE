# nanoleaf-kde-sync

`nanoleaf-kde-sync` mirrors KDE Plasma screen colors to supported Nanoleaf USB light devices on Linux.

## Primary install path (recommended for Arch/CachyOS KDE users)

### Download these two files from the latest release
1. `nanoleaf-kde-sync.AppImage`
2. `install-nanoleaf-kde-sync.sh`

### Install (one command)
```bash
bash ./install-nanoleaf-kde-sync.sh ./nanoleaf-kde-sync.AppImage
```

What the installer does for you:
- copies the AppImage to `~/.local/share/nanoleaf-kde-sync/`
- installs launcher menu entry + icon
- creates first-run config automatically (safe Demo mode)
- asks for admin permission only for USB udev access setup
- reloads udev rules when possible
- launches the app at the end

After install:
- the app appears in your KDE launcher menu as **nanoleaf-kde-sync**
- first launch shows a simple choice: **Demo mode** or **Real Nanoleaf mode**
- advanced diagnostics are still available later from tray Help/Troubleshooting

## Troubleshooting (if something breaks)
- Open `docs/TROUBLESHOOTING.md`
- In the tray app, use **Help / Troubleshooting**

## Advanced / developer paths (secondary)
These are still supported, but **not the recommended user path**:
- Arch package build: `docs/INSTALL_ARCH.md`
- pip/source setup and developer tooling: `docs/README.md`

## Project status

Release candidate focused on:
- Arch/CachyOS + KDE first-run usability
- KWin capture path + capture fallback
- Nanoleaf USB real driver path
- AppImage + installer based onboarding
