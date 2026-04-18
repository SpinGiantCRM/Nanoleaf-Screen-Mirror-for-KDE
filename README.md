# nanoleaf-kde-sync

`nanoleaf-kde-sync` mirrors KDE Plasma screen colors to supported Nanoleaf USB light devices on Linux.

Licensed under the Nanoleaf Source-Available Non-Commercial License.

| Compatibility area | Current status |
| --- | --- |
| KDE Plasma version support | **Plasma 6 is the primary target** via modern `org.kde.KWin.ScreenShot2`; older `org.kde.kwin.Screenshot` interfaces are used as a compatibility fallback path. |
| Primary distro target | **Arch/CachyOS** is the primary supported install/runtime path (`makepkg -si` from `packaging/arch`). |
| Capture backend + Wayland/X11 status | Backend order is **`kmsgrab` preferred**, then **`kwin-dbus` fallback**; KWin D-Bus capture is the implemented compatibility path when `kmsgrab` is unavailable. |
| Device model support | Real USB protocol support is implemented for **Pegboard Desk Dock `NL82K1` (PID `0x8201`)** and **PC Screen Mirror LS `NL82K2` (PID `0x8202`)**. |
| HDR support caveats | HDR-aware processing is implemented, but behavior still depends on capture metadata, transfer-function handling, and compositor/stack capabilities. |
| AppImage support status | **Secondary / experimental on Arch/CachyOS**; Arch package workflow remains the recommended path. |

For unsupported or untested setups, start with `docs/TROUBLESHOOTING.md`.

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

## Release artifact verification

Each GitHub Release includes SHA256 checksum files:
- `nanoleaf-kde-sync.AppImage.sha256`
- `install-nanoleaf-kde-sync.sh.sha256`
- `<artifact>.sha256` for any published wheel/sdist artifacts (`*.whl`, `*.tar.gz`)

Verify checksums after downloading assets:

```bash
sha256sum -c nanoleaf-kde-sync.AppImage.sha256
sha256sum -c install-nanoleaf-kde-sync.sh.sha256
```

If wheel/sdist assets are present, verify them the same way:

```bash
sha256sum -c nanoleaf_kde_sync-*.whl.sha256
sha256sum -c nanoleaf_kde_sync-*.tar.gz.sha256
```

### Sigstore signatures (when available in release assets)

Releases also publish keyless Sigstore signing files per artifact:
- `<artifact>.sig` (signature)
- `<artifact>.pem` (signing certificate)

To verify an artifact:

```bash
cosign verify-blob nanoleaf-kde-sync.AppImage \
  --signature nanoleaf-kde-sync.AppImage.sig \
  --certificate nanoleaf-kde-sync.AppImage.pem \
  --certificate-identity-regexp 'https://github.com/.+/.+/.github/workflows/release.yml@refs/tags/.+' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Project status

Release candidate focused on:
- Arch/CachyOS + KDE first-run usability
- KWin capture path + capture fallback
- Nanoleaf USB real driver path
- Arch package based onboarding (AppImage remains secondary/experimental on Arch/CachyOS)
