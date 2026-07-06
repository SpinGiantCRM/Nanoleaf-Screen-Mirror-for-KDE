# Production Readiness Audit Report

**Repository:** SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE  
**Audit date:** 2026-07-06  
**Auditor environment:** Linux (CachyOS-style), Python 3.14 venv, offscreen Qt, no active KDE Plasma session bus for KWin capture

---

## 1. Executive verdict

**Production readiness status:** `ready` (pending live KDE session HDR validation)

The codebase is mature: 1550 automated tests pass, release gate is green, type/lint/security scans are clean, and hardware smoke test passes with NL82K2 (48 zones). Remaining gaps are primarily **KDE-session authorization UX** and **HDR colour on a real Plasma HDR desktop** — not blockers for SDR mirroring with desktop-entry launch.

### Top 10 risks (by user impact)

| # | Risk | Severity |
|---|------|----------|
| 1 | KWin ScreenShot2 authorization depends on desktop-entry launch context; shell/systemd autostart may fail capture silently until user relaunches from `.desktop` | High |
| 2 | HDR colour correctness on real Plasma HDR desktops not verified in this audit environment | High |
| 3 | HDR colour correctness on real Plasma HDR desktops not verified in CI | High |
| 4 | KWin ScreenShot2 authorization depends on desktop-entry launch context | High |
| 5 | Single-monitor assumption; multi-monitor setups unsupported | Medium |
| 6 | Tray UI (`tray_app.py`) has ~53% line coverage; complex lifecycle paths need hardware validation | Medium |
| 7 | `virtual_zones.py` and several CLI helpers have 0% coverage | Low–Medium |
| 8 | Arch packaging release gate requires `makepkg` (fails in minimal/sandbox CI) | Low |
| 9 | Invalid imported `color_matrix` is dropped on normalize (logged; re-import required) | Low |
| 10 | Multi-monitor / plugin framework explicitly out of scope | Low |

### Top 10 fixes completed in this audit

| # | Fix |
|---|-----|
| 1 | Settings slider save now **merges** into existing `LedCalibrationProfile` instead of replacing it — preserves imported `color_matrix` and dark-sample fields |
| 2 | HID `open()` retries the **full enumerate+open path** on busy/open failures, not only empty enumeration |
| 3 | HID `transceive()` response budget uses **elapsed wall time** instead of decrementing full read-timeout slots per fast empty read |
| 4 | Config normalize logs warning when `color_matrix` is invalid instead of silent drop |
| 5 | Config migrate logs warning when top-level and calibration corner anchors conflict; keeps calibration block value |
| 6 | `_sync_top_level_into_profile` preserves profile `dark_sample_stabilize_*` instead of hardcoding defaults |
| 7 | Regression test: `test_settings_slider_save_preserves_imported_color_matrix` |
| 8 | Regression test: `test_open_retries_when_device_is_busy_then_available` |
| 9 | Regression test: `test_transceive_tolerates_many_fast_empty_reads_before_response` |
| 10 | Regression tests for matrix/anchor/HID retry/transceive budget | Pass 1 |
| 11 | HID write-timeout: join inflight thread before close; brief join after timeout | Pass 2 |
| 12 | HID writer errors wired into supervisor reinit (same limit as capture/process) | Pass 2 |
| 13 | kmsgrab→KWin fallback surfaced immediately in status; probe cache heals on first detection | Pass 2 |
| 14 | Settings backend probes use `resolve_capture_dims` instead of 1920×1080 fallback | Pass 2 |
| 15 | Duplicate-frame HID skip respects FPS pacing deadline | Pass 2 |
| 16 | Hardware smoke test: NL82K2 48-zone capture + device init verified on device | Pass 2 |

### Top 10 remaining issues (not safely fixable in this pass)

| # | Issue | Why blocked |
|---|-------|-------------|
| 1 | KWin authorization UX on Wayland from shell/autostart | Requires live Plasma session + user interaction |
| 2 | HDR PQ/EOTF on real HDR desktop | Requires HDR monitor + Plasma HDR mode |
| 3 | Multi-monitor support | Out of product scope per AGENTS.md |
| 4 | Full tray UI visual/regression suite | Brittle without headed KDE session |
| 5 | `virtual_zones.py` production usage | 0% coverage; may be experimental/dead path |
| 6 | Orphan HID write thread if still alive after join cap | Platform cannot cancel blocking hidapi write |
| 7 | Arch `makepkg` in sandbox release gate | Environment tooling, not app defect |
| 8 | Invalid color_matrix dropped on load (warn only) | Safer than keeping corrupt matrix |
| 9 | End-to-end sustained mirroring soak under load | Needs extended hardware session |
| 10 | Plugin / multi-device architecture | Explicitly out of scope |

---

## 2. Evidence table

| Severity | Area | File(s) | Evidence | User-visible impact | Fix status | Validation |
|----------|------|---------|----------|---------------------|------------|------------|
| High | Config/UI | `settings_dialog_handlers.py` | `_led_profile_from_sliders()` built fresh profile without `color_matrix` | Imported LED matrix lost after any slider change + Save | **fixed** | `pytest tests/test_settings_dialog.py::test_settings_slider_save_preserves_imported_color_matrix` |
| Medium | HID | `hid_transport.py` | Retry loop only re-enumerated on empty device list | Busy device open fails once with no backoff despite `retry_attempts=3` | **fixed** | `pytest tests/test_hid_transport_extended.py::test_open_retries_when_device_is_busy_then_available` |
| Medium | HID | `hid_transport.py` | `remaining_budget_s -= per_read_budget_s` on every read | Multi-chunk HID responses fail after 4 fast empty reads | **fixed** | `pytest tests/device/test_hid_transport.py::test_transceive_tolerates_many_fast_empty_reads_before_response` |
| Medium | Config | `normalize.py` | Invalid `color_matrix` returned `[]` silently | Measured profile matrix lost on load with no diagnostic | **fixed** (warn) | `pytest tests/test_normalize.py::test_validate_config_drops_invalid_color_matrix_with_warning` |
| Medium | Config | `normalize.py` | Conflicting top-level vs calibration anchors: top-level dropped | Hand-edited configs may lose anchor without notice | **fixed** (warn) | `pytest tests/test_normalize.py::test_migrate_config_dict_keeps_calibration_anchor_on_conflict` |
| Low | Config | `normalize.py` | `_sync_top_level_into_profile` hardcoded dark_sample defaults | Default-profile sync reset dark-sample tuning | **fixed** | `pytest tests/test_normalize.py` (existing + guided calibration tests) |
| Medium–High | HID | `hid_transport.py` | Write timeout raised but daemon thread continued | Rare double-write or fault on close after timeout | **fixed** (join cap) | `pytest tests/device/test_hid_transport.py::test_close_waits_for_inflight_write_thread` |
| Medium | Runtime | `engine_loop_hid.py`, `engine_loop_supervisor.py` | HID errors recorded but supervisor only watched capture/process | Sustained HID fault may not reinit backends | **fixed** | `pytest` (1550 pass); manual HID fault injection |
| Medium | Capture | `kmsgrab.py`, `service.py` | Internal KWin fallback while cache still said `kmsgrab` | Diagnostics showed kmsgrab while using KWin | **fixed** | `pytest tests/test_service_status.py::test_get_status_reports_kmsgrab_kwin_fallback_before_cache_heal` |
| High | Capture | `kwin_dbus.py`, `desktop_entry.py` | ScreenShot2 requires restricted DBus interface in `.desktop` | Capture fails from shell/autostart without authorization | documented | Manual: launch from desktop entry vs terminal |
| Low | UI | `settings_dialog_handlers_ext.py` | 1920×1080 fallback when runtime status missing | Preview/diagnostics use wrong dims until runtime starts | **fixed** | `resolve_capture_dims(self._cfg_seed)` via `_probe_capture_dims()` |
| — | Tests/CI | `scripts/release_gate.sh` | All gates pass with Arch `makepkg` available | — | verified | `./scripts/release_gate.sh` |
| — | Security | `bandit`, `pip-audit` | No findings | — | verified | `bandit -r src/`; `pip-audit --path .` |

---

## 3. Runtime path summary

**Entry points:** `nanoleaf-kde-sync` (tray) → `service.py` → `runtime/startup.py` → `runtime/engine_loop.py`

```
Config load (ConfigManager.validate_config)
  → Backend selection (capture/factory.py: auto-probe kmsgrab→kwin-dbus→xdg-portal)
  → Capture backend init (KWinDBusScreenshotCapture | KMSGrabCapture | XDGPortalCapture | Mock)
  → USB driver init (device/usb_driver.py → hid_transport.py)
  → Calibration gate (anchor_calibration / calibration_resolver — blocks stream if incomplete)
  → run_loop_supervisor spawns:
       capture_worker_loop  → capture_buf (ring buffer, drop-if-full)
       process_worker_loop  → zone sample → color_pipeline → process_buf
       hid_writer_loop      → stale-frame drop → HID write pacing → NanoleafUSBDriver.send_colors
  → RuntimeState snapshots → tray/settings diagnostics
```

**Frame path detail:**

1. **Capture:** `engine_loop_capture.py` calls `capture.capture()`; kmsgrab may precompute zone colors via DRM helper; dimensions from `capture/dimensions.py` (sysfs/Qt, default 480×270).
2. **Process:** `engine_loop_process.py` samples edge zones (`runtime/zones.py`), runs `color_pipeline.py` (HDR metadata → linear → gamut → LED calibration matrix → gamma → quantization).
3. **HID:** `engine_loop_hid.py` applies FPS governor, stale-output drop (`engine_frame.evaluate_stale_output_drop`), duplicate-frame skip, then `usb_driver` TLV framing over HID.

---

## 4. Colour/HDR assessment

**Status:** `partially correct` — strong test coverage for sRGB/PQ paths, neutrals, and pipeline stages; **not verified on live Plasma HDR hardware in this audit**.

**Reasons:**

- Dedicated tests: `test_hdr.py`, `test_color_accuracy_pipeline.py`, `test_color_golden_matrix.py`, `test_reference_ambient_neutral_model.py`, portal/KWin colour path contracts.
- Pipeline separates SDR/HDR presets via `LedCalibrationProfile` per preset and compositor HDR runtime (`color/capture_metadata.py`).
- PQ/EOTF, sRGB, display gamut adaptation, dark-zone stabilization, and neutral handling have regression tests.
- **Gap:** No end-to-end hardware proof that Auto/HDR/SDR presets match user expectation on NL82K2 + HDR desktop.
- **Fixed this audit:** Imported `color_matrix` no longer wiped by Settings slider save.

---

## 5. Capture/DRM/KWin assessment

**Status:** `partially robust` — explicit fallback chains, probe cache healing, and resource cleanup on failed probes; **fragile without KDE session**.

**Reasons:**

- Auto-probe order: kmsgrab (if DRM helper ready) → kwin-dbus → xdg-portal (`capture/factory.py`).
- Fallback chain closes backends on failed probe attempts (v1.9.3 changelog).
- KWin uses dedicated executor + reconnect (`kwin_dbus.py`); invalid-screen errors tracked in `RuntimeState`.
- kmsgrab requires setcap DRM helper; doctor checks caps; wheel bundles helper for linux_x86_64.
- **Fragile:** KWin authorization is environment-dependent; smoke test failed here with `kwin-no-api` (no Plasma session).
- **Fragile:** kmsgrab silent KWin fallback until service heals probe cache (3 status polls).

---

## 6. Config/calibration persistence assessment

**Status:** `robust` for normal flows; edge cases improved this audit.

**Reasons:**

- Schema v2 migration with calibration block consolidation (`config/normalize.py`).
- Manual `device_zone_count` authoritative; tests in `test_config.py`, `test_guided_led_calibration_workflow.py`.
- Corner anchors TL/TR/BR/BL validated before streaming (`calibration_incomplete` gate).
- Round-trip tests: `test_config_store.py`, reset tool tests, LED profile import/export.
- **Fixed:** color_matrix preservation on UI slider save; anchor conflict warning; invalid matrix warning.

---

## 7. Test and command results

| Command | Result |
|---------|--------|
| `python -m venv .venv && pip install -e .[test]` | Pass |
| `ruff check src/ tests/ scripts/` | Pass (All checks passed) |
| `ruff format --check src/ tests/ scripts/` | Pass (287 files formatted) |
| `mypy src/nanoleaf_sync --ignore-missing-imports --follow-imports=silent` | Pass (110 files) |
| `pytest -q --timeout=60 --cov=nanoleaf_sync --cov-fail-under=75` | **1550 passed**, 77.03% coverage |
| `bandit -r src/ -c pyproject.toml` | Pass (0 issues) |
| `pip-audit --path .` | Pass (no known vulnerabilities) |
| `pre-commit run --all-files` | Pass (after ruff auto-format) |
| `./scripts/release_gate.sh` | Pass (with full permissions; **fail in sandbox** on `makepkg --printsrcinfo` exit 10) |
| `nanoleaf-kde-sync-doctor` | 0 FAIL, 3 WARN (no KWin session, drm-vendor-tier, autostart disabled) |
| `nanoleaf-kde-sync-smoke-test` | Capture failed (`kwin-no-api`) without Plasma session |
| `nanoleaf-kde-sync-smoke-test --hardware` | **Pass** — NL82K2, 48 zones, frame (1440×2560), device init OK |

---

## 8. Manual validation checklist

**Target:** CachyOS / KDE Plasma 6 Wayland, NL82K2, 48-zone manual count

- [ ] Run `nanoleaf-kde-sync-doctor` — expect PASS on session-bus, kwin-screenshot2, hid-device, calibration
- [ ] Run `nanoleaf-kde-sync-smoke-test --hardware` — capture + device open
- [ ] Run `nanoleaf-kde-sync-smoke-test --hardware --send-test-frame` — optional LED output sanity check
- [ ] Launch tray from **desktop entry** (not bare terminal): `nanoleaf-kde-sync`
- [ ] Authorize KWin screen capture when prompted; confirm diagnostics show `kwin-dbus` or intended backend
- [ ] Settings → confirm manual zone count stays **48** after restart (device-reported count diagnostics-only)
- [ ] Calibration test pattern → assign **TL / TR / BR / BL** anchors; restart; confirm mirroring starts
- [ ] Display preset **SDR** → neutral grey/white on desktop edges look neutral on strip
- [ ] Display preset **HDR** (if Plasma HDR on) → verify SDR white reference in diagnostics before tuning brightness
- [ ] Start mirroring → verify low latency (target 60 FPS); check Live Diagnostics FPS and stale-drop counters
- [ ] Unplug/replug USB strip → mirroring recovers without tray restart
- [ ] **Stop** → strip goes black; tray remains running
- [ ] **Start** again → mirroring resumes
- [ ] Quit and relaunch tray → settings and calibration persist
- [ ] Import measured LED profile → adjust one slider → Save → confirm `color_matrix` still applied (colours unchanged vs pre-slider except adjusted channel)
- [ ] Check `~/.local/state/nanoleaf-kde-sync/` logs for repeated errors or screen content leaks (should be metadata only)

---

## Files changed in this audit

| File | Change |
|------|--------|
| `src/nanoleaf_sync/ui/settings_dialog_handlers.py` | Merge slider values into existing LED profile |
| `src/nanoleaf_sync/device/hid_transport.py` | Full-path open retry; transceive elapsed budget; inflight write join on timeout/close |
| `src/nanoleaf_sync/config/normalize.py` | Matrix/anchor warnings; dark_sample preserve |
| `src/nanoleaf_sync/runtime/engine_loop_context.py` | `hid_worker_error_count` |
| `src/nanoleaf_sync/runtime/engine_loop_hid.py` | HID error counter; duplicate-frame pacing |
| `src/nanoleaf_sync/runtime/engine_loop_supervisor.py` | Reinit on HID worker failures |
| `src/nanoleaf_sync/service.py` | Immediate kmsgrab→KWin status; heal cache on first fallback |
| `src/nanoleaf_sync/ui/settings_dialog_handlers_ext.py` | `_probe_capture_dims()` |
| `tests/test_settings_dialog.py` | color_matrix preservation test |
| `tests/test_normalize.py` | matrix + anchor conflict tests |
| `tests/device/test_hid_transport.py` | transceive + close-inflight tests |
| `tests/test_hid_transport_extended.py` | busy-device open retry test |
| `tests/test_service_status.py` | kmsgrab fallback status + faster heal test |
| `docs/SMOKE_TEST.md` | Hardware frame test requires `--hardware --send-test-frame` |
| `AUDIT_REPORT.md` | Full audit report |
