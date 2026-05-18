# Full Repo Audit: Nanoleaf-Screen-Mirror-for-KDE v1.2.1+

Audit date: 2026-05-18
Files audited: 68 Python source files, 68 test files, pyproject.toml, CI config
Scope: bugs, dead code, performance, color accuracy, inconsistencies, QoL

---

## EXECUTIVE SUMMARY

The codebase is well-structured with clear separation of concerns (capture → processing → USB output), 4 capture backends, ~22 CLI tools, and strong test coverage (68 test files, 70% line coverage floor). Code quality is generally high with typed annotations, dataclass usage, and structured error handling.

**Total findings: 56 issues**
- **Bugs (critical):** 3 P0, 6 P1, 2 P2
- **Bugs (low):** 4 P3
- **Dead code:** 9 items
- **Performance:** 5 items
- **Color accuracy:** 3 items
- **Inconsistencies:** 6 items
- **QoL:** 15 items

---

## COMPLETE FINDINGS

### BUGS

#### CB1 (P0) — `migrate_config_dict` unconditionally overwrites `calibration_model`

**File:** `config/normalize.py:83-84`

`migrate_config_dict()` is called on every `ConfigManager.load()`. It always sets `calibration_model = "corner_anchored"` regardless of current value. If a user has a different calibration model, loading (e.g., after settings change) silently resets it.

```python
migrated["calibration_model"] = "corner_anchored"
```

**Evidence:** `confirmed` — visible in code, called from `ConfigManager.load()` line 65.

---

#### CB2 (P0) — Hable tonemap applied to SDR boost compensation shifts colors

**File:** `runtime/compositor.py:32-34`

When `sdr_boost_nits > 80` (e.g., 120 nits), `apply_sdr_boost_compensation` applies the full Hable filmic tonemap to SDR content. For pure SDR luminance boosting on HDR displays, a simple linear scale + clamp would be more predictable. The Hable curve compresses highlights and shifts midtones even at modest boosts (e.g., `boost=1.5`).

**Evidence:** `inferred` — Hable is designed for HDR→SDR tone-mapping, not SDR luminance boosting.

---

#### CB3 (P0) — `close()` not in `CaptureBackend` protocol; `KMSGrabCapture` leaks resources

**File:** `capture/interfaces.py:8-24` + `capture/kmsgrab.py:26-244`

`CaptureBackend` protocol only requires `capture()`. `close()` is optional (checked via `getattr`). `KMSGrabCapture` lacks `close()`, so its `_fallback` (a `KWinDBusScreenshotCapture` instance with its own asyncio event-loop thread) leaks when discarded. The factory uses `getattr` for `close()`, so the leak is silent.

**Evidence:** `confirmed` — `KMSGrabCapture` has no `close()` method, `interfaces.py` doesn't require it.

---

#### CB4 (P1) — `close()` in kwin_dbus races with `capture()` due to missing lock

**File:** `capture/kwin_dbus.py:195-221`

`close()` sets `self._loop = None` without acquiring `self._loop_lock`. If `capture()` → `_run_async()` runs concurrently, `_ensure_background_loop()` returns `None` and `asyncio.run_coroutine_threadsafe(coro, None)` crashes with `AttributeError`.

**Evidence:** `confirmed` — `_loop_lock` only used inside `_ensure_background_loop`, not in `close()` or `capture()`.

---

#### CB5 (P1) — kwin_dbus `_loop_worker` catches `BaseException`, swallowing `KeyboardInterrupt`

**File:** `capture/kwin_dbus.py:190`

```python
except BaseException as exc:
```

Catches `KeyboardInterrupt` and `SystemExit`, preventing clean interpreter shutdown. These should propagate.

**Evidence:** `confirmed` — `BaseException` includes `KeyboardInterrupt`/`SystemExit`.

---

#### CB6 (P1) — `_read_fd_exact` silently returns truncated data on short read

**File:** `capture/kwin_dbus.py:550-557`

When `os.read()` returns fewer bytes than requested and then returns `b""` (EOF), the loop breaks and returns `bytes(view[:read_total])` — a partial buffer. Caller at line 636-639 detects "shorter than expected" but misdiagnoses the cause.

**Evidence:** `confirmed`

---

#### CB7 (P1) — Auto-probe warmup latency counted in measurement samples

**File:** `capture/auto_probe.py:117-123`

Warmup capture latency is appended to `stats.latencies_ms` (shared list with measurement samples). Warmup is typically much slower (cold cache, first D-Bus call), skewing `median_ms`, `p95_ms`, and `jitter_ms`.

**Evidence:** `confirmed`

---

#### CB8 (P1) — `_benchmark_backend` reports `conversion_ms` as trivial attribute access

**File:** `capture/factory.py:383-391`

`conversion_ms` measures `frame.size <= 0`, `frame.nbytes`, `frame.ndim`, `frame.shape`/`strides` — O(1) numpy attribute reads, not actual conversion. The metric name is misleading for diagnostics.

**Evidence:** `confirmed`

---

#### CB9 (P1) — Smoke test capture backend resource leak on failure

**File:** `tools/smoke_test.py:97-115`

When `capture.capture()` raises, the `except` block runs and exits without closing the capture backend object created at line 70. Leaks DBus connections, portal sessions, or GPU buffer handles depending on backend.

**Evidence:** `confirmed` — `finally` block at line 148 is attached to a different `try` block, never reached if capture fails.

---

#### CB10 (P2) — kwin_dbus resize index cache not cleared on `close()`

**File:** `capture/kwin_dbus.py:94-95`

The bounded LRU `_resize_index_cache` persists after `close()`. If the backend is re-initialized with different dimensions, stale entries remain. Minor leak (~2KB max).

**Evidence:** `confirmed`

---

#### CB11 (P2) — xdg_portal `pipeline` may be unbound if `Gst.parse_launch` raises

**File:** `capture/xdg_portal.py:535-555`

If `Gst.parse_launch(pipeline_desc)` raises, `pipeline` is never assigned. The `except` block tries `pipeline.set_state(Gst.State.NULL)` → `NameError`. Silently caught by inner `except Exception: pass`, but a `NameError` is raised and swallowed.

**Evidence:** `confirmed`

---

#### CB12 (P3) — Empty `_MIGRATIONS` dict — version-based migration is a no-op

**File:** `config/normalize.py:92,98-104`

`_MIGRATIONS = {}` — the version-increment loop iterates zero slots. The infrastructure exists but does nothing.

**Evidence:** `confirmed`

---

#### CB13 (P3) — `last_reinit_ts` not reset in `RuntimeState.reset_for_start()`

**File:** `runtime/state.py:39,60-92`

`last_reinit_ts` retains its old value after restart. Callers likely check `is_reinitializing` first so this may not cause bugs, but it's inconsistent with the reset contract.

**Evidence:** `confirmed`

---

#### CB14 (P3) — `failure_count` stale between warmup error and post-hoc correction

**File:** `capture/auto_probe.py:114,124-125,150-153`

`stats.attempted_captures` is incremented BEFORE warmup capture. If warmup fails, `failure_count` is NOT incremented at line 125. Post-hoc correction at lines 150-153 fixes it, but `failure_count` is stale between these points.

**Evidence:** `confirmed`

---

### DEAD CODE

#### DC1 — Three wrapper functions in hdr.py never called

**File:** `color/hdr.py:104-115`

```python
_srgb_u8_to_linear01()   # delegating wrapper
_linear01_to_srgb_u8()    # delegating wrapper
_srgb_eotf_to_linear()    # delegating wrapper
```

All three only delegate to `srgb.py` functions. Never called.

**Evidence:** `confirmed`

---

#### DC2 — `LAYOUT_PRESETS` imported but never referenced

**File:** `config/normalize.py:12`

Imported at module level but never used in any function body.

**Evidence:** `confirmed`

---

#### DC3 — `_percentile` duplicates auto_probe's `_compute_p95`

**File:** `capture/factory.py:344-349`

`_percentile()` is a private helper used only in `_benchmark_backend` (P95 calc). Same function exists in `auto_probe.py` with slightly different method.

**Evidence:** `confirmed`

---

#### DC4 — `_jitter` is a trivial one-liner

**File:** `capture/factory.py:352-355`

```python
def _jitter(values):
    return max(values) - min(values)
```

Called once. Could be inlined.

**Evidence:** `confirmed`

---

#### DC5 — `is_supported_real_backend` never called

**File:** `capture/backend_selection.py:37-38`

Exported function that is never imported or called anywhere in the codebase.

**Evidence:** `confirmed`

---

#### DC6 — `_resize_to_target` duplicated between kmsgrab.py and kwin_dbus.py

**File:** `capture/kmsgrab.py:217-239`, `capture/kwin_dbus.py:789-801`

23 lines of identical nearest-neighbor resize logic with index caching, copy-pasted across two files.

**Evidence:** `confirmed`

---

#### DC7 — `_effective_runtime_zone_count` duplicated between doctor.py and smoke_test.py

**File:** `tools/smoke_test.py:23-30`, `tools/doctor.py:48-55`

Identical function in two files.

**Evidence:** `confirmed`

---

#### DC8 — Dead `mapping_preview_text` wrapper in settings_dialog.py

**File:** `ui/settings_dialog.py:107-108`

One-line pass-through to imported `_mapping_preview_text`. Never called through the wrapper.

**Evidence:** `confirmed`

---

#### DC9 — Silent no-op `_Fallback*` classes in settings_dialog.py

**File:** `ui/settings_dialog.py:78-103`

`_FallbackLayout`, `_FallbackWidget`, `_FallbackScrollArea` silently swallow all `addWidget`, `addLayout`, `setLayout` calls. If a Qt widget type isn't in `load_qt()`, the section becomes invisible without error.

**Evidence:** `confirmed`

---

### PERFORMANCE ISSUES

#### P1 — Hable tonemap per-frame when SDR boost active

**File:** `runtime/compositor.py:32-34`

If user is on HDR display with SDR boost > 80 nits, the full Hable tonemap runs every frame. LUT caching would skip recomputation when `hdr_max_nits` doesn't change.

---

#### P2 — Oklch per-pixel conversion on full-resolution frames

**File:** `runtime/color_processing.py:102-109`

`srgb_u8_to_oklch` does `np.cbrt`, `np.sqrt`, `np.arctan2` per pixel per frame. If capture is 1080p, that's ~2M pixels × these operations per frame.

---

#### P3 — 2-4 HID round-trips on first `set_zone_colors` call

**File:** `device/usb_driver.py:144-160`

First frame after startup makes `initialize()` + `get_on_off_state()` + `get_brightness()` round-trips before sending any zone colors.

---

#### P4 — xdg_portal `VideoInfo.new_from_caps()` called per frame

**File:** `capture/xdg_portal.py:739-744`

GStreamer caps metadata extracted on every successful sample pull (up to 60 FPS).

---

#### P5 — Legacy D-Bus introspection re-done every `capture()` call

**File:** `capture/kwin_dbus.py:401-432`

Legacy D-Bus path fetches fresh introspection XML on every capture. ScreenShot2 path caches correctly.

---

### COLOR ACCURACY ISSUES

#### CA1 — Hable tonemap for SDR boost alters colors unpredictably

**File:** `runtime/compositor.py:32-34` (same as CB2)

---

#### CA2 — No ICC profile / display gamut integration

Entire pipeline assumes sRGB input and output. No `colord` or EDID gamut query for wide-gamut displays.

---

#### CA3 — Neutral luminance adjustment in OKLab doesn't preserve hue

**File:** `runtime/color_processing.py:194-196`

Adjusting L without adjusting a/b shifts hue for near-dark neutral colors.

---

### INCONSISTENCIES

#### I1 — `RGBTuple` type alias redefined in two files

**File:** `runtime/processing.py:10` + `runtime/state.py:12`

---

#### I2 — Default VID/PID in model.py differs from protocol.py documented values

**File:** `config/model.py:114-115` (0x37FA:0x8202) vs protocol.py (0x3311, 0x0002/0x0003)

---

#### I3 — Dual calibration field storage (top-level + nested CalibrationConfig)

**File:** `config/model.py:141-154, 176-197`

`corner_anchor_*`, `reverse_zones`, `calibration_model`, `output_channel_order`, `device_zone_count` exist as both `AppConfig` top-level AND `CalibrationConfig` nested fields.

---

#### I4 — Mixed PEP 604 and typing module type hints in state.py

**File:** `runtime/state.py:25-30` vs `46,50`

Some `Optional[X]`, others `X | None`.

---

#### I5 — doctor.py (64x36) vs smoke_test.py (320x180) probe dimensions

**File:** `tools/doctor.py:389-390` vs `tools/smoke_test.py:19-20`

---

#### I6 — Explicit `kmsgrab` selection silently falls back to kwin-dbus

**File:** `capture/kmsgrab.py:79-92`

When user explicitly selects `kmsgrab` but DRM/KMS fails, it silently returns KWin D-Bus frames.

---

### QOL ISSUES

#### Q1 — mypy only checks `runtime/` directory

**File:** `pyproject.toml` — `files = ["src/nanoleaf_sync/runtime"]`

---

#### Q2 — Coverage omits all UI code

**File:** `pyproject.toml` — `omit = ["src/nanoleaf_sync/ui/*"]`

---

#### Q3 — No pre-commit hooks or CI format enforcement

No `.pre-commit-config.yaml`. CI ruff only on `E9,F63,F7,F82`.

---

#### Q4 — Config schema has no version field

`_MIGRATIONS = {}` and no `schema_version` field on `AppConfig`.

---

#### Q5 — Config path discovery duplicated

**File:** `service.py` + `config/store.py`

---

#### Q6 — Thread naming still partial

Some threads named, many anonymous.

---

#### Q7 — Token exposure in tray startup notification

**File:** `ui/tray_app.py:345-355`

`DESKTOP_STARTUP_ID` and `XDG_ACTIVATION_TOKEN` shown in tray popup.

---

#### Q8 — Settings dialog `display_preset_combo` has no signal binding

**File:** `ui/settings_dialog.py:167`

---

#### Q9 — `layout_preset` string mismatch kills source-zone lock

**File:** `ui/settings_dialog.py:160` checks `"edge-weighted"`, code sets `"edge_strip"`.

---

#### Q10 — Fragile combo text parsing

**File:** `ui/settings_dialog.py:689` — `.split(" ", 1)[0]`

---

#### Q11 — No structured logging / correlation ID

---

#### Q12 — `compositor_hdr_mode_checkbox` missing tooltip

**File:** `ui/settings_dialog.py:172`

---

#### Q13 — `device_zone_count_max` hardcoded to 128

**File:** `ui/settings_dialog.py:1090-1091`

---

#### Q14 — Auto-turn-on behavior in `set_zone_colors`

**File:** `device/usb_driver.py:154-155`

---

#### Q15 — Private API access across modules

**File:** `service.py:84-85` — `capture_factory._has_drm_device()` with `# noqa: SLF001`

---

## PHASED IMPLEMENTATION PLAN

### Phase 0: Quick Fixes (all P0 + trivia)

Estimated effort: ~1 hour

| ID | File | Change |
|----|------|--------|
| CB1 | `config/normalize.py:83-84` | Guard calibration_model overwrite with version check |
| CB10 | `capture/kwin_dbus.py:94-95` | Clear resize_index_cache in close() |
| DC1 | `color/hdr.py:104-115` | Remove 3 dead wrapper functions |
| DC2 | `config/normalize.py:12` | Remove unused LAYOUT_PRESETS import |
| DC5 | `capture/backend_selection.py:37-38` | Remove dead is_supported_real_backend |
| DC8 | `ui/settings_dialog.py:107-108` | Remove dead wrapper |
| I4 | `runtime/state.py` | Normalize type hints to PEP 604 |
| Q7 | `ui/tray_app.py:345-355` | Remove tokens from tray notification |

### Phase 1: Bug Fixes (P0-P1)

Estimated effort: ~4 hours

| ID | File | Change |
|----|------|--------|
| CB2 | `runtime/compositor.py:32-34` | Replace Hable with linear scaling for SDR boost |
| CB3 | `capture/interfaces.py:8-24` + `kmsgrab.py` | Add close() to protocol + KMSGrabCapture |
| CB4 | `capture/kwin_dbus.py:195-221` | Add _loop_lock to close() |
| CB5 | `capture/kwin_dbus.py:190` | BaseException → Exception |
| CB6 | `capture/kwin_dbus.py:550-557` | Short-read check/retry in _read_fd_exact |
| CB7 | `capture/auto_probe.py:117-123` | Separate warmup from measurement |
| CB8 | `capture/factory.py:383-391` | Fix conversion_ms metric or rename |
| CB9 | `tools/smoke_test.py:97-115` | Add capture.close() in finally |
| Q9 | `ui/settings_dialog.py:160,673,1508` | Fix layout_preset string |

### Phase 2: Performance & Color Accuracy

Estimated effort: ~6 hours

| ID | File | Change |
|----|------|--------|
| P1 | `runtime/compositor.py` | Cache Hable tonemap LUT when hdr_max_nits unchanged |
| P2 | `runtime/engine.py` + `color_processing.py` | Zone sample before Oklch conversion |
| P3 | `device/usb_driver.py:144-160` | Defer init reads to reduce first-frame latency |
| P4 | `capture/xdg_portal.py:739-744` | Cache VideoInfo per caps |
| P5 | `capture/kwin_dbus.py:401-432` | Cache legacy introspection |
| CA1 | `runtime/compositor.py` | Linear scaling for SDR boost |

### Phase 3: Consistency & Debt Reduction

Estimated effort: ~4 hours

| ID | File | Change |
|----|------|--------|
| I1 | `runtime/processing.py`, `state.py` | Extract shared RGBTuple to `color/_types.py` |
| I2 | `config/model.py:114-115` | Verify/fix default VID/PID |
| I3 | `config/model.py` | Consolidate calibration fields to single source |
| I6 | `capture/kmsgrab.py:79-92` | Log warning on fallback from explicit kmsgrab |
| DC6 | `kmsgrab.py` + `kwin_dbus.py` | Extract shared `_resize_to_target` to `capture/_utils.py` |
| DC7 | `doctor.py` + `smoke_test.py` | Extract shared _effective_runtime_zone_count |
| DC3/DC4 | `capture/factory.py` | Inline _jitter, remove _percentile |
| Q10 | `ui/settings_dialog.py:689` | Add try/except around combo parsing |
| Q8 | `ui/settings_dialog.py:167` | Add signal binding for display_preset_combo |

### Phase 4: Infrastructure

Estimated effort: ~3 hours

| ID | Change |
|----|--------|
| Q1 | mypy: `files = ["src/nanoleaf_sync"]` |
| Q2 | Add UI smoke tests or remove UI exclusion |
| Q3 | Add `.pre-commit-config.yaml` + CI enforcement |
| Q4 | Add `schema_version: int = 1` to AppConfig |

### Phase 5: Polish

Estimated effort: ~5 hours

| ID | Change |
|----|--------|
| Q5 | Single config path source of truth in ConfigManager |
| Q6 | Name all anonymous threading.Thread() calls |
| Q11 | Add frame sequence number through log calls |
| Q12 | Add tooltip to compositor_hdr_mode_checkbox |
| Q13 | Make device_zone_count_max dynamic |
| Q14 | Add preference toggle for auto-turn-on |
| Q15 | Expose needed functions as public API |
| CB12 | Populate _MIGRATIONS dict |
| CB13 | Reset last_reinit_ts in reset_for_start() |
| CB14 | Fix failure_count increment ordering in auto_probe |

---

## TOTAL EFFORT ESTIMATE

- **Phase 0:** ~1 hour (8 quick fixes)
- **Phase 1:** ~4 hours (9 bug fixes)
- **Phase 2:** ~6 hours (6 performance/color)
- **Phase 3:** ~4 hours (9 consistency/debt fixes)
- **Phase 4:** ~3 hours (4 infrastructure changes)
- **Phase 5:** ~5 hours (10 polish items)

**Total:** ~23 hours across 46 discrete changes.

---

## CI/VERIFICATION COMMANDS

```bash
# Unit tests + coverage
python -m pytest -q --timeout=60 --timeout-method=thread --durations=25 --cov=nanoleaf_sync --cov-report=term-missing --cov-fail-under=70

# Ruff lint
ruff check src/ tests/ --select E9,F63,F7,F82

# MyPy (expanded scope after Phase 4)
mypy src/nanoleaf_sync --ignore-missing-imports --follow-imports=silent

# Import smoke tests
python -c "from nanoleaf_sync.config.store import ConfigManager; print('import OK')"
python -c "from nanoleaf_sync.runtime.diagnostics_exports import _plot_diag_timeseries; print('import OK')"
python -c "from nanoleaf_sync.capture.interfaces import CaptureBackend; print('import OK')"
```

---

## Freebuff Invocation Snippet

```
@read .opencode/plans/full-audit-2026-05-18.md
Implement Phase 0 and Phase 1 from the audit plan. This covers 17 changes:
- CB1: Guard calibration_model overwrite in config/normalize.py
- CB2: Replace Hable tonemap with linear scaling for SDR boost in runtime/compositor.py
- CB3: Add close() to CaptureBackend protocol and KMSGrabCapture
- CB4: Add _loop_lock to close() in capture/kwin_dbus.py
- CB5: BaseException → Exception in capture/kwin_dbus.py
- CB6: Short-read check in _read_fd_exact in capture/kwin_dbus.py
- CB7: Separate warmup from measurement in capture/auto_probe.py
- CB8: Fix conversion_ms in capture/factory.py
- CB9: Fix capture resource leak in tools/smoke_test.py
- CB10: Clear resize_index_cache in capture/kwin_dbus.py close()
- DC1: Remove 3 dead wrappers in color/hdr.py
- DC2: Remove unused LAYOUT_PRESETS import in config/normalize.py
- DC5: Remove dead is_supported_real_backend in capture/backend_selection.py
- DC8: Remove dead mapping_preview_text wrapper in ui/settings_dialog.py
- I4: Normalize type hints to PEP 604 in runtime/state.py
- Q7: Remove tokens from tray notification in ui/tray_app.py
- Q9: Fix layout_preset string mismatch in ui/settings_dialog.py

Run all verification commands after changes and report results.
```
