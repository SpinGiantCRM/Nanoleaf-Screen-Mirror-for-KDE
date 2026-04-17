# nanoleaf-kde-sync

`nanoleaf-kde-sync` is a KDE/Linux ambient-light synchronization service for Nanoleaf devices.
It captures screen content, maps dominant colors to configured LED zones, and sends updates through a device backend.

## Project purpose

This project provides a Linux-first path for Nanoleaf screen mirroring with:

- A tray app for start/stop and settings management.
- A background runtime engine for capture → color analysis → zone mapping → device output.
- A mock-first development workflow so the app can run without real capture/device integrations.

## Runtime requirements

- Linux desktop environment with KDE support as the primary target.
- Python **3.11+**.
- Core Python dependencies:
  - `numpy>=1.21`
  - `PyQt6>=6.0`
  - `dbus-next>=0.2.0`
  - `hidapi>=0.14.0`
- For real capture/device operation (non-mock), additional system-level capabilities may be required:
  - KWin D-Bus/Wayland integration and/or DRM/KMS access.
  - USB HID access permissions for the target Nanoleaf device.

## Install

1. Create and activate a Python 3.11+ virtual environment.
2. Install Python dependencies:
   - `pip install -r docs/requirements.txt`
3. Install the package:
   - Editable dev install: `pip install -e .`
   - Standard install: `pip install .`

## Usage

### Start tray UI

After installation:

- `nanoleaf-kde-sync`

This launches the system tray application and lets you control the background sync service.

### Start service entry point directly

- `nanoleaf-kde-sync-service`

### Auto-start in KDE

1. Copy desktop entry:
   - `cp docs/nanoleaf-kde-sync.desktop ~/.config/autostart/`
2. Log out and back in (or otherwise reload autostart entries).

### Configuration location

Persistent config is stored at:

- `~/.config/nanoleaf-kde-sync/config.json`

Useful mapping fields:

- `zone_offset`
- `reverse_zones`
- `device_zone_count`
- `explicit_zone_map`

Useful HDR defaults:

- `hdr_transfer` (`srgb` | `pq` | `hlg` | `linear`)
- `hdr_primaries` (`bt709` | `bt2020`)
- `hdr_max_nits`

## Mock vs real backend behavior

By default, development-safe mock mode is enabled:

- `use_mock_capture=true`
- `use_mock_device=true`

In this mode:

- The app runs without real screen-capture backends.
- Device writes are handled by mock drivers instead of real Nanoleaf HID protocol output.

To switch toward real integrations, set:

- `use_mock_capture=false`
- `use_mock_device=false`

in `~/.config/nanoleaf-kde-sync/config.json`.

## Known limitations

- Real screen capture backends (e.g., full DRM/KMS + KWin paths) are scaffolded and may be incomplete depending on your environment.
- Real Nanoleaf HID protocol behavior is under active development; some implementations are placeholders.
- Linux distribution packaging and permission setup (especially for HID and graphics capture) can vary and may require manual adjustment.
- Hardware-specific timing/latency tuning is not universally optimized yet.

## Support

- Check `docs/TECHNICAL_DESIGN.md` for architecture details and implementation context.
- Check `docs/CHANGELOG.md` for project change history.
- For issues or feature requests, open a ticket in this repository with:
  - Your distro + KDE version.
  - Python version.
  - Whether `use_mock_capture` / `use_mock_device` were enabled.
  - Relevant logs and steps to reproduce.
