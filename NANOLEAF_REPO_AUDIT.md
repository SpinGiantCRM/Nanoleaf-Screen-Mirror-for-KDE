# Nanoleaf Repo Audit

## Executive Summary

**Overall repo health**: Excellent. This is a well-engineered Python/PyQt6 project with clean architecture, thorough testing (1466 passing tests), strong CI/CD, and good security posture. Ruff, mypy, and all checks pass cleanly.

**Biggest confirmed risks**:
1. Portal colour inaccuracy due to GStreamer `videoconvert` colour-matrix heuristics
2. Hardcoded output channel order (`grb`) for all device models with no validation path
3. Gamut adaptation matrix reads without lock, risking data races
4. HDR config defaults are misleading (`display_preset="hdr"` + `compositor_hdr_mode=False`)
5. `fuser -v` parsing is locale-fragile for holder detection

**Biggest suspected risks**:
1. Portal vs KWin colour consistency not verified with automated golden tests
2. Big-endian byte order handling missing in portal path
3. `_write_payload` buffer reuse may leak stale bytes between frames
4. Portal session close via `asyncio.run()` in a thread with an existing loop can produce `RuntimeError`

**Highest-value quick wins**:
- Force GStreamer colourimetry to `bt709` in portal path
- Add lock acquisition to `get_gamut_adaptation_matrix()`
- Replace `fuser -v` with `/proc/*/fd/` scanning
- Add golden colour-snapshot test fixture

**Highest-value larger refactors**:
- Device channel-order auto-probe (physical test pattern)
- Deterministic capture replay harness using synthetic frames
- Per-backend colour correction profiles

**Best novel ideas**:
- Privacy mask zones (ignore parts of screen)
- Adaptive smoothing based on motion
- Smart scene detection for smoother lighting transitions

---

## Repo Map

| Layer | Entry points / Key files |
|-------|--------------------------|
| **Entry points** | `src/nanoleaf_sync/ui/tray_app.py:main()` (PyQt6 tray), `src/nanoleaf_sync/service.py:main()` (headless) |
| **Capture pipeline** | `capture/factory.py` (backend creation), `capture/kwin_dbus.py` (KWin D-Bus), `capture/xdg_portal.py` (portal+PW/GStreamer), `capture/kmsgrab.py` (DRM), `capture/mock_capture.py` (test), `capture/auto_probe.py` (benchmark selection) |
| **Colour pipeline** | `color/hdr.py` (HDR→sRGB), `color/capture_metadata.py` (metadata resolution), `runtime/color_pipeline.py` (full pipeline), `runtime/color_processing.py` (Oklab/calibration), `runtime/srgb.py` (sRGB EOTF), `color/primaries.py` (gamut math) |
| **Device output** | `device/protocol.py` (TLV), `device/hid_transport.py` (HID IO), `device/usb_driver.py` (driver), `device/send_policy.py` (live send policy), `device/interfaces.py` (abstractions) |
| **UI/status** | `ui/tray_app.py` (system tray), `ui/settings_dialog.py`, `ui/display_configurator.py`, `ui/diagnostic_hub_dialog.py`, `ui/live_diagnostics.py`, `ui/calibration_widget.py` |
| **Config** | `config/model.py` (data classes), `config/store.py` (JSON persistence), `config/normalize.py`, `config/presets.py` |
| **Runtime orchestrator** | `runtime/engine.py` (3-stage pipeline), `runtime/state.py` (RuntimeState), `runtime/startup.py`, `runtime/processing.py` |
| **Tests** | `tests/` (130+ test files, 1466 tests), `tests/device/` (HID/protocol/USB driver tests), `tests/conftest.py` (auto-reset fixtures) |
| **Packaging/CI** | `pyproject.toml`, `.github/workflows/ci.yml`, `packaging/arch/PKGBUILD`, `scripts/` (build, install, release) |

### Pipeline flow:

```
KWin D-Bus / xdg-portal / kmsgrab / mock
        ↓
  Factory + Auto-Probe (backend selection)
        ↓
  3-stage threading engine:
    Capture Worker → Process Worker → HID Writer
        ↓                    ↓
  Frame capture      Colour pipeline:
                     - zone sampling (RGB→Oklab→...)
                     - display gamut adaptation
                     - SDR boost compensation
                     - color style + LED calibration
                     - temporal smoothing (One-Euro)
                     - predictive sync
                     - quantization hold
                     - dark zone stabilization
        ↓
  USB HID TLV write (send_policy: WRITE_ONLY/NONBLOCKING/RESPONSE_REQUIRED)
        ↓
  Nanoleaf LED strip
```

---

## Commands Run

| Command | Result | Notes |
|---------|--------|-------|
| `git status --short` | Shows modified working tree | 38 modified files (ongoing dev) |
| `git rev-parse --short HEAD` | `ded1b06` | |
| `python3 --version` | Python 3.14.6 | |
| `PyQt6` import check | 6.11.0 | |
| `dbus` import check | 1.4.0 | |
| `Pillow` import check | OK | |
| `numba` import check | **FAILED** | Not installed (optional, not in deps) |
| `ruff check src/` | **All checks passed** | |
| `mypy src/nanoleaf_sync --ignore-missing-imports` | **Success, no issues** | mypy 3.12 target |
| `python -m pytest -q --timeout=60 -x` | **1466 passed, 1 warning** | 32.17s; warning is PyGIDeprecationWarning |

---

## Scanner Results

| Tool | Status | Notes |
|------|--------|-------|
| **ruff** | ✅ Clean | Line-length 100, target py311 |
| **mypy** | ✅ Clean | 98 source files, no issues |
| **pytest** | ✅ 1466/1466 pass | Good coverage. Some UI files excluded from coverage via `omit` setting |
| **gitleaks** | Not run locally | Available via pre-commit hook |
| **trivy** | Not installed | Would be useful for container scanning |
| **osv-scanner** | Not installed | Would be useful for dependency vuln scanning |
| **semgrep** | Not installed locally | Runs in CI (`p/python` ruleset) |
| **bandit** | Not run locally | Configured in `pyproject.toml` with exclusions; runs in CI |
| **pip-audit** | Not run locally | Runs in CI on every push |

---

## Confirmed Issues

### CI-001: GStreamer colourimetry not pinned in portal path (CRITICAL)

- **Severity**: High
- **Confidence**: Confirmed
- **Area**: Capture → xdg-portal backend
- **Evidence**: `xdg_portal.py:614-619` — the GStreamer pipeline string is:
  ```
  pipewiresrc fd={fd} path={node_id} do-timestamp=true
  ! queue leaky=downstream max-size-buffers=2 max-size-bytes=0 max-size-time=0
  ! videoconvert ! videoscale
  ! video/x-raw,width={self.width},height={self.height},format={fmt}
  ! appsink ...
  ```
  There is no `colorimetry` constraint on the caps filter. GStreamer's `videoconvert` may default to different colour matrix coefficients (BT.601 vs BT.709) depending on the input caps from PipeWire, causing a systematic colour shift between the portal path and the KWin path.
- **Why it matters**: Users who select the portal backend get noticeably different colours than the KWin backend, which is confusing and undermines trust. This is the most likely root cause of "portal colours look wrong."
- **Likely root cause**: `videoconvert` applies its own colour matrix conversion without explicit colourimetry constraints.
- **Recommended fix**: Change the caps filter to include `colorimetry=bt709`:
  ```
  ! video/x-raw,width={self.width},height={self.height},format={fmt},colorimetry=bt709
  ```
  Also add a fallback without colourimetry for backends that don't support it.
- **Files/functions involved**: `xdg_portal.py:_open_via_gstreamer()` (line 614-618)
- **Tests to add**: `tests/test_xdg_portal_colour_path.py::test_colourimetry_pinned_to_bt709`
- **Estimated effort**: 1 hour
- **Regression risk**: Low. GStreamer caps with colourimetry are well-supported.

### CI-002: Lock-free read of gamut adaptation matrix (HIGH)

- **Severity**: Medium
- **Confidence**: Confirmed
- **Area**: Colour pipeline → gamut adaptation
- **Evidence**: `color_processing.py:185-188`:
  ```python
  def get_gamut_adaptation_matrix() -> np.ndarray | None:
      with _GAMUT_LOCK:
          return _GAMUT_ADAPTATION_MATRIX_T
  ```
  The function acquires `_GAMUT_LOCK` but returns the transposed matrix cache `_GAMUT_ADAPTATION_MATRIX_T`. The matrix is set under lock in `init_gamut_adaptation()` (line 93-95), but the transposed copy `_GAMUT_ADAPTATION_MATRIX_T` is also set under that lock. However, reader `apply_display_gamut_adaptation()` directly accesses the transposed matrix through `get_gamut_adaptation_matrix()` which returns it while holding the lock — but then uses it outside the lock. Due to GIL this is safe for `np.ndarray` reads in CPython, but is a correctness issue for other Python implementations and a code hygiene concern.
- **Why it matters**: A reader that calls `init_gamut_adaptation` concurrently could see a partially-constructed matrix. Low practical risk under CPython but still a bug.
- **Likely root cause**: The function was originally designed to return the original matrix under lock, but was refactored to return the transposed copy.
- **Recommended fix**: Either remove the lock from `get_gamut_adaptation_matrix()` (since GIL protects dict ops) or add a module-level atomic reference. The simplest fix: use `copy()` inside the lock.
- **Files/functions involved**: `color_processing.py:get_gamut_adaptation_matrix()`, `color_processing.py:apply_display_gamut_adaptation()`
- **Tests to add**: `test_color_processing_extended.py::test_gamut_matrix_thread_safety`
- **Estimated effort**: 30 minutes
- **Regression risk**: None

### CI-003: Hardcoded output channel order for all device models (HIGH)

- **Severity**: High
- **Confidence**: Confirmed
- **Area**: Device output → USB driver
- **Evidence**: `usb_driver.py:106-109`:
  ```python
  @staticmethod
  def _channel_order_for_model(model_number: str | None) -> str:
      if str(model_number or "").strip().upper() in {"NL82K1", "NL82K2"}:
          return "grb"
      return "grb"
  ```
  Both branches return `"grb"`. The function always returns the same value regardless of model. The config default is also `"grb"`. If a user connects a device with a different channel order (e.g., RGB or BRG), colours will be completely wrong with no error message.
- **Why it matters**: User plugs in a non-standard Nanoleaf device and gets red→green swapped colours silently.
- **Likely root cause**: Only two models were available during development.
- **Recommended fix**: Implement a physical channel-order probe that sends known test colours and reads back a sensor/reflection, or add a manual calibration wizard step for channel ordering. At minimum, add a config option to auto-detect from model number with a per-model map.
- **Files/functions involved**: `usb_driver.py:_channel_order_for_model()`, `config/model.py:output_channel_order`
- **Tests to add**: `tests/device/test_usb_driver.py::test_channel_order_model_map`, `tests/device/test_usb_driver.py::test_channel_order_detection`
- **Estimated effort**: 2–4 hours for probe; 30 minutes for model map
- **Regression risk**: Low

### CI-004: `fuser -v` parsing locale-dependent (MEDIUM)

- **Severity**: Medium
- **Confidence**: Confirmed
- **Area**: Device → HID transport
- **Evidence**: `hid_transport.py:136-169` uses `subprocess.run(["fuser", "-v", path])` and parses the human-readable output. The output format of `fuser -v` varies by locale and OS version (columns change, headers differ). The parsing at lines 155-168 splits whitespace and assumes fixed columns.
- **Why it matters**: On non-English locales or non-Linux systems, holder detection silently returns no results, and the diagnostics output says "no holders found" even when the device is held.
- **Likely root cause**: Quick implementation without locale hardening.
- **Recommended fix**: Replace `fuser -v` with `/proc/*/fd/*` scanning which is locale-independent. Use `os.readlink()` on `/proc/PID/fd/*` and match against the device path.
- **Files/functions involved**: `hid_transport.py:_linux_hidraw_holders()`
- **Tests to add**: `tests/device/test_hid_transport.py::test_hidraw_holders_procfs_scan`
- **Estimated effort**: 2 hours
- **Regression risk**: Low

### CI-005: HDR config defaults are misleading (MEDIUM)

- **Severity**: Medium
- **Confidence**: Confirmed
- **Area**: Config model
- **Evidence**: `config/model.py:126` has `display_preset: str = "hdr"` but `compositor_hdr_mode: bool = False` (line 138). The default `hdr_transfer = "pq"` and `hdr_primaries = "bt2020"` (lines 167-168), yet both capture backends deliver only SDR display-referred sRGB. Users with default config see HDR-related settings despite the app being unable to capture HDR content.
- **Why it matters**: Misleading defaults cause users to think HDR capture is supported. The "HDR" display preset combined with non-HDR capture means the SDR boost compensation logic activates unnecessarily, potentially over-brightening or colour-shifting output.
- **Likely root cause**: Historical design where HDR capture was planned but never fully realized.
- **Recommended fix**: Change `display_preset` default to `"sdr"` (or rename the concept). Add a startup-time warning if `compositor_hdr_mode=True` is set, explaining HDR capture limitations. Document that all current capture backends deliver SDR.
- **Files/functions involved**: `config/model.py`, `runtime/compositor.py`, `service.py:get_status()`
- **Tests to add**: `tests/test_config.py::test_hdr_defaults_are_reasonable`
- **Estimated effort**: 1 hour
- **Regression risk**: Low (config migration needed)

### CI-006: Portal restore token saved without on-exit cleanup (MEDIUM)

- **Severity**: Medium
- **Confidence**: Confirmed
- **Area**: Capture → xdg-portal
- **Evidence**: `xdg_portal.py:1014-1020` saves the restore token with `0o600`, but there is no cleanup path that removes the token on app exit or when the user explicitly requests a fresh portal session. The token persists across restarts, which means the portal permission dialog is never shown again. The `_clear_restore_token()` method exists (line 998) but is only called when SelectSources or Start fails after a restore token was used.
- **Why it matters**: If the user wants to change screen selection (e.g., from a full-screen capture to a specific window), the only way is to manually delete `~/.config/nanoleaf-kde-sync/portal_token`. This is not discoverable.
- **Likely root cause**: Designed to minimize permission prompts.
- **Recommended fix**: Add a "Reset portal permission" button in Settings/Advanced. Also add a `forget_portal_restore_token()` method (already exists at `service.py:767-770`) but ensure it's wired to the UI.
- **Files/functions involved**: `xdg_portal.py:_save_restore_token()`, `service.py:forget_portal_restore_token()`, UI settings dialog
- **Tests to add**: `tests/test_xdg_portal_robustness.py::test_forget_portal_token`
- **Estimated effort**: 1 hour
- **Regression risk**: Low

### CI-007: Big-endian byte order not handled in portal path (MEDIUM)

- **Severity**: Medium
- **Confidence**: Confirmed
- **Area**: Capture → xdg-portal
- **Evidence**: `xdg_portal.py:884-891` — the `_mapped_bytes_to_rgb` function handles BGRx/BGRA by swapping channels `[2, 1, 0]`. This assumes little-endian where B is byte 0 and R is byte 2. On big-endian systems, `struct.unpack` would see a different byte order. The KWin path correctly checks `sys.byteorder != "little"` at `kwin_dbus.py:1119` and bails out of the fast path. The portal path has no such check.
- **Why it matters**: Extremely rare on modern Linux (only a few ARM and MIPS platforms) but would produce completely wrong colours silently.
- **Likely root cause**: Little-endian assumption.
- **Recommended fix**: Add `if sys.byteorder != "little": return None` to the relevant format handling, mirroring KWin's approach. Better yet, add proper endian handling.
- **Files/functions involved**: `xdg_portal.py:_mapped_bytes_to_rgb()`
- **Tests to add**: `tests/test_xdg_portal_colour_path.py::test_portal_rgb_endian`
- **Estimated effort**: 30 minutes
- **Regression risk**: None

### CI-008: `_write_payload` buffer reuse may leak stale bytes (LOW)

- **Severity**: Low
- **Confidence**: Confirmed
- **Area**: Device → HID transport
- **Evidence**: `hid_transport.py:436-445` — the write buffer is a `bytearray(report_len)` created once before the loop, then reused on each iteration. When `previous_chunk_size > chunk_size`, stale bytes from the previous write iteration at positions `[data_offset + chunk_size : data_offset + previous_chunk_size]` are zeroed. However, if the *previous* write had *different* data at those positions (due to field framing differences between frames), the zeroing covers the right range but the *new* data's remaining bytes (if shorter than the previous payload segment for that report) could have residual data from the frame before the previous one. This is because `bytearray` is reused across the outer function call but reset per-call.
- **Why it matters**: Unlikely to cause visible issues in practice since the buffer is recreated per `_write_payload` call, but the code pattern is confusing and may mask subtle bugs if the function is called with variable-length payloads.
- **Likely root cause**: Micro-optimization by reusing a buffer.
- **Recommended fix**: Either document the safety invariant or simplify by creating a fresh buffer per report.
- **Files/functions involved**: `hid_transport.py:_write_payload()`
- **Tests to add**: `tests/device/test_hid_transport.py::test_write_payload_no_stale_bytes`
- **Estimated effort**: 30 minutes
- **Regression risk**: Low

---

## Suspected Issues / Needs Verification

### SI-001: KWin "InvalidScreen" error race on monitor hotplug

- **Severity**: Medium
- **Confidence**: Suspected
- **Area**: Capture → KWin D-Bus
- **Missing evidence**: The `_maybe_invalidate_kwin_probe_cache_for_invalid_screen()` method (service.py:1231-1268) invalidates the KWin probe cache after 3 consecutive InvalidScreen errors. But it counts *any* 3 errors, not necessarily 3 *consecutive* InvalidScreen errors. A mix of error types could trigger premature invalidation.
- **Why suspect**: Looking at the check `if int(self._runtime.consecutive_errors or 0) < 3: return` followed by `if not is_kwin_invalid_screen_error(last_error): return` — it checks `consecutive_errors` (any error) then checks if the *last* one is InvalidScreen. If errors 1 and 2 were network timeouts and error 3 was InvalidScreen, it would still invalidate even though the invalid screen issue may be transient.
- **Recommended verification**: Check if `consecutive_errors` should be an InvalidScreen-specific counter.

### SI-002: Portal session close may fail due to event loop conflict

- **Severity**: Medium
- **Confidence**: Suspected
- **Area**: Capture → xdg-portal
- **Evidence**: `xdg_portal.py:963` calls `asyncio.run(self._close_portal_session(session_handle))` which will fail with `RuntimeError: asyncio.run() cannot be called from a running event loop` if called from an async context. The fallback to a worker thread handles this for the main use case, but there's a narrow window where `_close_portal_session_sync` is called while the portal negotiation event loop is still alive.
- **Recommended verification**: Instrument with a `try/except` around `asyncio.run` and check the specific error type.

### SI-003: Missing CI coverage for kwin_dbus.py and xdg_portal.py

- **Severity**: Low
- **Confidence**: Suspected
- **Evidence**: Both `capture/kwin_dbus.py` and `capture/xdg_portal.py` interact with hardware/D-Bus and are likely skipped in CI. Many tests mock these extensively, but integration-level tests are absent. `pyproject.toml` omits several UI files from coverage, and the capture backends depend on KDE runtime.

---

## External Research Findings

| Topic | URL | Finding | How it applies | Recommended action |
|-------|-----|---------|----------------|-------------------|
| KWin ScreenShot2 auth | KDE discuss + GIMP integration | ScreenShot2 requires `X-KDE-DBUS-Restricted-Interfaces` in .desktop file | Repo already handles this via `desktop_entry.py` with `RESTRICTED_IFACE_MARKER` | Verify the .desktop file has the marker (docs/nanoleaf-kde-sync.desktop) |
| HDR capture unavailable | KWin developer blog (Xaver Hugl, Dec 2023) | Neither screenshot nor screencast APIs deliver HDR pixel data | Repo correctly assumes display-referred SDR with heuristic fallback | Keep existing approach; add clearer UI messaging |
| Portal colourspace metadata | xdg-desktop-portal spec | Portal lacks colour primaries/transfer metadata | Repo correctly hardcodes sRGB/BT.709 assumptions | No action needed beyond CI-001 fix |
| Nanoleaf TLV protocol | Official Nanoleaf docs (PDF in repo) | CMD 0x02 SET_ZONE_COLORS, 3 bytes per LED, 64-byte HID reports | Repo implementation matches spec exactly | No issues |
| HyperHDR best practices | github.com/awawa-dev/HyperHDR | Floating-point pipeline, motion-adaptive smoothing, temporal dithering | Repo already uses One-Euro filter, Oklab, adaptive smoothing | Consider temporal dithering for banding reduction |
| No rate limit on Nanoleaf USB | Nanoleaf protocol PDF | No documented rate limit | Repo sends at configurable FPS (default 60) | No change needed |

---

## Colour Accuracy Audit

### KWin vs Portal vs Mock paths

| Aspect | KWin D-Bus | xdg-portal (GStreamer) | Mock |
|--------|-----------|----------------------|------|
| **Pixel format** | Raw ARGB32 via pipe FD | BGRx/BGRA/RGB/BGR via GStreamer appsink | Deterministic synthetic |
| **Colour primaries** | Assumed BT.709 display-referred | Assumed BT.709 display-referred | sRGB |
| **Transfer function** | Assumed sRGB gamma | Assumed sRGB gamma | sRGB |
| **Frame dimensions** | Up to display resolution, resized to config | Negotiated via PipeWire caps | Config dimensions |
| **Potential shifts** | None (raw pixel data) | **videoconvert colourimetry heuristics** | None |

### HDR/SDR handling

- **Current state**: Both capture backends deliver SDR display-referred sRGB. The HDR pipeline in `color/hdr.py` applies EOTF → gamut conversion → tone mapping, but is only invoked when the capture backend reports HDR metadata, which never happens with current KWin/Portal APIs.
- **`convert_frame_to_srgb8()`** (hdr.py:298): Short-circuits on `uint8 + srgb + bt709` — this is the common path for both backends.
- **`_preserve_extended_linear_float()`** (hdr.py:111): Only kept for future DRM/kmsgrab HDR paths.
- **Verdict**: Correct for current APIs. The `display_preset="hdr"` default is misleading (CI-005).

### Portal colour inaccuracy root cause

The most likely root cause is GStreamer's `videoconvert` element applying its own colour matrix conversion. When PipeWire delivers frames with BT.601 colourimetry (common for video capture), `videoconvert` converts to sRGB colourspace using a BT.601→sRGB matrix instead of the correct BT.709→sRGB matrix. This desaturates reds and shifts greens. The fix is to explicitly pin `colorimetry=bt709` in the caps filter (CI-001).

### Calibration profiles

- SDR and HDR calibration profiles exist (`LedCalibrationProfile` in `config/model.py`) with per-channel gains, gamma, white balance, chroma compression, and black cutoff.
- These operate in linear/Oklab space — correct approach.
- No automated calibration process exists (requires manual tuning).

---

## Flicker / Latency / Performance Audit

### Frame pacing

- **3-stage pipeline**: Capture Worker → Process Worker → HID Writer, connected via lock-free SPSC ring buffers
- **FPS governor**: Adaptive, starts at config FPS, adjusts downward based on measured p95 latency
- **Stale frame drop**: Configurable threshold (default 60ms + 2× frame budget) drops old frames
- **Pacing**: HID writer paces sends to target FPS budget with `time.sleep()` after each send

### Smoothing

- **One-Euro filter**: Adaptive low-pass with motion prediction. `smoothing` (0.0-1.0) controls minimum cutoff, `smoothing_speed` controls motion-responsive gain.
- **Exponential Moving Average**: 0.9/0.1 EWMA on ACK latency, loop gap, and capture-to-send metrics
- **Quantization hold**: Prevents re-sending identical colours within threshold (1.25 units @ 60fps)
- **Dark zone stabilization**: Blends to neutral grey below configurable luminance threshold with hysteresis

### Sampling

- Zone sampling stride (default 1 = every pixel) reduces CPU usage
- Multiple engines: legacy (RGB integral), optimized (Oklab integral)
- Live mode switching between area-average and edge-direct based on motion
- Letterbox detection clips zones to content bounds

### Performance assessment

- The arch is well-optimized for real-time. The SPSC ring buffers avoid locks on hot paths.
- At 60 FPS, the frame budget is 16.67ms. Processing spans: capture (~1-5ms KWin), colour pipeline (~1-3ms), HID write (~1-3ms). Well within budget.
- At 120 FPS (8.33ms budget), CPU copies from frame capture to zone sampling may become the bottleneck.
- **Missing**: No automatic quality degradation under load (e.g., increasing stride when FPS drops). The FPS governor lowers FPS but does not adjust stride.

---

## Privacy / Security Audit

| Concern | Status | Details |
|---------|--------|---------|
| Screen capture permissions | ✅ Handled | KWin: desktop-entry restricted interface. Portal: system permission prompt + restore token |
| Token storage | ✅ Secure | Portal restore token at `~/.config/.../portal_token` with `0o600` |
| Log sanitization | ✅ Implemented | Launch tokens redacted in error messages (`redact_launch_token()`) |
| Debug exports | ✅ Secure | Written to temp dirs with `0o700` |
| HID access | ✅ Controlled | VID/PID validation before device open |
| Network exposure | ✅ None | No network service |
| Untrusted input | ✅ Safe | No Qt Designer `.ui` loading; no deserialization of untrusted data |
| Supply chain | ⚠️ Monitoring | Dependabot + pip-audit in CI. Bandit + Semgrep + CodeQL |
| Config file permissions | ⚠️ Not hardened | Config stored in `~/.config/nanoleaf-kde-sync/` — permissions not explicitly set |

---

## UI / Diagnostics Audit

| UX Feature | Status | Details |
|------------|--------|---------|
| Backend indicator | ⚠️ Partial | Status includes `effective_capture_backend`, `selected_capture_backend`, `selection_reason`, `backend_probe_attempts`. But the tray icon itself doesn't visually indicate backend |
| Fallback explanation | ✅ Good | `backend_unresolved_reason`, `selection_reason`, probe attempt rows explain decisions |
| Permission errors | ✅ Good | KWin auth errors include `launch_context_snapshot()` with redacted tokens |
| Diagnostics hub | ✅ Good | `DiagnosticHubDialog`, `LiveDiagnosticsDialog`, `Doctor` tool, `SmokeTest` |
| Debug bundle | ✅ Good | `export_diagnostic_bundle()` writes to `0o700` dir |
| Colour path probe | ✅ Excellent | `run_colour_path_probe()` shows per-zone before/after at each pipeline stage |
| Flicker lab | ✅ Good | `run_flicker_lab()` tests fade, rapid alternation, colour cuts |
| Portal mode indicator | ✅ Good | `startup_state == "waiting_for_screen_selection"` shown in status |
| HDR colour path diagnostics | ✅ Good | `hdr_colour_path` dict with transfer, primaries, source, warnings |
| Readiness check | ✅ Good | `run_readiness_check()` produces structured report |

**Gap**: The tray icon has no visual distinction between KWin, portal, mock, and error states. Adding coloured/overlaid icons would dramatically improve at-a-glance status awareness.

---

## Testing Plan

### Exact test files / test names to add

| Test file | Test name | What it covers |
|-----------|-----------|----------------|
| `tests/test_xdg_portal_colour_path.py` | `test_portal_colourimetry_pinned_to_bt709` | Verifies GStreamer pipeline includes `colorimetry=bt709` |
| `tests/test_xdg_portal_colour_path.py` | `test_portal_rgb_endian` | Verifies big-endian byte order handling |
| `tests/test_color_processing_extended.py` | `test_gamut_matrix_thread_safety` | Verifies lock acquisition in getter |
| `tests/device/test_hid_transport.py` | `test_write_payload_no_stale_bytes` | Verifies no stale bytes between writes |
| `tests/device/test_hid_transport.py` | `test_hidraw_holders_procfs_scan` | Tests holder detection via /proc |
| `tests/device/test_usb_driver.py` | `test_channel_order_model_map` | Verifies per-model channel order |
| `tests/test_config.py` | `test_hdr_defaults_are_reasonable` | Verifies HDR defaults are consistent |
| `tests/test_screen_capture.py` | `test_capture_backend_colour_consistency` | Golden test: same input → same output across backends |
| `tests/test_runtime_state.py` | `test_consecutive_errors_tracking` | Verifies error tracking per type |
| `tests/test_service_status_modes.py` | `test_tray_icon_indicates_backend` | Verifies tray icon changes with backend |

---

## Prioritised Fix Plan

| Priority | Task | Impact | Effort | Risk | Dependencies |
|----------|------|--------|--------|------|--------------|
| **P0** | Pin GStreamer colourimetry to bt709 (CI-001) | Fixes portal colour inaccuracy | 1h | Low | None |
| **P0** | Add lock to gamut adaptation matrix read (CI-002) | Removes race condition | 30m | None | None |
| **P1** | Replace `fuser -v` with procfs scanning (CI-004) | Robust holder detection | 2h | Low | None |
| **P1** | Add channel order model map / probe (CI-003) | Ensures correct colours per model | 2-4h | Low | None |
| **P2** | Fix HDR config defaults (CI-005) | Reduce user confusion | 1h | Low | Config migration |
| **P2** | Add "Reset portal permission" UI button (CI-006) | Improves UX for portal users | 1h | Low | None |
| **P2** | Add big-endian check to portal path (CI-007) | Robustness on rare platforms | 30m | None | None |
| **P3** | Tray icon backend indicator | At-a-glance status | 3h | Low | None |
| **P3** | Golden colour snapshot tests | Prevents colour regressions | 4h | Medium | Test fixtures |

---

## Novel Ideas

| Idea | Category | Why it helps | Effort | Risk | Worth doing now? | First step |
|------|----------|-------------|--------|------|-----------------|------------|
| **Privacy mask zones** | Polish | Users can mask webcam areas, notifications, OSD from influencing lights | 1-2 days | Low | Yes | Add `privacy_zones` list to config; skip masked rects in zone sampling |
| **Adaptive smoothing via motion** | Polish | Reduces flicker during static content, stays responsive during video/games | 1 day | Low | Yes | Already partially done (One-Euro filter); expose motion_threshold in UI |
| **Smart scene detection** | Ambitious | Detect video/movie/game/desktop and auto-select profile | 3-5 days | Medium | Maybe | Add scene classifier based on motion+brightness variance |
| **Temporal dithering for banding** | Performance | Reduces colour banding on 8-bit LED strips | 1 day | Low | Maybe | Add ordered dither matrix to output preparation |
| **Black-bar detection for letterbox** | Polish | Avoids lighting black bars in 21:9 content | Done | - | Already implemented in `content_bounds.py` | - |
| **HDR-aware tone mapper** | Architecture | When DRM captures are available, properly tone-map HDR→SDR | 2-3 days | Medium | Future | Already has Hable tonemap in `hdr.py`; needs DRM HDR metadata |
| **Per-backend colour profile** | Architecture | Auto-correct for backend-specific colour shifts | 2-3 days | Low | Maybe | Add `backend_color_profiles` dict to config; apply correction matrix per backend name |
| **Deterministic replay system** | Architecture | Record real captures, replay for testing colour pipeline changes | 3-5 days | Medium | Maybe | Extend `replay_capture.py` to read saved frames from disk |
| **GPU downsampling** | Performance | Use OpenCL/Vulkan compute for zone sampling on large displays | 2-4 weeks | High | Not now | Research pyopencl integration |
| **Entertainment mode output** | Ambitious | Low-latency streaming protocol if Nanoleaf supports it | Research needed | Unknown | Not now | Check firmware capabilities |

---

## Implementation Specs (Top 5)

### Spec 1: Pin GStreamer colourimetry to BT.709

**Goal**: Eliminate colour differences between KWin and portal backends.

**Changes**:
1. In `xdg_portal.py:614-619`, change the caps filter string to:
   ```
   ! video/x-raw,width={self.width},height={self.height},format={fmt},colorimetry=bt709
   ```
2. Add a fallback loop that retries without `colorimetry=bt709` if caps negotiation fails (some old GStreamer versions may not support it).
3. Verify that `videoconvert` before the caps filter is still correct for the resize + conversion chain.

**Test**: `test_portal_colourimetry_pinned_to_bt709` — check pipeline string contains `colorimetry=bt709`.

### Spec 2: Secure gamut adaptation matrix read

**Goal**: Eliminate theoretical data race.

**Changes**:
1. In `color_processing.py:get_gamut_adaptation_matrix()`, hold the lock for the entire read:
   ```python
   def get_gamut_adaptation_matrix() -> np.ndarray | None:
       with _GAMUT_LOCK:
           if _GAMUT_ADAPTATION_MATRIX_T is None:
               return None
           return _GAMUT_ADAPTATION_MATRIX_T.copy()
   ```

**Test**: `test_gamut_matrix_thread_safety` — call init and get concurrently.

### Spec 3: Replace `fuser -v` with /proc scanning

**Goal**: Locale-independent HID device holder detection.

**Changes**:
1. In `hid_transport.py:_linux_hidraw_holders()`, replace the `subprocess.run(["fuser", "-v", path])` with:
   ```python
   import os
   holders = []
   for proc_entry in Path("/proc").iterdir():
       if not proc_entry.name.isdigit():
           continue
       try:
           fd_dir = proc_entry / "fd"
           for fd in fd_dir.iterdir():
               try:
                   link = os.readlink(str(fd))
                   if link == path:
                       cmdline = (proc_entry / "cmdline").read_text().split("\0")[0]
                       holders.append(f"PID {proc_entry.name} ({cmdline})")
               except OSError:
                   pass
       except OSError:
           pass
   ```
2. Keep the existing API but improve reliability.

**Test**: `test_hidraw_holders_procfs_scan` — monkeypatch `Path.iterdir`.

### Spec 4: HDR config default fix

**Goal**: Reduce user confusion about HDR capabilities.

**Changes**:
1. Change `config/model.py:126` from `display_preset: str = "hdr"` to `display_preset: str = "sdr"`.
2. Add a config migration in `config/normalize.py` that upgrades `display_preset="hdr"` → `"sdr"` for new installs but preserves user-set values on upgrade.
3. Add a warning in `service.py:get_status()` when `compositor_hdr_mode=True`.

**Test**: `test_hdr_defaults_are_reasonable` — verify defaults don't contradict capture capabilities.

### Spec 5: Tray icon backend indicator

**Goal**: At-a-glance visual feedback of active capture backend.

**Changes**:
1. In `ui/tray_app.py`, add backend-aware icon variants:
   - Normal icon → KWin active
   - Icon with overlay → portal/fallback active
   - Icon with "!" → error state
   - Icon with "M" → mock mode
2. Use Qt's `QIcon` composition or load different SVG assets.
3. Update icon on each status poll.

**Test**: `test_tray_icon_indicates_backend` — set mock status and verify icon changes.

---

## Open Questions

1. **Colour accuracy**: Can you run a manual benchmark comparing KWin vs portal colours on your setup? Use `nanoleaf-kde-sync-doctor` and look at the "capture_colour_diagnostics" section for both. If portal colours look different, the `colorimetry=bt709` fix should resolve it.

2. **Device models**: Do you have access to a non-standard Nanoleaf USB device (not NL82K1/NL82K2)? The channel order issue (CI-003) only matters for unsupported models.

3. **HDR display**: Do you have an HDR display? If so, does `compositor_hdr_mode=True` produce visible improvements or just over-brighten? This affects the priority of CI-005.

4. **Big endian**: Are you targeting any big-endian platforms? If not, CI-007 can be deprioritized.

5. **Testing**: Would you like me to implement any of the test files listed in the Testing Plan?
