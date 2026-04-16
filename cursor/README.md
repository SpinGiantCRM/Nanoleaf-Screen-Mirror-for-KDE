# nanoleaf-kde-sync

Nanoleaf ambient light synchronization for KDE/Linux (scaffold + initial framework).

## Install
1. Create/activate a Python 3.11+ environment
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Install the package (optional while developing):
   - `pip install -e .`
   - or install non-editable:
     - `pip install .`

## Run (tray UI)
The project provides a system tray UI that starts/stops the background service:

After install, run:

- `nanoleaf-kde-sync`

Development mode note:
- By default the app uses `use_mock_capture=true` and `use_mock_device=true`, so it runs without DRM/KWin capture bindings or Nanoleaf HID protocol bytes.
- Once you have real capture + official USB protocol, set `use_mock_capture=false` (capture) and `use_mock_device=false` (USB) in `~/.config/nanoleaf-kde-sync/config.json`.
- Real screen capture paths (DRM/KMS, KWin D-Bus) and real Nanoleaf HID report bytes are still placeholders in this scaffold.

## Auto-start (KDE)
1. Copy the provided `.desktop` file into KDE autostart:
   - `cp nanoleaf-kde-sync.desktop ~/.config/autostart/`
2. Log out/in (or reload autostart).

## Config
Persistent settings live at:
- `~/.config/nanoleaf-kde-sync/config.json`

### Calibration knobs (strip mapping)
- `zone_offset`: rotate sampled screen zones onto the physical strip
- `reverse_zones`: flip strip orientation
- `device_zone_count`: number of zones the device expects (0 => use screen zone count)
- `explicit_zone_map`: optional explicit per-device mapping (list of screen-zone indices)

### HDR defaults (used if capture backends don't provide metadata)
- `hdr_transfer`: `"srgb" | "pq" | "hlg" | "linear"`
- `hdr_primaries`: `"bt709" | "bt2020"`
- `hdr_max_nits`: used for tone-mapping into device-friendly sRGB
