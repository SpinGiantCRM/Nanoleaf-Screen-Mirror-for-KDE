# Nanoleaf Screen Mirror for KDE (v1.7.2)

Personal-first Nanoleaf USB screen mirroring app for KDE Plasma 6 on Linux.

This repo is intentionally lean: app code, packaging, and only practical docs needed to install/run/troubleshoot.

## What it does

- Captures your active display on KDE Plasma 6
- Samples edge/zone colors
- Streams colors to supported Nanoleaf USB strips (`NL82K1`, `NL82K2`)
- Provides a tray app + settings + first-run display setup

## Install (Arch / CachyOS)

**Recommended (pacman / paru updates):**

```bash
paru -S --needed python-dacite nanoleaf-kde-sync
```

After the package is published on AUR, normal system updates (`paru -Syu`) keep the app current.

**Local checkout build (development or pre-AUR):**

```bash
paru -S --needed python-dacite
./scripts/build_arch_package.sh
```

Install udev rules after package install:

```bash
./scripts/setup_udev.sh
```

## Quick start

```bash
nanoleaf-kde-sync-init-config
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync
```

Service-only mode:

```bash
nanoleaf-kde-sync-service
```

## Core commands

- `nanoleaf-kde-sync` — tray app (recommended)
- `nanoleaf-kde-sync-service` — headless runtime service
- `nanoleaf-kde-sync-init-config` — generate default config
- `nanoleaf-kde-sync-doctor` — environment/device diagnostics
- `nanoleaf-kde-sync-smoke-test` — quick functional sanity check
- `nanoleaf-kde-sync-autostart` — manage KDE autostart integration
- `nanoleaf-kde-sync-reset` — reset config/calibration/diagnostic cache safely

## First-run setup

1. Start the tray app (`nanoleaf-kde-sync`).
2. Complete the setup wizard.
3. Keep **manual strip zone count** set to your real hardware value.
4. Run a calibration test pattern and assign TL/TR/BR/BL anchors.

Manual strip count is authoritative for runtime, mapping, and calibration. Device-reported count is diagnostics-only unless you explicitly apply a new value.

## HDR / SDR notes

- `Display preset = SDR`: SDR-safe defaults.
- `Display preset = HDR`: HDR-first defaults.
- `Display preset = Auto`: follows compositor capability.

On Plasma HDR desktops, verify SDR white reference and compositor HDR settings in app diagnostics before tuning brightness.

## Fresh install / reinstall / uninstall helpers

Pacman-managed reinstall from a local checkout:

```bash
./scripts/reinstall_local.sh
./scripts/uninstall_local.sh
# optional full purge:
./scripts/uninstall_local.sh --purge-config
```

See [Arch / AUR packaging](docs/PACKAGING_AUR.md) for maintainer and AUR publish steps.

Reinstall helper stops old tray/service processes first to avoid stale runtime loops and HID handles.

## Reset commands

```bash
nanoleaf-kde-sync-reset app-config --stop-runtime
nanoleaf-kde-sync-reset calibration --stop-runtime
nanoleaf-kde-sync-reset diagnostics --stop-runtime
```

- `app-config`: full config reset.
- `calibration`: anchors/mapping/calibration payload only.
- `diagnostics`: probe/latency/wizard draft caches only.

## Practical docs

- [Hardware setup](docs/HARDWARE_SETUP.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Smoke test](docs/SMOKE_TEST.md)

## Release gate

Only CI needs to pass before release.

## Developer setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
pre-commit install
pre-commit run --all-files
```

## Supported environment

- Linux
- KDE Plasma 6 (Wayland recommended)
- Supported Nanoleaf USB strips: `NL82K1` (`0x37fa:0x8201`), `NL82K2` (`0x37fa:0x8202`)

## Known limitations

- Single-monitor flow only (no multi-monitor support).
- Device strip count auto-detection is diagnostics-only; not auto-applied.
- Desktop-entry launch context is still preferred for reliable KWin authorization.


## Ambient color model defaults

The daily-use default is now tuned for stable ambient glow rather than precision-debug sampling:

- Layout: `edge_strip`
- Edge locality: `balanced` (default for stability; `tight` remains available for precision diagnostics)
- Quality: `high`
- Motion: `responsive`
- Color style: `ambient` (recommended)
- Display preset: `hdr`

Color styles:
- **Reference / Natural**: color-accurate, neutral-preserving, chroma-capped.
- **Ambient**: recommended Nanoleaf-like stable glow with neutral luminance floor.
- **Vivid**: richer color with controlled chroma boost.
- **Punchy**: strongest stylized response.

Grey/white edge content now drives neutral luminance directly, so medium greys produce visible neutral light instead of collapsing toward black.

Diagnostics include edge-locality and colour-accuracy summaries (input/output RGB, perceptual lightness/chroma ratio, hue delta, neutral preservation), plus HDR/SDR compositor context.
