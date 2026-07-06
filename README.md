# Nanoleaf Screen Mirror for KDE

[![CI](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/workflows/ci.yml/badge.svg)](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE)](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/releases)
[![PyPI](https://img.shields.io/pypi/v/nanoleaf-kde-sync)](https://pypi.org/project/nanoleaf-kde-sync/)
[![Python](https://img.shields.io/pypi/pyversions/nanoleaf-kde-sync)](https://pypi.org/project/nanoleaf-kde-sync/)
[![License](https://img.shields.io/github/license/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE)](LICENSE)
[![KDE Plasma 6](https://img.shields.io/badge/KDE%20Plasma-6-blue)](https://kde.org/plasma-desktop/)

Mirror your screen edge colours to a supported Nanoleaf USB light strip on KDE Plasma 6.

Built for:

- KDE Plasma 6 on Linux
- Wayland sessions
- Nanoleaf USB strips NL82K1 / NL82K2
- Single-monitor edge mirroring

The app runs from your system tray, guides you through strip setup, lets you calibrate corner mapping, and includes diagnostics when capture, USB, or colour output needs fixing.

## Works best with / not supported yet

**Works best with:**

- KDE Plasma 6 (Wayland recommended)
- Nanoleaf USB strips: `NL82K1` (`0x37fa:0x8201`) or `NL82K2` (`0x37fa:0x8202`)
- Single-monitor setups

**Not supported yet:**

- Multi-monitor mirroring
- Multiple strips
- Non-KDE desktops as the primary target

## Privacy and safety

This app reads your screen locally through KDE capture APIs and sends colour values to a supported USB HID strip. It does not run a network server. Diagnostics exports are local and should be reviewed before sharing. See [Security](docs/SECURITY.md) for the full threat model.

## Install

**Recommended:**

```bash
pipx install nanoleaf-kde-sync
nanoleaf-kde-sync-setup-permissions
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync
```

After installing permissions, log out and back in, then reconnect the strip.

On distros without PEP 668 restrictions you can use `pip install nanoleaf-kde-sync` instead of pipx.

Arch package maintainers: see [docs/PACKAGING_AUR.md](docs/PACKAGING_AUR.md) for local build and AUR publish steps.

## Quick start

| Step | Command / action | What should happen |
| ---- | ---------------- | ------------------ |
| 1 | `pipx install nanoleaf-kde-sync` | CLI commands become available |
| 2 | `nanoleaf-kde-sync-setup-permissions` | udev rules installed; DRM setcap command printed if needed |
| 3 | Log out/in, reconnect strip | USB permissions take effect |
| 4 | `nanoleaf-kde-sync-doctor` | Device/capture checks show OK or clear fixes |
| 5 | `nanoleaf-kde-sync` | Tray icon appears |
| 6 | Tray → **Set up strip…** | Wizard completes; test pattern reaches the strip |
| 7 | **Start** | LEDs follow screen edges |

Optional first-run helpers:

```bash
nanoleaf-kde-sync-init-config
nanoleaf-kde-sync-smoke-test
```

Service-only mode:

```bash
nanoleaf-kde-sync-service
```

## If something looks wrong

1. Open tray → **Help & Diagnostics**
2. Click **Refresh**
3. Export a support bundle if asking for help
4. Use **Reset** only if calibration or config is clearly broken

See [Troubleshooting](docs/TROUBLESHOOTING.md) for symptom-based guidance.

## Core commands

- `nanoleaf-kde-sync` — tray app (recommended)
- `nanoleaf-kde-sync-setup-permissions` — install udev rules and print DRM helper guidance
- `nanoleaf-kde-sync-doctor` — environment/device diagnostics
- `nanoleaf-kde-sync-smoke-test` — quick functional sanity check
- `nanoleaf-kde-sync-init-config` — generate default config
- `nanoleaf-kde-sync-service` — headless runtime service
- `nanoleaf-kde-sync-autostart` — manage KDE autostart integration
- `nanoleaf-kde-sync-reset` — reset config/calibration/diagnostic cache safely
- `nanoleaf-kde-sync-benchmark` — synthetic pipeline performance benchmark (developers/diagnostics)

## First-run setup

1. Start the tray app (`nanoleaf-kde-sync`).
2. Complete the setup wizard.
3. Keep **manual strip zone count** set to your real hardware value.
4. Run a calibration test pattern and assign TL/TR/BR/BL anchors.

Manual strip count is authoritative for runtime, mapping, and calibration. Device-reported count is diagnostics-only unless you explicitly apply a new value.

See the [User guide](docs/USER_GUIDE.md) for a full walkthrough. See [Diagnostics](docs/DIAGNOSTICS.md), [Performance](docs/PERFORMANCE.md), and [Roadmap](docs/ROADMAP.md) for advanced topics.

## HDR / SDR notes

- `Display preset = SDR`: SDR-safe defaults.
- `Display preset = HDR`: HDR-first defaults.
- `Display preset = Auto`: follows compositor capability.

On Plasma HDR desktops, verify SDR white reference and compositor HDR settings in app diagnostics before tuning brightness.

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

## Developer / local checkout only

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
pre-commit install
pre-commit run --all-files
```

Udev rules from a git checkout:

```bash
./scripts/setup_udev.sh
```

Pacman-managed reinstall from a local checkout:

```bash
./scripts/reinstall_local.sh
./scripts/uninstall_local.sh
# optional full purge:
./scripts/uninstall_local.sh --purge-config
```

Local Arch package build: `./scripts/build_arch_package.sh`. See [docs/PACKAGING_AUR.md](docs/PACKAGING_AUR.md).

## Release gate

Run `./scripts/release_gate.sh` before tagging a release. CI must be green on `main`.

## License

Source-available non-commercial license — see [LICENSE](LICENSE). Redistribution terms apply; read before packaging or mirroring.
