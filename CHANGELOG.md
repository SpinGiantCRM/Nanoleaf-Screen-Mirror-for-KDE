# Changelog

## v1.7.0 — KWin-first auto backend, performance profile, balanced defaults

### Features

- Auto capture keeps `kwin-dbus` as the KDE primary backend; `kmsgrab` remains an explicit benchmark option
- Settings performance profile control (`performance` / `balanced` / `quality`) with live preview updates
- Balanced defaults for target FPS (60), sampling quality, and edge locality

### Fixes

- Accuracy mode forces zone sampling stride 1 for tighter colour fidelity
- Stale cached `kmsgrab` probe winners are no longer treated as viable auto selections
- Settings layout widened for calibration and diagnostics labels on compact displays

## v1.6.0 — Colour path diagnostics, portal/KWin capture reliability, palette stability

### Features

- `palette_adaptive` zone sampling with confidence-scored candidates for better highlight handling
- Focused colour-path diagnostics: capture source, portal/KWin backend details, and per-zone pipeline stages
- One-shot colour debug snapshot export (thumbnail, zones JSON, config, backend status, colour context)
- Live diagnostics colour-path panel and expanded per-zone candidate/final columns

### Fixes

- XDG portal captures treated as display-referred sRGB (same safe path as KWin)
- KWin `InvalidScreen` falls back to active screen; stale `kwin-dbus` probe cache invalidated after repeated failures
- Palette algorithm temporal stabilization to reduce frame-to-frame LED flicker
- Output quantization hold diagnostics and per-zone stage RGB tracing when diagnostics enabled

## v1.5.0 — Audit reliability, HDR correctness, and flicker fixes

### Fixes

- KWin captures always treated as display-referred SDR; SDR boost compensation disabled for `kwin-dbus`
- USB HID: no fallback on closed transport after uncertain writes; periodic ACK health checks every 30 frames
- Clear smoothing history on reinit, capture gaps, resolution changes, and source identity shifts
- KWin compositor restart: detect D-Bus owner changes and reset capture bus state before capture
- Skip duplicate unchanged HID frames on static desktops to reduce stop-motion flicker
- Schmidt-trigger near-black stabilization and FPS-scaled output quantization hold
- XDG Portal restore token cleared when reuse is denied

### Diagnostics

- Live diagnostics: HID send policy, stale-output drop rate, and duplicate-output skip count
- KWin-specific HDR informational notes instead of false-positive metadata warnings
- Settings tooltips note when display/HDR options need mirroring restart for full effect

## v1.4.0 — UI polish, pipeline hardening, and security

### Fixes

- HDR tone-map respects **Max nits** again; Settings shows when SDR compensation is suppressed under HDR tone-map
- Low-light and gamut handling refinements; predictive sync and ring-buffer drop accounting improved
- Tray copy: **Advanced → Troubleshooting Guide**, **Set up strip…**; simplified status tooltip
- Calibration preview surfaces USB/HID guidance instead of raw diagnostic blobs

### UX

- Tray menu stretches to content width; About/Status technical details collapsible
- **Command results** dialog for Doctor/Smoke output (Copy/Close)
- Settings unsaved-changes guard on Close; Advanced decluttered; tighter button/menu styling
- Live Diagnostics: priority status, optional advanced counters, stale-refresh banner
- Advanced: optional custom USB VID/PID when explicitly enabled

### Security

- KWin capture: dimension/byte caps; screenshot paths confined to `$XDG_RUNTIME_DIR` / `/tmp`
- KMS grab: DRM card path must match `/dev/dri/cardN`
- USB VID/PID allowlist with opt-in custom IDs; wizard session path confined unless env override
- Portal token file written with `0600` permissions
- Diagnostics exports use per-export temp dirs; status export strips live frame RGB

## v1.3.0 — Colour stability, spatial isolation, and runtime polish

### Fixes

- Partial-bright scenes no longer tint the whole strip: dark zones skip neighbour spread, achromatic-only dark hold, and faster dark release
- UI overlay / mixed-content zones use area-average or dark-biased sampling instead of vivid peak-pick flicker
- HDR dark flicker: pipeline reorder, letterbox-aware sampling, linear SDR boost undo, and near-black output gating
- Hue-oscillation hold and predictive-sync guards reduce indecisive colour flipping on static UI
- HID open failures now detect when another process (e.g. Steam/Wine) holds `/dev/hidrawN` and surface clearer guidance
- Linux HID open resolves sysfs `hidraw` paths when enumeration returns USB interface tokens

### Runtime

- Predictive sync for 4D mode when frames are stale (with dark-zone and UI guards)
- Capture worker poll interval tuned for lower handoff latency
- FPS governor and latency export diagnostics extended
- Expanded regression tests for neighbour blend, dark output, mixed sampling, and colour pipeline

## v1.2.0 — Pixel sampling accuracy

### Fixes

- Improved edge/zone pixel sampling accuracy for screen mirroring

## v1.1.0 — Settings UX and mirroring resume

### Fixes

- Mirroring no longer shows setup/calibration preview patterns after closing Settings or Display Setup
- Resume mirroring with a fresh service and real screen capture after preview tests
- Wizard finish enables real screen capture instead of leaving mock capture on

### UX

- Settings reorganized into five focused pages (Everyday, Strip setup, Fine-tuning, Colour, Advanced)
- Settings Save persists config without restarting until the dialog closes
- Tray menu: **Set up strip…** label; redundant Advanced Settings entry removed
- Setup wizard step 1 promotes strip count; technical details collapsed
- Pause/resume feedback when strip tests pause mirroring

## v1.0.0 — Public launch

First public release of Nanoleaf Screen Mirror for KDE.

### Features

- Real-time edge/zone screen mirroring to Nanoleaf USB strips on KDE Plasma 6 (Wayland)
- Tray app with settings, setup wizard, calibration, and diagnostics
- Capture backends: KWin DBus (preferred) with portal/kmsgrab fallbacks
- Arch/CachyOS packaging via PKGBUILD and local build scripts

### Quality & security

- Hardened CI: Semgrep, CodeQL, dependency review, Dependabot, bandit, pip-audit, gitleaks
- Security regression tests for doc paths, config writes, and HID validation
- Headless Qt tests for critical tray/settings flows
- User documentation shipped in the Arch package

### Fixes in this release

- Settings Save + Close no longer double-restarts mirroring
- Troubleshooting guide opens correctly from installed packages
- Setup wizard cancel copy clarifies draft-saving behavior
