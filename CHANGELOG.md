# Changelog

## v1.5.1 — Startup & Shutdown Stability Fixes (pre-release)

**Fixes two critical bugs: startup timeout causing false "failed to produce frame" failures, and stop-mirroring hang when device/capture backends are unresponsive.**

### Engine
- **Fixed indentation bug** in `_run_loop_legacy`: `capture_thread.join(timeout=...)` was inside the while loop (8-space indent), blocking every tick for 1 second — this alone caused repeated "failed to produce frame" failures regardless of timeout
- **Increased `startup_frame_timeout_s`** from 1.5s → 5.0s in both `_run_loop_legacy` and `_run_loop_pipeline`
- **Simplified startup timeout condition**: removed `xdg-portal` exemption check (the longer timeout handles all backends uniformly)

### Shutdown
- **Fixed indefinite hang on stop**: `close_backends()` in `shutdown_backends` now runs in a daemon thread with a 2.0s timeout join, preventing blocking when HID devices or capture backends are unresponsive
- **Wrapped `send_final_frame()`** in try/except to prevent crash during shutdown
- **Increased tray `_shutdown_timeout_s`** from 1.5s → 3.0s to give the runtime thread enough time to complete the shutdown sequence

### Files Changed
- `src/nanoleaf_sync/runtime/engine.py` — indentation fix, timeout increases, simplified condition
- `src/nanoleaf_sync/runtime/startup.py` — shutdown backends timeout thread
- `src/nanoleaf_sync/ui/tray_app.py` — shutdown timeout increase

## v1.5.0 — Frame Validation & Live Diagnostics (pre-release)

**Two-phase pipeline health feature — black-frame detection in the engine, brightness-gated auto-probe ranking, and a real-time Live Diagnostics dialog.**

### Phase 1 — Frame Validation & Auto-Probe Brightness Check
- **New `RuntimeState` fields**: `consecutive_black_frames`, `total_black_frames`, `latest_frame_mean_brightness` — tracked in `__init__`, `reset_for_start()`, and `status_snapshot()`
- **Engine black-frame detection**: `_process_worker` computes `np.mean(frame)` after capture, counts consecutive all-black frames, and logs a warning at 31 consecutive black frames (counter resets on non-black)
- **Auto-probe brightness gating**: `auto_probe.py` captures frame return values from `call_with_timeout()` warmup/capture calls; checks `np.mean < 2.0` for black frames; sets `brightness_ok=False` on probe stats; factors `brightness_ok` into backend ranking (after `qualified`, before score); propagates to `ProbeResult`. Graceful try-except handles non-numpy mock frames
- **`probe_models.py`**: Added `brightness_ok: bool = True` to `CandidateProbeResult` and `ProbeResult`

### Phase 2 — Live Diagnostics Dialog
- **New `src/nanoleaf_sync/ui/live_diagnostics.py`**: `LiveDiagnosticsDialog` with 5 section groups:
  - **Capture** — backend name, method, frame size, mean brightness, consecutive/total black frames
  - **Pipeline** — frames sent, consecutive errors, target/effective FPS, lifecycle state, priority mode
  - **Device** — driver ready, capture backend ready, calibration status/message
  - **Errors** — last error, error kind, guidance, startup elapsed ms
  - **Per-Zone Colors** — collapsible grid showing zone index, side, RGB per zone
- 500ms `QTimer` auto-refresh while mirroring is running; stops timer when mirroring stops (live-only mode)
- **Tray integration**: Added "Live Diagnostics" action to Advanced submenu between Troubleshooting Guide and Run Doctor

### Files Changed
- `src/nanoleaf_sync/runtime/state.py` — 3 new fields
- `src/nanoleaf_sync/runtime/engine.py` — frame brightness validation
- `src/nanoleaf_sync/capture/auto_probe.py` — brightness-gated backend ranking
- `src/nanoleaf_sync/capture/probe_models.py` — `brightness_ok` field
- `src/nanoleaf_sync/ui/live_diagnostics.py` — new live diagnostics dialog
- `src/nanoleaf_sync/ui/tray_app.py` — live diagnostics wiring

## v1.4.0 — UI Beautification (pre-release)

**6-phase UI polish — tray menu restructure, unified settings, embedded calibration, KDE Breeze QSS theming, wizard step indicator, dialog geometry persistence.**

### Phase 1 — Tray Menu Cleanup
- Restructure menu into daily-use top-level actions (Start, Stop, Settings, Calibration/Setup, About/Status) + "Advanced" submenu
- Add system theme icons (`QIcon.fromTheme`) to Start, Stop, Settings, Calibration/Setup, About/Status, Quit
- Merge duplicate Troubleshooting actions into single "Troubleshooting Guide" in Advanced submenu
- Dynamic autostart: show only Enable or Disable toggle based on current filesystem state
- Remove `view_mode` parameter from `on_settings()` and `on_open_advanced_settings()`

### Phase 2 — Remove view_mode Dualism
- Purge `SETTINGS_VIEW_STANDARD` and `SETTINGS_VIEW_ADVANCED` constants
- Remove `view_mode` parameter from `SettingsDialog` constructor; accept `dialog_geometry` instead
- All 6 sections (Display & Color, Performance, Edge Mapping, Calibration, Device, Diagnostics) always visible
- Remove dead `_view_mode` branch and related conditional logic

### Phase 3 — Embed SimpleCalibrationWidget
- Embed `SimpleCalibrationWidget` from `calibration_widget.py` inline in the Calibration section
- Remove dead `display_configurator_button` ("Re-run Display Setup") and `open_calibration_tool_button`
- Add "Open full calibration wizard" button to Calibration section that routes to display configurator

### Phase 4 — KDE Breeze-Compatible QSS Stylesheet
- Create `src/nanoleaf_sync/ui/style.qss` with `palette()`-based neutral theme
- Style QGroupBox, QPushButton, QSlider, QComboBox, QCheckBox, section headings, scroll areas
- Load stylesheet at tray startup via `_load_stylesheet()` before app initialization
- Set `heading` property on section labels so QSS `QLabel[heading="true"]` rule matches

### Phase 5 — Step Indicator
- Display configurator `step_label` already provides step indicator (pre-existing)

### Phase 6 — Persist Dialog Size
- `SettingsDialog.__init__` accepts `dialog_geometry: bytes | None` parameter
- `_Dialog.__init__` restores geometry via `restoreGeometry()` when provided
- Outer `SettingsDialog.exec()` captures geometry via `saveGeometry()` and exposes it via `saved_geometry()`
- `tray_app.py` stores geometry in `_saved_settings_geometry` for persistence across dialog opens

### Files Changed
- `src/nanoleaf_sync/ui/tray_app.py` — menu restructure, icons, autostart, QSS loading, geometry persistence
- `src/nanoleaf_sync/ui/settings_dialog.py` — remove view_mode, embed calibration widget, clean dead code, geometry persistence
- `src/nanoleaf_sync/ui/style.qss` — new KDE Breeze-compatible QSS stylesheet
- `tests/test_tray_menu_structure.py` — update for new menu structure, icons, merged troubleshooting
- `tests/test_settings_dialog.py` — update for removed view_mode

## v1.2.2 — Full Codebase Audit (Phases 0-5)

**46 changes across all modules — bugs, dead code, performance, consistency, infrastructure, and polish.**

### Phase 0 — Quick Fixes (8)
- **CB1**: Guard `calibration_model` overwrite — uses `setdefault` instead of unconditional assignment in `config/normalize.py`
- **CB10**: Clear `_resize_index_cache` in `kwin_dbus.py` `close()` to prevent stale entries on re-init
- **DC1**: Remove 3 dead wrapper functions in `color/hdr.py` (`_srgb_u8_to_linear01`, `_linear01_to_srgb_u8`, dead pass-through)
- **DC2**: Remove unused `LAYOUT_PRESETS` import from `config/normalize.py`
- **DC5**: Remove dead `is_supported_real_backend` from `capture/backend_selection.py`
- **DC8**: Remove dead `mapping_preview_text` wrapper from `ui/settings_dialog.py`
- **I4**: Normalize type hints to PEP 604 (`X | None` instead of `Optional[X]`) in `runtime/state.py`
- **Q7**: Redact `DESKTOP_STARTUP_ID` and `XDG_ACTIVATION_TOKEN` in tray notifications via `redact_launch_token()`

### Phase 1 — Bug Fixes (9)
- **CB2**: Replace Hable filmic tonemap with linear scaling for SDR-on-HDR boost in `runtime/compositor.py` — improves color accuracy and predictability
- **CB3**: Add `close()` to `CaptureBackend` protocol in `capture/interfaces.py` and implement in `KMSGrabCapture` to prevent resource leaks
- **CB4**: Hold `_loop_lock` in `kwin_dbus.py` `close()` to prevent race conditions with concurrent `capture()` calls
- **CB5**: Change `BaseException` to `Exception` in `kwin_dbus.py` loop worker to allow clean `KeyboardInterrupt` propagation
- **CB6**: Raise `KWinDBusCaptureError` on short pipe reads instead of silently returning truncated frames
- **CB7**: Exclude warmup capture latency from measurement stats in `capture/auto_probe.py`
- **CB8**: Set `conversion_ms` to `0.0` instead of measuring trivial numpy attribute access in `capture/factory.py`
- **CB9**: Add `finally` block in `tools/smoke_test.py` to properly close capture and driver resources on failure
- **Q9**: Fix `layout_preset` string mismatch — consistently use `"edge_strip"` across all UI surfaces

### Phase 2 — Performance & Color Accuracy (6)
- **P1/P2/CA1**: Zone sampling happens before Oklch conversion (existing architecture); Hable replaced by linear scaling (CB2) for color-accurate SDR boost
- **P3**: Pre-read device on/off state and brightness during `initialize()` so subsequent `set_zone_colors` calls use cached values
- **P4**: Cache GStreamer `VideoInfo` per caps string in `capture/xdg_portal.py` to avoid repeated parsing at 60 FPS
- **P5**: Cache legacy D-Bus introspection XML in `capture/kwin_dbus.py` to avoid re-introspecting on every capture

### Phase 3 — Consistency & Debt Reduction (9)
- **I1**: Extract shared `RGBTuple` type alias to `color/_types.py`; 6 files updated to import from single source
- **I3**: Add `__post_init__` to `AppConfig` syncing calibration fields for single source of truth
- **I6**: Log warning when `kmsgrab` explicitly selected but falls back to kwin-dbus
- **DC3/DC4**: Inline `_jitter` and `_percentile` dead functions in `capture/factory.py`
- **DC6**: Extract shared `_resize_to_target` to `capture/_utils.py`; deduplicated from `kmsgrab.py` and `kwin_dbus.py`
- **DC7**: Extract shared `effective_runtime_zone_count` to `tools/_utils.py`; deduplicated from `doctor.py` and `smoke_test.py`
- **Q8**: Connect `display_preset_combo.currentIndexChanged` signal to `_refresh_preview_label`
- **Q10**: Add try/except guard around `sdr_white_reference_preset_combo` text parsing

### Phase 4 — Infrastructure (4)
- **Q1**: Expand mypy scope to `files = ["src/nanoleaf_sync"]` in `pyproject.toml`
- **Q2**: Remove UI coverage exclusion (`omit = ["src/nanoleaf_sync/ui/*"]`) from `pyproject.toml`
- **Q3**: Add `.pre-commit-config.yaml` with ruff (lint + format) and mypy hooks; create `.github/workflows/lint.yml` standalone CI workflow; expand CI mypy step to full scope
- **Q4**: Add `schema_version: int = 1` to `AppConfig`; populate `_MIGRATIONS` dict with schema 0→1 migration in `config/normalize.py`

### Phase 5 — Polish (10)
- **Q11**: Add `frame_seq` sequence number flowing through all engine log calls for correlation
- **Q13**: Make `_device_zone_count_max()` dynamic — returns `max(constant, detected + 16)` in settings and display configurator
- **Q14**: Add `auto_turn_on: bool = True` preference toggle in `AppConfig`; `usb_driver.py` checks it before auto-power-on
- **Q15**: Create public `has_drm_device()` / `kmsgrab_bindings_available()` aliases in `capture/factory.py`; update `service.py` to use them (removing `noqa: SLF001`)
- **CB12**: Populate `_MIGRATIONS` dict with schema 0→1 migration step
- **CB13**: Reset `last_reinit_ts` to `0.0` in `RuntimeState.reset_for_start()`
- **CB14**: Fix `failure_count` increment ordering in `capture/auto_probe.py` — increment after actual probe attempt
