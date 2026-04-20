# Nanoleaf Screen Mirror for KDE

![CI](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-Source%20Available-blue)
![Version](https://img.shields.io/github/v/release/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE?display_name=tag)

Nanoleaf Screen Mirror for KDE brings Nanoleaf desktop mirroring to Linux on KDE Plasma 6.

It captures the active display, maps sampled colors to Nanoleaf zones, and sends frames to supported Nanoleaf USB devices.

## Documentation

- [Auto backend behavior and probe policies](docs/AUTO_BACKEND.md)
- [Latency plan and tuning guidance](docs/LATENCY_PLAN.md)
- [Troubleshooting guide](docs/TROUBLESHOOTING.md)
- [Hardware setup](docs/HARDWARE_SETUP.md)
- [Smoke test guide](docs/SMOKE_TEST.md)
- [RC test matrix](docs/RC_TEST_MATRIX.md)
- [Contributing](CONTRIBUTING.md)

## Features

- KDE Plasma 6 screen capture support (`auto`, `kwin-dbus`, `kmsgrab`, `xdg-portal`)
- Policy-aware auto backend probing with cache + environment signature tracking
- Nanoleaf USB HID output (`NL82K1` / `NL82K2`)
- Configuration bootstrap and diagnostics commands
- Tray-managed autostart enable/disable with KDE desktop authorization marker
- Guided strip alignment controls (zone count, reverse, offset, preview mapping)
- Display Configurator wizard (first-run + re-open from Settings) for SDR/HDR and behaviour presets
- Preset-driven colour behaviour modes: Default (recommended), Balanced, Dynamic, Hyper
- User-facing HDR tuning controls (transfer, primaries, max nits)
- Optional auto-start mirroring when tray app launches (`start_on_launch`)
- Service entry point for continuous mirroring

## Supported devices

- `NL82K1` (`VID:PID 37fa:8201`)
- `NL82K2` (`VID:PID 37fa:8202`)

## Installation (Arch / CachyOS)

> `python-dacite` may not be available in default pacman repositories on clean Arch/CachyOS installs. Install it with an AUR helper first, then build this package.

```bash
paru -S --needed python-dacite
cd packaging/arch
makepkg -si
```

## Quick start

1. Generate a default configuration:

```bash
nanoleaf-kde-sync-init-config
```

2. Run diagnostics:

```bash
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
```

3. Confirm device IDs in `~/.config/nanoleaf-kde-sync/config.toml`:

- `device_vid = 14330` (`0x37fa`)
- `device_pid = 33282` (`0x8202`) or `33281` (`0x8201`)

4. Start the tray app (recommended) or service directly:

```bash
nanoleaf-kde-sync
# or
nanoleaf-kde-sync-service
```

5. Optional autostart management:

```bash
nanoleaf-kde-sync-autostart status
nanoleaf-kde-sync-autostart enable
nanoleaf-kde-sync-autostart disable
```

## Display configurator and presets

On first launch, the tray app opens a **Display Configurator** wizard after startup.
You can run it again any time from **Settings → Re-run Display Setup** or tray **Display Configurator**.

Wizard flow:
1. **SDR or HDR** selection with plain-English guidance.
2. **Behaviour preset** selection:
   - **Default** (recommended tuned look)
   - **Balanced** (safer/stabler)
   - **Dynamic** (more responsive to vivid accents)
   - **Hyper** (strongest and most reactive)
3. **HDR tuning** (if HDR selected): transfer (`sRGB` vs `PQ`), primaries (`BT.709` vs `BT.2020`), and `HDR max nits`.

   > **Note**: In `config.toml`, `transfer`/`primaries` use lowercase values: `srgb`/`pq`, `bt709`/`bt2020`.

Tooltip help is included in Settings for these display fields.

## Capture backends and auto policy

### Backend tradeoffs

- `kmsgrab`: often the fastest path when DRM/KMS access and bindings are available.
- `kwin-dbus`: compatibility-first KDE path using `org.kde.KWin.ScreenShot2`.
- `xdg-portal`: portable launch-context/compositor path through ScreenCast portal permissions.

### `auto` is policy-aware (not capability-only)

When `prefer_backend = "auto"`, backend selection uses:

1. **Policy gate** (`auto_probe_policy`): decides *when* to run a fresh probe.
2. **Cached winner** (`auto_selected_backend`): reused when policy says no fresh probe.
3. **Probe result or fallback**: fresh probe picks a winner if one qualifies; otherwise capability fallback applies.

Supported policies:

- `first-run`: probe only when there is no cached winner.
- `each-boot`: probe once at process boot, then reuse result for the process lifetime.
- `on-change` (default): probe when the environment signature changes, or cache is missing.

Cache metadata fields:

- `auto_selected_backend`
- `auto_probe_signature`
- `auto_probe_timestamp`

Probe can be disabled by config/env kill-switch:

- `auto_probe_enabled = false`
- `NANOLEAF_DISABLE_CAPTURE_PROBE=true`
- `NANOLEAF_ENABLE_CAPTURE_PROBE=false`

If probe is disabled or no candidate qualifies, `auto` falls back to capability detection:

- `kmsgrab` when DRM/KMS device + bindings are available
- otherwise `kwin-dbus`

See [`docs/AUTO_BACKEND.md`](docs/AUTO_BACKEND.md) for full behavior and reset workflow.

## Developer quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
pytest -q
```

## Troubleshooting highlights

See the full guide at [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

- **No frame capture**: Ensure you are running KDE Plasma 6 on Wayland and accepted capture permissions.
- **Probe metadata looks stale**: reset auto-probe cache metadata and retry (see troubleshooting reset workflow).
- **KWin ScreenShot2 authorization errors** (`...NoAuthorized` / `...NotAuthorized`):
  launching `nanoleaf-kde-sync-service` directly from a terminal can be denied by KDE policy.
  If diagnostics show `DESKTOP_STARTUP_ID=unset` and `XDG_ACTIVATION_TOKEN=unset`,
  start from the installed desktop entry/tray flow so KDE can apply the
  `X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2` authorization context.
- **USB permission denied**: Install/reload the udev rule with the helper script:

  ```bash
  ./scripts/setup_udev.sh
  ```

  Then unplug and reconnect the device.

- **Zone order mismatch**: Open tray **Settings** and use the Zone alignment preview while tuning reverse/offset.
- **HDR looks washed out or too dim**: Open tray **Settings** and adjust HDR transfer/primaries/max nits.

## Supported environment

- Linux
- KDE Plasma 6 (Wayland recommended)
- Nanoleaf USB device with a supported VID/PID
