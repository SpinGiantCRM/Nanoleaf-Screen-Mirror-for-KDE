# Nanoleaf KDE Sync Production Readiness Audit

Date: 2026-07-06
Repository: `SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE`
Scope: KDE Plasma 6 / Linux Nanoleaf USB screen-mirroring app, including capture, colour/HDR, calibration, HID output, runtime loop, config persistence, UI-adjacent flows, doctor/smoke/release tooling, packaging, and security-sensitive surfaces.

## 1. Executive verdict

Production readiness status: **blocked**

The repository shows substantial prior hardening across capture, colour processing, HID transport, calibration authority, packaging, and release checks. Static inspection did not find a reason to call the code obviously non-functional. However, a production sign-off is blocked because this audit environment could not obtain a local checkout from GitHub and could not run the required local checks, KDE Wayland/KWin authorization checks, DRM helper checks, or NL82K2 hardware validation.

### Top risks ranked by user impact

1. **Real hardware and KDE session path unvalidated in this audit** — cannot certify NL82K2 output, HID permissions, KWin authorization, DRM helper capabilities, or runtime latency without a CachyOS/KDE Plasma 6 Wayland session and device.
2. **HDR correctness remains partially constrained by capture backend semantics** — KWin Screenshot2 is warned as unable to preserve HDR colour accuracy in runtime code; HDR/SDR behaviour needs real Plasma HDR validation.
3. **KMS/DRM helper path is fragile by nature** — helper packaging and setcap are present, but DRM framebuffer access and zone patch sampling require real compositor/GPU/driver validation.
4. **HID write timeout handling still needs stress validation** — transport has timeout and uncertain-write recovery, but long-running write timeout/disconnect/reconnect behaviour must be tested on actual devices.
5. **Single-monitor limitation is documented** — users with multiple displays may capture the wrong source or need explicit monitor selection validation.
6. **Desktop-entry launch context remains important for KWin authorization** — terminal launches may fail differently from desktop launches.
7. **Manual zone-count authority must be verified end-to-end** — config/runtime code prefers configured counts, but real mismatch cases must be checked against a detected 48-zone NL82K2.
8. **Colour pipeline has many adaptive stages** — display gamut adaptation, SDR boost compensation, dark-zone stabilization, dithering, neighbour blending, and predictive sync need scene-based visual QA to rule out flicker or tinting regressions.
9. **Release gate was not executed in this audit** — static inspection shows a broad gate, but the actual command result is unknown for the current branch.
10. **Docs/tooling drift can mislead hardware validation** — one confirmed smoke-test documentation mismatch was fixed in this pass.

### Fixes completed in this audit

Only confirmed, low-risk fixes are listed. No speculative code changes were made to fragile capture, DRM, HID, HDR, calibration, or runtime timing code without local execution evidence.

1. **Fixed smoke-test documentation for hardware frame output** — `docs/SMOKE_TEST.md` now instructs `nanoleaf-kde-sync-smoke-test --hardware --send-test-frame`, matching the CLI requirement that hardware is skipped by default.
2. **Corrected this audit report** — `AUDIT_REPORT.md` now records the inspected runtime path, evidence, blocked checks, and exact manual validation checklist without claiming unrun tests or hardware results.

### Remaining issues not safely fixable in this pass

1. Run the complete local release gate on a real checkout.
2. Validate KWin authorization from both terminal and installed desktop entry.
3. Validate KMS/DRM helper installation, setcap, and zone patch sampling on the target GPU/driver stack.
4. Validate NL82K2 48-zone HID output, unplug/replug, busy-device handling, and long-run write pacing.
5. Validate HDR preset behaviour on Plasma HDR with known HDR and SDR test content.
6. Validate manual zone count remains authoritative when USB reports a different count.
7. Validate TL/TR/BR/BL physical calibration order on real strip placement.
8. Stress-test runtime stop/start/restart and tray close behaviour over repeated sessions.
9. Review HID timeout thread cleanup with local tests before making any code change in that area.
10. Confirm packaged wheel/source distribution includes the DRM helper binary and udev rules exactly as expected.

## 2. Evidence table

| Severity | Area | File(s) | Evidence | User-visible impact | Fix status | Validation |
|---|---|---|---|---|---|---|
| High | Audit execution | repository checkout/test environment | `git clone https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE.git` failed in this environment with `Could not resolve host: github.com`. | No production sign-off can be made because tests and release gate did not run locally. | Blocked | Run all commands in section 7 from a local checkout. |
| High | Capture / KWin / DRM | `README.md`, `src/nanoleaf_sync/capture/factory.py`, `src/nanoleaf_sync/runtime/engine_loop_capture.py` | README documents KDE Plasma 6 Wayland target, supported devices, single-monitor limitation, and desktop-entry context preference. Factory resolves auto/fallback backends. Capture worker supports full-frame and precomputed DRM zone colours. | Wrong backend, wrong monitor, or failed KWin authorization can prevent mirroring or use the wrong screen. | Documented | `nanoleaf-kde-sync-doctor --capture`; launch from desktop entry and terminal; verify selected backend and source size. |
| High | HDR / SDR colour | `src/nanoleaf_sync/config/normalize.py`, `src/nanoleaf_sync/runtime/engine_loop_process.py`, `src/nanoleaf_sync/runtime/color_pipeline.py` | Config normalization intentionally maps a legacy HDR + PQ + BT.2020 default combination back to SDR/sRGB/BT.709. Runtime warns that KWin Screenshot2 cannot preserve HDR colour accuracy. Colour pipeline applies gamut adaptation, SDR boost compensation, style/calibration, brightness, smoothing, and output limiting. | HDR users may see wrong colour if backend metadata or Plasma HDR state is misdetected. | Documented | Test SDR and HDR presets on Plasma HDR; compare neutral grey, saturated red/green/blue, dark scenes, and bright HDR highlights. |
| High | HID / USB output | `src/nanoleaf_sync/device/hid_transport.py`, `src/nanoleaf_sync/device/usb_driver.py` | HID transport has retry/open diagnostics, hidraw path resolution, busy-holder detection, write-progress metadata, and timeout write support. USB driver supports NL82K1/NL82K2 GRB channel mapping and stores device-reported count separately. | Device may fail to open, flicker, freeze, or require clear guidance if udev, busy handles, timeout, or disconnect occurs. | Documented | `nanoleaf-kde-sync-doctor --device`; `nanoleaf-kde-sync-smoke-test --hardware --send-test-frame`; unplug/replug during mirroring. |
| Medium | Smoke test docs | `docs/SMOKE_TEST.md`, `src/nanoleaf_sync/tools/smoke_test.py` | CLI skips USB initialization unless `--hardware` is passed; previous docs showed `--send-test-frame` alone. | User could think the LED output test ran when it was actually skipped. | Fixed | `nanoleaf-kde-sync-smoke-test --hardware --send-test-frame` on real hardware. |
| Medium | Calibration / zone count | `README.md`, `src/nanoleaf_sync/config/model.py`, `src/nanoleaf_sync/config/normalize.py`, `src/nanoleaf_sync/runtime/engine_loop_process.py` | README states manual strip count is authoritative; config model stores nested calibration and raw count; normalization prefers calibration count then configured count; process loop records configured/detected/effective source and mismatch state. | Wrong zone count or anchor mapping can shift all colours around the physical strip. | Documented | Set manual count to 48, run wizard, save/restart, verify count remains 48 and anchors TL/TR/BR/BL survive. |
| Medium | Runtime frame pacing | `src/nanoleaf_sync/runtime/engine_loop_context.py`, `src/nanoleaf_sync/runtime/engine_loop_capture.py`, `src/nanoleaf_sync/runtime/engine_loop_process.py` | Capture/process ring buffers are bounded. Capture worker rate-limits from governor/HID EWMA and drops frames when full. Process worker stops on incomplete mapping and resets state on capture gaps/dimension/source changes. | Poor pacing can produce latency, stale output, or flicker during fast content. | Documented | Run long mirroring session with diagnostics enabled; inspect frame drops, stale output, HID work EWMA, and capture-to-send latency. |
| Medium | Config persistence | `src/nanoleaf_sync/config/model.py`, `src/nanoleaf_sync/config/normalize.py`, `tests/test_config.py` | Canonical calibration block exists; normalization validates USB IDs/count bounds, preserves nested calibration, validates profiles and colour matrix, and tests cover several persistence/normalization cases. | Settings could be lost after save/load if a field is not round-tripped. | Test coverage present, not rerun | `pytest tests/test_config.py`; manually save settings/calibration, restart tray, inspect config. |
| Medium | Packaging / release gate | `pyproject.toml`, `scripts/release_gate.sh` | Package data includes udev rules and `capture/nanoleaf_drm_helper`; release gate runs version checks, runtime install verification, ruff, format, mypy, bandit, pip-audit, DRM helper build, wheel build/validation, and pytest coverage fail-under 75. | Broken packaging could omit helper files or ship an unvalidated wheel. | Documented | `./scripts/release_gate.sh` from a clean venv on Linux. |
| Low | Prior audit state | `CHANGELOG.md` | Changelog records recent stage 3-5 audit fixes, KWin invalid screen tracking, DRM helper fixes, colour path fixes, HID hardening, and packaging updates. | Indicates strong prior work, but changelog is not proof of current passing tests. | Documented | Compare current branch test results against changelog claims. |

## 3. Runtime path summary

1. **Configuration load/normalization**
   - `ConfigManager` loads config and passes through normalization.
   - Capture backend preference, display preset, HDR metadata defaults, zone count, calibration block, channel order, privacy zones, and LED calibration profiles are normalized.

2. **Backend selection**
   - `create_capture_backend()` resolves `prefer_backend`.
   - `auto` can use cached/fresh probe results and a fallback chain across `kmsgrab`, `kwin-dbus`, and `xdg-portal`.
   - Explicit backend selection bypasses probing.

3. **Capture worker**
   - `capture_worker_loop()` obtains the active backend.
   - If DRM zone patch capture is active and display-space zone rects are available, the worker attempts `capture(zone_rects=...)`.
   - Otherwise it captures a frame normally.
   - The capture result is either an RGB frame or precomputed per-zone RGB values.
   - The worker resolves frame dimensions, builds a frame context, and pushes the newest payload into a bounded capture ring buffer.

4. **Process worker**
   - `process_worker_loop()` pops the latest capture payload.
   - It derives image dimensions and brightness, handles black-frame degradation, verifies driver availability, evaluates configured vs detected device zone authority, and creates runtime zone artifacts.
   - If calibration mapping is incomplete or empty, mirroring is stopped rather than streaming wrong colours.
   - It builds colour context from capture metadata and source identity, resets smoothing on source/metadata changes, and constructs colour pipeline parameters.

5. **Colour pipeline**
   - `process_frame()` / `process_zone_colors()` samples zones or accepts precomputed zone colours.
   - Pipeline stages include letterbox-aware sampling, privacy-zone handling, temporal accumulation, SDR boost compensation, display gamut adaptation, colour style, LED calibration, neighbour spread, brightness scaling, adaptive smoothing, dark-zone output, predictive sync, and final 8-bit output.

6. **HID output**
   - `NanoleafUSBDriver` initializes HID transport, validates model number, records reported zone count, and uses configured zone count when present.
   - It sends generated zone colours through `HIDTransport` using TLV/HID report framing and live-send policies.
   - HID transport has open retry diagnostics, hidraw path mapping, busy-device guidance, write timing metadata, and timeout/error handling.

## 4. Colour/HDR assessment

Status: **partially correct, not production-certified in this pass**

Positive evidence:

- SDR defaults are explicit: `display_preset = "sdr"`, `hdr_transfer = "srgb"`, and `hdr_primaries = "bt709"`.
- Tests cover default SDR metadata and the legacy HDR-default migration case.
- Runtime stores and propagates colour context from capture metadata when available.
- Colour pipeline has deterministic per-stage handling for gamut adaptation, SDR boost compensation, style/calibration, brightness, smoothing, and final quantization.

Concerns:

- KWin Screenshot2 is explicitly warned as unable to preserve HDR colour accuracy.
- Normalization maps one legacy HDR/PQ/BT.2020 combination back to SDR, so HDR preset semantics are conservative rather than a guaranteed true HDR path.
- Real correctness depends on compositor HDR state, capture backend metadata confidence, SDR white reference, and display gamut context, none of which could be validated here.

Verdict: SDR path appears better covered than HDR. HDR must remain manually validated on the target KDE Plasma HDR environment before release.

## 5. Capture/DRM/KWin assessment

Status: **partially robust, fragile under real compositor and permission conditions**

Positive evidence:

- Backend constants, aliases, auto probe, cached winner, and fallback reporting are centralized.
- Fallback chain closes failed backend instances.
- Capture worker handles precomputed DRM zone colours and normal frames.
- Display-space zone scaling exists for DRM zone patch capture.
- Known limitations are documented: single-monitor flow and preferred desktop-entry launch context.

Concerns:

- KWin authorization and desktop-entry policy cannot be proven without a real Plasma session.
- KMS/DRM helper readiness cannot be proven without installed helper, setcap, and a real DRM device.
- Multi-monitor support remains a documented limitation.
- Real source-size correctness for DRM precomputed zones needs physical validation with known screen content.

Verdict: the design is careful, but production readiness remains blocked until real KDE/DRM validation passes.

## 6. Config/calibration persistence assessment

Status: **appears mostly robust from static inspection; requires end-to-end hardware validation**

Positive evidence:

- Canonical nested `CalibrationConfig` is present.
- Top-level legacy fields are consolidated into the calibration block.
- Manual configured zone count is preferred before detected USB count in runtime authority evaluation.
- Device-reported zone count is stored separately as diagnostics.
- Invalid VID/PID and zone counts are rejected or recovered with invalid config backup paths.
- Tests cover several calibration/config preservation cases.

Concerns:

- Save/load/reset flows were not executed locally.
- UI wizard state and physical anchors still require manual confirmation.
- A real 48-zone NL82K2 mismatch case must verify that detected count never silently overrides manual count.

Verdict: config and calibration persistence are structured correctly, but physical calibration validation is required before sign-off.

## 7. Test and command results

The required local commands were not run because the audit environment could not obtain a local checkout. The attempted checkout failed with DNS resolution failure:

```text
git clone https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE.git /mnt/data/nanoleaf_repo
fatal: unable to access 'https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE.git/': Could not resolve host: github.com
```

| Command | Result in this audit | Required follow-up |
|---|---|---|
| `python -m venv .venv` | Not run; no local checkout | Run from repository root. |
| `source .venv/bin/activate` | Not run; no local checkout | Run after venv creation. |
| `pip install -e .[test]` | Not run; no local checkout | Run from repository root. |
| `ruff check .` | Not run; no local checkout | Run and fix any findings. |
| `ruff format --check .` | Not run; no local checkout | Run and fix formatting drift. |
| `mypy src/nanoleaf_sync` | Not run; no local checkout | Run and fix type errors. |
| `pytest` | Not run; no local checkout | Run full suite. |
| `pytest --cov=src/nanoleaf_sync` | Not run; no local checkout | Run coverage check. |
| `bandit -r src` | Not run; no local checkout | Run security scan. |
| `pip-audit` | Not run; no local checkout | Run dependency audit. |
| `pre-commit run --all-files` | Not run; no local checkout | Run full pre-commit. |
| `./scripts/release_gate.sh` | Not run; no local checkout | Run final gate. |

The release gate script itself statically contains the expected checks: version check, runtime install verification, `ruff`, format check, `mypy`, `bandit`, `pip-audit`, DRM helper build, wheel build, wheel validation, and `pytest` with coverage fail-under 75.

## 8. Manual validation checklist

Target: CachyOS / Arch-family Linux, KDE Plasma 6 Wayland, supported Nanoleaf USB strip `NL82K2` / `0x37fa:0x8202`, 48 zones.

1. Install from the candidate package or editable checkout.
2. Install udev rules and reload/replug device.
3. Run:

   ```bash
   nanoleaf-kde-sync-doctor
   ```

4. Run:

   ```bash
   nanoleaf-kde-sync-doctor --capture
   nanoleaf-kde-sync-doctor --device
   ```

5. Run smoke test without hardware:

   ```bash
   nanoleaf-kde-sync-smoke-test
   ```

6. Run hardware smoke test and LED frame output:

   ```bash
   nanoleaf-kde-sync-smoke-test --hardware --send-test-frame
   ```

7. Start the tray app from the installed desktop entry:

   ```bash
   nanoleaf-kde-sync
   ```

8. Verify KWin authorization prompt and confirm capture succeeds after authorization.
9. Verify manual zone count remains **48** after device detection, settings save, tray restart, and app restart.
10. Run calibration pattern and verify physical TL/TR/BR/BL anchors.
11. Verify SDR preset with neutral grey, saturated RGB, dark scene, and fast UI motion.
12. Enable Plasma HDR and verify Auto/HDR preset behaviour with HDR and SDR content.
13. Verify low-latency mirroring during fast-moving content.
14. Unplug/replug the NL82K2 during mirroring and confirm recovery or clear error guidance.
15. Stop/start runtime from tray controls several times.
16. Close and restart the tray app; confirm no duplicate processes and no stale HID handle.
17. Inspect logs and diagnostics exports for privacy leaks, repeated capture errors, repeated HID errors, and unexpected live frame RGB dumps.
18. Run final release gate:

   ```bash
   ./scripts/release_gate.sh
   ```

## 9. Exact next engineering steps

1. Pull the audit branch locally.
2. Run all commands in section 7.
3. If any command fails, fix the defect directly and add regression tests.
4. Perform the section 8 physical validation checklist on the target CachyOS/KDE/NL82K2 setup.
5. Attach release-gate output and hardware validation notes to the PR before merging.
