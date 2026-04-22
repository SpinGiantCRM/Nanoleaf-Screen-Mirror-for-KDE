# Troubleshooting

## Quick triage

Run:

```bash
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
```

For deeper probes:

```bash
nanoleaf-kde-sync-doctor --capture
nanoleaf-kde-sync-doctor --device
nanoleaf-kde-sync-smoke-test --send-test-frame
```

If command output references `requested=auto` with `selection_reason=fallback`, follow the auto-backend and probe sections below.

## Common issues

### Install-time dependency issue on Arch/CachyOS

If `makepkg -si` fails with an unresolved `python-dacite` dependency, install it first with an AUR helper:

```bash
paru -S --needed python-dacite
cd packaging/arch
makepkg -si
```

### KWin ScreenShot2 authorization errors

If you see `NoAuthorized` / `NotAuthorized` (especially with `DESKTOP_STARTUP_ID=unset` and `XDG_ACTIVATION_TOKEN=unset` in diagnostics), launch from the desktop entry or tray app so KDE policy applies `X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2`.

### No HID device found

1. Confirm USB IDs with `lsusb` (Nanoleaf USB: `37fa:8201` or `37fa:8202`).
2. Ensure the udev rule is installed:

```bash
./scripts/setup_udev.sh
```

3. Reconnect the device.

### Colors look wrong on an HDR display

Open tray **Settings** and adjust:
- HDR transfer (`srgb` / `pq`)
- HDR primaries (`bt709` / `bt2020`)
- HDR max nits

Start with `srgb + bt709` if your desktop is SDR, then tune brightness conservatively.

### Zone order mismatch

Use tray **Settings**:
- Reverse strip orientation
- Zone offset
- Mapping preview line

If the strip is mounted upside-down, enable reverse first, then fine-tune the offset.

If setup was interrupted, reopen the setup wizard. In-progress calibration state is persisted and should resume from the previous phase/step. If the current phase is now inconsistent, use **Reset this section** or the phase-specific **Rollback** controls before continuing.

Quick recovery helper: **If calibration looks wrong, reset the current phase, send a test pattern, then confirm the phase again before moving on.**

### Corner-anchored calibration errors

If the preview shows a corner anchor validation warning:

1. Ensure all four corners (TL/TR/BR/BL) are assigned.
2. Ensure each anchor index is unique.
3. Ensure each anchor index is in range `0..device_zone_count-1`.

Expected behavior: invalid anchors block final completion and emit remediation hints; mapping should fall back safely instead of crashing.

### Calibration config looks stale

If calibration values appear inconsistent after manual edits:

1. Close tray/service.
2. Open `~/.config/nanoleaf-kde-sync/config.toml`.
3. Verify the values under `[calibration]` match your actual strip setup.
4. Start app and verify with:

```bash
nanoleaf-kde-sync-smoke-test
```

Then rerun setup wizard once to re-save a clean calibration payload.

## Auto-backend probe failures

When `prefer_backend = "auto"`, the service chooses backend via policy-aware probing + cache metadata.

Check current metadata:

```bash
nanoleaf-kde-sync-smoke-test
```

Look at:

- `probe config: enabled=<...> policy=<...> cached_winner=<...> signature=<...> timestamp=<...>`
- `backend decision: requested=auto effective=<...> selection_reason=<...>`

### Typical failure modes and fixes

- `selection_reason=fallback` with `effective=kwin-dbus`:
  - likely no valid cached winner + probe disabled/failed + no kmsgrab capability.
  - run with `nanoleaf-kde-sync-doctor --capture` and resolve the reported root cause.
- cached winner is empty (`cached_winner=none`) repeatedly:
  - reset cache and restart service (workflow below).
- probe disabled unexpectedly:
  - inspect config and env:
    - `auto_probe_enabled` in `config.toml`
    - `NANOLEAF_DISABLE_CAPTURE_PROBE`
    - `NANOLEAF_ENABLE_CAPTURE_PROBE`

## Forced backend override

To bypass auto behavior for diagnosis, force an explicit backend in `~/.config/nanoleaf-kde-sync/config.toml`:

```toml
prefer_backend = "kwin-dbus"
# or "xdg-portal" / "kmsgrab"
```

With explicit backend selection, probe status becomes informational and selection reason should be `explicit`.

Use this sequence for A/B comparisons:

1. Set `prefer_backend` to one backend.
2. Restart service/tray.
3. Run `nanoleaf-kde-sync-smoke-test`.
4. Repeat for the next backend.

## Slow path diagnosis

If mirroring works but feels laggy, isolate capture path first:

1. Record current effective path:

```bash
nanoleaf-kde-sync-smoke-test
```

2. Compare explicit backend runs (`kwin-dbus`, `xdg-portal`, `kmsgrab`) as above.
3. Keep all other settings fixed while testing:
   - `fps`
   - `zone_sampling_stride`
   - `smoothing` / `smoothing_speed` (lower `smoothing_speed` = slower response and stronger smoothing; `0.0` is the slowest)

Notes:

- `kmsgrab` is often fastest when available.
- `kwin-dbus` is the KDE compatibility baseline.
- `xdg-portal` is most portable across launch contexts/compositor policies, but may add permission/setup overhead.

If capture is fast but LED response is still delayed, reduce `smoothing` and `zone_sampling_stride` conservatively and retest.

## Probe policy reset workflow

If probe metadata appears stale or inconsistent, clear cache metadata and let policy repopulate it.

### Step 1: reset auto-probe cache fields

```bash
python -c "from nanoleaf_sync.config.store import ConfigManager; ConfigManager().reset_auto_probe_cache()"
```

This clears:

- `auto_selected_backend`
- `auto_probe_signature`
- `auto_probe_timestamp`

### Step 2: restart service/tray

Restart from your usual launch path (tray or service).

### Step 3: verify new decision metadata

```bash
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync-doctor
```

`cached_winner`, `signature`, and `timestamp` should be repopulated after a successful auto decision when `prefer_backend = "auto"`.
