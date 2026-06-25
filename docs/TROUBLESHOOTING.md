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

Important: a shell-launched CLI smoke test is not equivalent to launching from an installed desktop entry. A `kwin-authorization` failure from shell often indicates launch-context limitations, not a broken desktop-entry launch path.

Quick distinction workflow:
1. Run smoke test from shell and note if auth vars are unset (`DESKTOP_STARTUP_ID`, `XDG_ACTIVATION_TOKEN`).
2. Launch from the installed desktop entry/tray and retest.
3. Interpret:
   - fails only from shell launch: launch authorization context limitation
   - fails from desktop-entry launch too: true app/runtime failure on KWin path

### No HID device found

1. Confirm USB IDs with `lsusb` (Nanoleaf USB: `37fa:8201` or `37fa:8202`).
2. Ensure the udev rule is installed:

```bash
./scripts/setup_udev.sh
```

3. Reconnect the device.

### HID device is found but open still fails

Symptoms:
- `hid-device: PASS` with one or more matching devices
- `device-probe: FAIL` with "Failed to open Nanoleaf HID device after enumeration"

Workflow:
1. Re-run:
   ```bash
   nanoleaf-kde-sync-doctor
   nanoleaf-kde-sync-doctor --device
   ```
2. Read `hid-device` details per path/interface:
   - `path=/dev/hidrawN`
   - `interface=<number>`
   - `usage_page` / `usage`
3. Read `device-probe` `Attempt results`:
   - `open_path(...) failed ...` (per-path/interface result)
   - `open(vid, pid) failed ...` (VID/PID fallback result)
4. Interpret:
   - no devices listed: enumeration/hardware visibility issue
   - permission text (`permission denied`, `access denied`): udev/group/ACL issue
   - busy text (`resource busy`, `device or resource busy`): handle held by another process
   - all path opens fail with non-permission errors while ACLs are correct: backend/interface mismatch for this session

Linux backend note:
- If enumeration shows a USB interface token path such as `3-1:1.0` (instead of `/dev/hidrawN`), recent builds now also resolve and attempt the corresponding `/dev/hidrawN` path deterministically before VID/PID fallback.
- Doctor output now includes hid backend module/version and richer per-candidate fields (`bus_type`, `release_number`, strings) to make backend mismatch diagnosis reproducible.

### Colors look wrong on an HDR display

Open tray **Settings** and adjust:
- HDR transfer (`srgb` / `pq`)
- HDR primaries (`bt709` / `bt2020`)
- HDR max nits
- KDE SDR-on-HDR compensation / compositor HDR mode
- SDR white reference

Start with `srgb + bt709` if your desktop is SDR, then tune brightness conservatively.

Display mode quick guide:
- **SDR**: SDR-safe defaults (`srgb + bt709`).
- **HDR**: HDR-first defaults (`pq + bt2020`).
- **Auto**: follows runtime desktop HDR capability.

### Zone order mismatch

Use tray **Settings**:
- Reverse strip direction
- Strip LED zone count and screen sampling zone count
- Diagnostics (for raw mapping preview when needed)

If the strip is mounted upside-down, enable reverse orientation.

If setup was interrupted, reopen the setup wizard. In-progress calibration state is persisted and should resume from the last saved calibration step.

Quick recovery helper: **If calibration looks wrong, reset this section, send a test pattern, and re-assign the corner anchors before moving on.**

### Preset vocabulary (wizard + settings)

The Setup Wizard Step 3 (**Look & Feel**) and the Settings dialog now share the same user-facing preset model:

- **Layout**: `Edge strip` (recommended)
- **Edge locality**: `Balanced` (recommended), `Tight` (precision/debug), `Wide` (softer)
- **Quality**: `Low`, `Balanced`, `High`
- **Motion**: `Calm`, `Responsive`, `Dynamic`
- **Color style**: `Reference`/`Natural` (accurate), `Ambient` (recommended), `Vivid`, `Punchy`
- **Display preset**: `SDR`, `HDR`, `Auto`

`Horizontal` layout remains available only under **Advanced/Diagnostics** as a diagnostic mode and is not recommended for normal lightstrip use.

Advanced/Diagnostics may also expose HDR transfer/primaries/nits and compositor HDR details. The main wizard flow intentionally keeps these collapsed for readability.

### Corner calibration errors

If calibration is not marked **Ready**:

1. Ensure all four corners (TL/TR/BR/BL) are assigned.
2. Ensure each anchor index is unique.
3. Ensure each anchor index is in range `0..device_zone_count-1`.

Expected behavior: invalid anchors block final completion and emit remediation hints; mapping should fall back safely instead of crashing.

### Strip-count mismatch warnings

The app now surfaces clear warnings when strip counts are inconsistent:
- `Configured strip count differs from detected device count.`
- `Changing strip count may require recalibration.`
- `Current anchors were assigned for a different strip length.`

These warnings are informational (not blocking), but you should recalibrate after major strip-count changes.

### Edge locality

**Edge locality** controls how tightly sampled colors stay near their screen position:
- **Tight**: most accurate, least bleed.
- **Balanced**: default trade-off.
- **Wide**: softer, more blended look.

### Diagnostics panel

Diagnostics is intentionally collapsed by default in Wizard + Settings.  
Open it only when troubleshooting backend policy, runtime status, or raw device→source mapping details.

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
  - likely no valid cached winner + probe disabled/failed/no qualified candidate.
  - run with `nanoleaf-kde-sync-doctor --capture` and resolve the reported root cause.
- probe error includes `stage=warmup` / timeout:
  - warmup is reported separately from backend instantiation so startup/permission issues can be distinguished from capture timing.
  - probe timeout cannot forcibly interrupt non-interruptible backend reads (for example HID/driver calls); timeout returns quickly to the probe, while the blocked worker thread exits only when the underlying call returns.
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

- `kwin-dbus` is the KDE primary/default path.
- `kmsgrab` can be benchmarked explicitly, but auto-selection does not promote it.
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

### Canonical reset tool (1.0.0)

Prefer the dedicated reset command for clean, scoped resets:

```bash
nanoleaf-kde-sync-reset diagnostics --stop-runtime
nanoleaf-kde-sync-reset calibration --stop-runtime
nanoleaf-kde-sync-reset app-config --stop-runtime
```

- `diagnostics`: clears probe/latency/wizard draft caches only.
- `calibration`: resets anchor + calibration payload only.
- `app-config`: full config reset.

### Local reinstall / uninstall hygiene

For local editable/dev installs, use:

```bash
./scripts/reinstall_local.sh
./scripts/uninstall_local.sh
./scripts/uninstall_local.sh --purge-config
```

`reinstall_local.sh` stops stale tray/service processes before reinstall to avoid duplicate runtime loops and stale HID handles.

### Step 2: restart service/tray

Restart from your usual launch path (tray or service).

### Step 3: verify new decision metadata

```bash
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync-doctor
```

`cached_winner`, `signature`, and `timestamp` should be repopulated after a successful auto decision when `prefer_backend = "auto"`.


### Colour accuracy diagnostic

From **Settings → Diagnostics**, run both:
- **Run edge locality test** (verifies local edge response and no global bleed).
- **Run colour accuracy diagnostic** (reports input/output RGB, perceptual lightness/chroma, chroma ratio, hue delta, and neutral preservation).

For HDR desktops, verify diagnostics include display preset, compositor HDR mode, effective SDR white reference, and HDR max nits. If grey/neutral edges look dim, first check compositor SDR white reference before increasing global brightness.
