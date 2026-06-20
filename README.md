# Nanoleaf Screen Mirror for KDE

Public Nanoleaf USB screen mirroring app for KDE Plasma 6 on Linux (Arch / CachyOS and other distros via source install).

Mirrors your display edge colors to supported Nanoleaf USB strips in real time, with a tray app, setup wizard, calibration, and diagnostics.

## What you need

- Linux with KDE Plasma 6 (Wayland recommended)
- A supported Nanoleaf USB strip: `NL82K1` (`0x37fa:0x8201`) or `NL82K2` (`0x37fa:0x8202`)
- USB permissions via udev (see [Hardware setup](docs/HARDWARE_SETUP.md))

## Install (Arch / CachyOS)

**When published on AUR:**

```bash
paru -S --needed python-dacite nanoleaf-kde-sync
paru -Syu
```

**Until AUR account is available — local build from this repo:**

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

See the [User guide](docs/USER_GUIDE.md) for a full walkthrough.

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

## Reset commands

```bash
nanoleaf-kde-sync-reset app-config --stop-runtime
nanoleaf-kde-sync-reset calibration --stop-runtime
nanoleaf-kde-sync-reset diagnostics --stop-runtime
```

## Documentation

- [User guide](docs/USER_GUIDE.md)
- [Hardware setup](docs/HARDWARE_SETUP.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Smoke test](docs/SMOKE_TEST.md)
- [Security](docs/SECURITY.md)
- [Contributing](CONTRIBUTING.md)

Installed packages also ship docs under `/usr/share/doc/nanoleaf-kde-sync/`.

## Release gate

Run `./scripts/release_gate.sh` before tagging a release. CI must be green on `main`.

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

## License

Source-available non-commercial license — see [LICENSE](LICENSE). Redistribution terms apply; read before packaging or mirroring.
