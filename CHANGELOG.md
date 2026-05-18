# Changelog

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
