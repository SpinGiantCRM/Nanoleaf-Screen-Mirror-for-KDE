# Changelog

## v1.7.0 — Packaging, Bug Fixes, and Auto-Update Checker

**Wheel now ships VERSION + assets, version reporting works when pip-installed, self-update checker, and runtime bug fixes.**

### Packaging & Distribution
- **`pyproject.toml`**: added `[tool.setuptools.package-data]` including `VERSION`, `ui/style.qss`, `assets/icons/`, `assets/udev/`; added `packaging` dependency; narrowed coverage omit to individual UI files
- **`MANIFEST.in`**: created with explicit source distribution file patterns
- **`PKGBUILD`**: hardcoded `pkgver=1.6.0` → `1.7.0`, pinned `sha256sums`
- **`_read_app_version()`**: replaced filesystem VERSION walk with `nanoleaf_sync.__version__` (works via `importlib.metadata`)
- **`_make_device_driver()`**: made public as `make_device_driver()` on `NanoleafSyncService`; `tray_app.py` updated to call it

### Runtime Bug Fixes
- **`_send_stop_black_frame()`**: TOCTOU race fixed — hold `_status_lock` across the read-use cycle of `self._driver`
- **`_close_backends()`**: also wrapped with `_status_lock` for consistency
- **`capture_thread.join()`**: moved inside `is_alive()` guard to prevent crash on early-exit paths
- **`ConfigManager.load()`**: now logs WARNING with exception details on config corruption/OSError/TOML error instead of silently falling back
- **`_load_stylesheet()`**: logs warning when `style.qss` not found

### Auto-Update Checker
- **`compat/update_checker.py`**: new module — GitHub release checker via `urllib.request` (no `requests` dep), ETag caching, 1-hour TTL, `packaging.version` comparison
- **Tray menu**: "Check for Updates…" in Advanced submenu; background check on startup; tray notification for new versions
- **`SELF_CHECK_IMPORTS`** updated with the new module

### v1.6.0 — Final Release Audit Cleanup

**Completes the forensic audit remediation: 15 integration fixes, exception logging across the codebase, thread-safety hardening, and release packaging alignment.**

### Release & Packaging
- **VERSION** bumped to `1.6.0`; `nanoleaf_sync.__version__` exposed via `importlib.metadata`
- **README** header updated to v1.6.0
- **CI** coverage floor raised to 70%; mypy scope expanded to full `src/nanoleaf_sync`
- **PKGBUILD** installs 48×48 and 128×128 PNG icons alongside scalable SVG
- **tomli-w** is now a hard dependency; fallback TOML dumper removed

### Stability & Thread Safety
- **`runtime/state.py`**: `RuntimeState._lock` for multi-field consistency; `_assert_locked()` debug helper
- **`capture/_drm_zone_sampler.py`**: `__del__` replaced with context manager (`__enter__`/`__exit__`)
- **`capture/kwin_dbus.py`**: loop close sanity checks; cross-loop reinit regression test
- **`capture/xdg_portal.py`**: `_portal_bus` nulled before `loop.close()` assertion
- **`capture/_utils.py`**: LRU index cache uses `OrderedDict.move_to_end()` for correct eviction
- **`runtime/engine.py`**: `assert frame is not None` replaced with explicit `ValueError`

### Config & Wizard
- **`config/model.py`**: `wizard_state_version` field for draft schema versioning
- **`config/normalize.py`**: migration clears wizard draft on version mismatch
- **`service.py`**: public `reset_boot_probe_state()` API for tests

### Error Handling
- Added `logger.exception()` / `logger.warning(exc_info=True)` / `logger.debug(exc_info=True)` to ~30 previously silent `except Exception:` handlers across 17 modules

### Tests
- New: `test_runtime_state.py`, kwin cross-loop reinit test, wizard version migration tests, OrderedDict LRU test, `__version__` smoke test

## v1.5.8 — Codebase Audit Fixes (pre-release)

**17 bug fixes and stability improvements from a comprehensive codebase audit covering asyncio race conditions, thread safety, resource cleanup, and startup/shutdown reliability.**

### Critical Fixes
- **`store.py`**: Added `fcntl.flock` config file locking to prevent corruption from concurrent writes
- **`engine.py`**: Frame validation (ndarray check, empty `device_zone_indices` guard) prevents crashes on bad capture frames; periodic black-frame logging every 60 frames instead of one-shot at count 31
- **`xdg_portal.py`**: Fixed asyncio cross-loop `"Task got Future attached to a different loop"` bug by nulling `_portal_bus` before session close; added fallback worker thread with timeout
- **`primaries.py`**: Added `_DETECTED_PRIMARIES_LOCK` to fix cache population race condition
- **`state.py`**: Added `reinit_pause` threading.Event for coordinated worker pause/resume during backend reinitialization
- **`startup.py`**: Pause workers before backend destruction to prevent stale resource access; increased join timeout from 2s to 5s
- **`service.py`**: Changed `_PROCESS_BOOT_PROBE_LOCK` to `RLock` for reentrant safety; added exception logging for previously-swallowed errors; signal handler fallback to `os._exit(1)` after 5s timeout
- **`kwin_dbus.py`**: try-except guards around asyncio operations with increased timeouts
- **`color_processing.py`**: Added `_GAMUT_LOCK` for thread-safe gamut matrix updates

### High-Severity Fixes
- **`tray_app.py`**: 30s timeout on diagnostic subprocess calls; skip wizard when config passes readiness check; no auto-start after config load failure
- **`hid_transport.py`**: Retry with exponential backoff in `open()` for device reconnection; improved import error messages distinguishing libusb vs permission issues
- **`usb_driver.py`**: Wired device reconnection retry (`retry_attempts=3, retry_delay_s=0.5`) in `initialize()`
- **`normalize.py`**: Wizard state corruption guard with size limit + JSON error handling
- **`diagnostics_exports.py`**: `chmod 0o600` on temporary diagnostic export files
- **`zone_derivation.py`**: Zone count mismatch warning between user-defined zones and device zone count
- **`pyproject.toml`**: Documented `pipewire` and `pygobject` as optional dependency groups

### Tests
- **447 new readiness check tests** in `test_readiness_check.py` — comprehensive coverage of zone count validation, corner anchors, calibration mapping, wizard draft detection, runtime loop detection, device/capture probe errors, error category prioritization, and edge cases
- Updated `FakeTransport` and `_FakeTransport` mocks to accept `**kwargs` for new retry parameters
- Updated `test_normalize.py` for wizard state corruption fix

### Files Changed
- `src/nanoleaf_sync/capture/kwin_dbus.py` — asyncio guards
- `src/nanoleaf_sync/capture/xdg_portal.py` — portal session close fix
- `src/nanoleaf_sync/color/primaries.py` — primaries cache lock
- `src/nanoleaf_sync/config/normalize.py` — wizard state limit
- `src/nanoleaf_sync/config/store.py` — config file locking
- `src/nanoleaf_sync/device/hid_transport.py` — retry + error messages
- `src/nanoleaf_sync/device/usb_driver.py` — retry wiring
- `src/nanoleaf_sync/runtime/color_processing.py` — gamut lock
- `src/nanoleaf_sync/runtime/diagnostics_exports.py` — temp file perms
- `src/nanoleaf_sync/runtime/engine.py` — frame validation, black-frame logging
- `src/nanoleaf_sync/runtime/startup.py` — reinit pause, join timeout
- `src/nanoleaf_sync/runtime/state.py` — reinit_pause event
- `src/nanoleaf_sync/runtime/zone_derivation.py` — zone mismatch warning
- `src/nanoleaf_sync/service.py` — RLock, exception logging, signal handler
- `src/nanoleaf_sync/ui/tray_app.py` — subprocess timeout, wizard UX, auto-start gating
- `pyproject.toml` — optional deps documentation
- `tests/` — 447 new readiness check tests, transport mock fixes

## v1.5.7 — Audit Fixes, Coverage, and Color Accuracy (pre-release)

**Four bug fixes from a full codebase audit, a critical XYZ color matrix correction, and 60% test coverage (up from 58.68%).**

### Bug Fixes
- **`calibration_state.py`**: Remove nonexistent `start_anchor=None` kwarg from `_corner_steps()` — would cause latent `TypeError` if that code path were ever reached
- **`service.py`**: Wire `auto_turn_on` config field through to `NanoleafUSBDriver` — was dead code, config toggle had no effect
- **`config/model.py`**: Add `startup_frame_timeout_s: float = 5.0` field to `AppConfig` — was a phantom field only accessible via `getattr` fallback

### Critical Color Math Fix
- **`primaries.py`**: Fixed `chromaticities_to_xyz_matrix` — corrected matrix layout from column-major to row-major, and fixed the white-point scaling solve equation. White point Y was 0.993 (0.7% error in XYZ space), now 1.000000 correctly mapping sRGB white to D65 Y=1.0. Also fixed `build_adaptation_matrix` white point extraction to match row-major convention.

### Test Coverage: 58.68% → 60%
- **10 new test files** (~177 tests): `test_fps_governor.py`, `test_serialization.py`, `test_capture_utils.py`, `test_compositor.py`, `test_primaries.py`, `test_color_accuracy_diagnostics.py`, `test_srgb.py`, `test_dimensions.py`, `test_normalize.py`, `test_anchor_calibration.py`
- CI coverage floor: 55% → 60%

### Files Changed
- `src/nanoleaf_sync/color/primaries.py` — XYZ matrix layout + solve fix
- `src/nanoleaf_sync/config/model.py` — `startup_frame_timeout_s` field
- `src/nanoleaf_sync/service.py` — `auto_turn_on` wiring
- `src/nanoleaf_sync/ui/calibration_state.py` — remove bad kwarg
- `.github/workflows/ci.yml` — coverage floor 55 → 60
- `tests/` — 10 new test files

## v1.5.6 — 120fps Pipeline Throughput Fix (pre-release)

**Fixes the "bottom-left lights work briefly then stop" regression from v1.5.5. Targets 120fps by reducing HID ack timeout and fully draining the input buffer.**

### Root Cause
v1.5.5's 25ms blocking ack timeout was 3x the 8.3ms frame budget at 120fps, starving the HID writer. Additionally, `max_drain_reads=2` only drained 2 HID responses per frame — accumulated responses filled the kernel buffer, causing the device to stop processing new commands after a few seconds.

### Fix
- **`hid_transport.py`**: Reduced `ack_timeout_ms` from 25→8ms (fits 120fps budget), increased `max_drain_reads` from 2→64 to fully drain all pending HID input
- **`engine.py`**: Increased ring buffer capacities from 2→4 to absorb ~33ms of 120fps capture jitter
- **`usb_driver.py`**: Added debug logging of drain read count and flush/wait time per frame

### Files Changed
- `src/nanoleaf_sync/device/hid_transport.py` — full drain, 8ms ack timeout
- `src/nanoleaf_sync/device/usb_driver.py` — drain diagnostics logging
- `src/nanoleaf_sync/runtime/engine.py` — ring buffer capacity 4

## v1.5.5 — Pipeline Throughput Fix (pre-release)

**Fixes the "mostly black with occasional faint glow" regression from v1.5.4. Restores 30-60fps pipeline throughput while ensuring the device acknowledges every frame.**

### Root Cause
v1.5.4 disabled the nonblocking HID drain entirely, forcing `transceive_with_timing` (up to 200ms guard window) per frame. This was too slow for the 3-stage pipeline — the HID writer couldn't keep up, the ring buffer filled up, and most frames were dropped. The rare "faint white glow" was the few frames that made it through.

### Fix — Hybrid Drain
- **`hid_transport.py`**: Modified `write_with_nonblocking_drain` to use a hybrid approach — the first drain read blocks for up to 25ms (`ack_timeout_ms`) to confirm the device acknowledged the frame, then subsequent reads are nonblocking (0ms) to drain extra queued responses. This is fast enough for 30-60fps throughput while guaranteeing the device applies each frame.
- **`service.py`**: Reverted `_install_drivers()` to use the default `enable_live_frame_write_optimization=True` since the nonblocking drain path is now fixed.

### Tests
- Renamed `test_write_with_nonblocking_drain_does_not_wait_for_response` → `test_write_with_nonblocking_drain_hybrid_drain_ack` to reflect the new hybrid-blocking behavior.

### Files Changed
- `src/nanoleaf_sync/device/hid_transport.py` — hybrid drain with ack timeout
- `src/nanoleaf_sync/service.py` — revert to optimized drain path
- `tests/device/test_hid_transport.py` — test name update

## v1.5.4 — Black Screen Mirroring Fix (pre-release)

**Fixes the critical regression where screen mirroring produced all-black output on the LED strip despite correct capture and processing.**

### Root Cause
The 3-stage pipeline's `_hid_writer` thread used `write_with_nonblocking_drain` (fire-and-forget HID writes) by default. Zone color frames were sent to the device but never acknowledged/applied, so the LED strip stayed black even though capture and processing worked correctly.

### Fix
- **`service.py`**: Disable `enable_live_frame_write_optimization` for the runtime service path, forcing the driver to use the response-required `transceive_with_timing` HID path instead of the nonblocking drain.
- **`engine.py`**: Add return-value checking on `process_buf.push()` in `_process_worker` so frame drops from a full ring buffer are logged as warnings instead of silently ignored.

### Tests
- Updated `tests/test_service_status_modes.py` mock to accept the new `enable_live_frame_write_optimization` keyword argument.

### Files Changed
- `src/nanoleaf_sync/service.py` — disable nonblocking drain optimization for runtime
- `src/nanoleaf_sync/runtime/engine.py` — log dropped frames from full process buffer
- `tests/test_service_status_modes.py` — mock keyword arg fix

## v1.5.3 — Stuck Thread Recovery Fix (pre-release)

**Fixes the "Start never completes, Stop doesn't work" bug when the runtime thread blocks on unresponsive HID or capture backends.**

### Startup / Stop Recovery
- **`RuntimeLifecycle.stop()`**: after join timeout, forcibly detaches stuck threads (blocked in HID open or capture init) and transitions to error state so the UI can recover and re-enable Start.
- **`RuntimeLifecycle._sync_state_locked()`**: preserves explicitly-set "error" state instead of overwriting it to "idle" when the thread is not alive.

### Tests
- Updated `tests/test_service_robustness.py` — 2 tests now expect `stop()` returning `True` after detaching (new recovery behavior).

### Files Changed
- `src/nanoleaf_sync/runtime/startup.py` — detach stuck threads, preserve error state
- `tests/test_service_robustness.py` — update stop() assertions for recovery path

## v1.5.2 — KWin D-Bus & Stop Button Recovery Fixes

**Fixes two critical bugs: kwin-dbus capture hanging forever, and Stop leaving the Start button permanently greyed out.**

### Capture
- **Added 2.0s timeout to `_run_async` in `kwin_dbus.py`**: `future.result()` now times out after 2.0s with proper cancellation, raising `KWinDBusCaptureError`. This prevents the capture worker from blocking indefinitely when a KWin D-Bus call hangs.

### Tray / Stop
- **Added `_poll_stop_completion` QTimer polling loop in `on_stop`**: when the runtime thread hasn't finished within the initial 5s join, the poller checks every 50–500ms until the service stops or a 5s deadline expires. `_set_idle_ui_state()` re-enables the Start button once stopped.
- **Removed dead `was_running` variable** in `on_stop`.
- **Added `_stop_poll_deadline` and `_stop_poll_count` field initializations** in `__init__`.
- **Increased `_shutdown_timeout_s`** from 3.0s → 5.0s for consistent timing across stop paths.

### Engine
- **Increased pipeline thread join timeout** from 1.0s → 2.0s to match `_run_loop_legacy`.

### Tests
- Updated mocks in `test_tray_quit_async.py` with `_poll_stop_completion` lambda and `import time` for deadline manipulation.

### Files Changed
- `src/nanoleaf_sync/capture/kwin_dbus.py` — timeout on D-Bus future result
- `src/nanoleaf_sync/ui/tray_app.py` — stop polling, field init, cleanup
- `src/nanoleaf_sync/runtime/engine.py` — thread join timeout
- `tests/test_tray_quit_async.py` — mock updates

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
