# Repository map for AI contributors

Use this map to find likely patch and test locations. Always inspect the live files before editing.

## HID / protocol / device

- `src/nanoleaf_sync/device/protocol.py` — Nanoleaf TLV command constants, response parsing, and protocol errors.
- `src/nanoleaf_sync/device/hid_transport.py` — low-level HID transport wrapper.
- `src/nanoleaf_sync/device/usb_driver.py` — Nanoleaf USB driver, device open/probe behavior, output writes.
- `src/nanoleaf_sync/device/interfaces.py` — driver protocol and USB ID data structures.
- `tests/device/` and `tests/test_runtime_real_driver_flow.py` — device/protocol/driver coverage.
- `docs/HARDWARE_SETUP.md` and `docs/TROUBLESHOOTING.md` — user-facing HID setup and failure workflows.

## Config validation / loading

- `src/nanoleaf_sync/config/model.py` — dataclass config model.
- `src/nanoleaf_sync/config/normalize.py` — migration, normalization, and validation rules.
- `src/nanoleaf_sync/config/store.py` — config paths, default/mode configs, load/save manager.
- `src/nanoleaf_sync/config/presets.py` — preset vocabulary and normalization helpers.
- `src/nanoleaf_sync/tools/config_init.py` and `src/nanoleaf_sync/tools/reset.py` — CLI config init/reset flows.
- `tests/test_config.py`, `tests/test_config_init.py`, and `tests/test_reset_tool.py` — config/tooling coverage.

## Runtime loop / lifecycle

- `src/nanoleaf_sync/runtime/engine.py` — frame processing and main runtime loop.
- `src/nanoleaf_sync/runtime/startup.py` — backend initialization, priority handling, lifecycle wrapper.
- `src/nanoleaf_sync/runtime/state.py` — shared runtime state and status snapshots.
- `src/nanoleaf_sync/runtime/output_session.py` — exclusive output ownership/session state.
- `src/nanoleaf_sync/service.py` — service orchestration and status handling.
- `src/nanoleaf_sync/ui/tray_app.py` — tray Start/Stop/Quit/settings interactions.
- `tests/test_runtime_engine.py`, `tests/test_runtime_startup.py`, `tests/test_service_robustness.py`, `tests/test_service_status*.py`, and `tests/test_tray_*` — lifecycle coverage.

## Calibration / mapping / colour

- `src/nanoleaf_sync/runtime/anchor_calibration.py` — corner anchor validation and zone mapping derivation.
- `src/nanoleaf_sync/runtime/calibration_resolver.py` — effective calibration mapping snapshots.
- `src/nanoleaf_sync/runtime/zone_derivation.py` and `src/nanoleaf_sync/runtime/zones.py` — effective source zones and sampling.
- `src/nanoleaf_sync/color/zone_mapper.py` and `src/nanoleaf_sync/color/hdr.py` — mapping and HDR helpers.
- `src/nanoleaf_sync/runtime/color_processing.py`, `srgb.py`, and `compositor.py` — color style, calibration, and SDR/HDR compensation.
- `src/nanoleaf_sync/ui/calibration_*.py`, `src/nanoleaf_sync/ui/zone_calibration.py`, and `src/nanoleaf_sync/ui/zone_presets.py` — guided calibration and UI mapping helpers.
- `tests/test_*calibration*.py`, `tests/test_zone*.py`, `tests/test_hdr.py`, and `tests/test_color_accuracy_pipeline.py` — calibration/mapping/color coverage.

## Capture backends

- `src/nanoleaf_sync/capture/factory.py` — backend creation, auto-probe policy, cache/report state, manual portal benchmark.
- `src/nanoleaf_sync/capture/backend_selection.py` and `backend_normalization.py` — backend name normalization and support checks.
- `src/nanoleaf_sync/capture/kwin_dbus.py` — KWin ScreenShot2 capture backend.
- `src/nanoleaf_sync/capture/xdg_portal.py` — xdg-desktop-portal backend.
- `src/nanoleaf_sync/capture/kmsgrab.py` — KMS grab backend.
- `src/nanoleaf_sync/capture/auto_probe.py`, `probe_models.py`, `probe_timing.py`, and `latency_probe.py` — probe/latency measurement infrastructure.
- `src/nanoleaf_sync/capture/dimensions.py` — capture dimension detection and resolution.
- `tests/test_auto_probe.py`, `tests/test_kwin_dbus_capture.py`, `tests/test_xdg_portal_robustness.py`, `tests/test_capture_factory_threading.py`, and `tests/test_dimensions.py` — capture coverage.
- `docs/AUTO_BACKEND.md`, `docs/SMOKE_TEST.md`, and `docs/TROUBLESHOOTING.md` — capture troubleshooting docs.

## Doctor / tooling

- `src/nanoleaf_sync/tools/doctor.py` — environment, capture, device, mode, and probe checks.
- `src/nanoleaf_sync/tools/smoke_test.py` — quick capture/device/output sanity check.
- `src/nanoleaf_sync/tools/autostart.py`, `reset.py`, `config_init.py`, and `output_format.py` — support CLIs.
- `src/nanoleaf_sync/runtime/readiness_check.py` and `diagnostics_exports.py` — readiness status and diagnostic exports.
- `scripts/check_calibration_guardrails.py`, `scripts/check_release_versions.py`, and install helper scripts — repository tooling.
- `tests/test_doctor.py`, `tests/test_smoke_test.py`, `tests/test_readiness_check.py`, `tests/test_backend_diagnostics_reporting.py`, and `tests/test_*tool*.py` — tooling coverage.

## Packaging / CI

- `pyproject.toml` — package metadata, dependencies, script entry points, pytest/ruff/mypy config.
- `README.md` — install, quick start, release gate, supported environment, and known limitations.
- `packaging/arch/PKGBUILD` and `packaging/arch/nanoleaf-kde-sync.install` — Arch package metadata and install hooks.
- `assets/udev/` and `scripts/setup_udev.sh` — udev permission setup.
- `docs/nanoleaf-kde-sync.desktop` and `src/nanoleaf_sync/desktop_entry.py` — desktop-entry authorization/install behavior.
- `.github/workflows/ci.yml` and `.github/workflows/release.yml` — CI and release automation.
- `.github/actions/arch-metadata-validation/action.yml` and `.github/PULL_REQUEST_TEMPLATE/release.md` — release/package validation support.
- `tests/test_check_release_versions.py`, `tests/test_desktop_entry.py`, and CI-relevant command coverage in `AGENTS.md` — packaging/CI tests.
