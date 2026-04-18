# Repository map and ownership guide

This document is the "where do I start?" map for the repository.
Use it together with `docs/TECHNICAL_DESIGN.md` (architecture intent) and `docs/TROUBLESHOOTING.md` (operational fixes).

## 1) Project purpose (source of truth)

`nanoleaf-kde-sync` mirrors KDE Plasma screen colors to supported Nanoleaf USB devices with low latency and predictable behavior on Linux.

Primary target environment:
- KDE Plasma 6
- Arch / CachyOS packaging workflow
- USB HID-connected Nanoleaf PC Screen Mirror LS (`NL82K2`) and Pegboard Desk Dock (`NL82K1`)

## 2) Top-level directory map

| Path | Why it exists | Edit here when you need to... |
| --- | --- | --- |
| `README.md` | Primary end-user landing page and install flow. | Update user-facing setup narrative and high-level status. |
| `CONTRIBUTING.md` | Contributor workflow and guardrails. | Change development expectations and contribution process. |
| `pyproject.toml` | Packaging metadata, Python requirements, CLI entrypoints. | Add dependencies, bump version, or add/rename CLI commands. |
| `src/nanoleaf_sync/` | Application source code (capture, processing, runtime, UI, device protocol). | Implement product behavior. |
| `tests/` | Unit/integration regressions and release safety checks. | Add tests for feature fixes and regressions. |
| `docs/` | Human documentation, release process, smoke/RC guidance. | Document behavior, testing, release process. |
| `packaging/arch/` | Arch package metadata and install hooks. | Update Arch packaging/release details. |
| `scripts/` | Build/release and host setup helpers. | Maintain automation used by maintainers/CI. |
| `assets/` | Distributed static files (udev rules, icons). | Update device permissions or branded assets. |
| `installer/` | Compatibility wrapper for installer path stability. | Rarely edit; keep as forwarding shim. |

## 3) Application code map (`src/nanoleaf_sync`)

### Runtime/control plane

| Path | Responsibility |
| --- | --- |
| `service.py` | Long-running service bootstrap and orchestration entrypoint. |
| `runtime/startup.py` | First-run startup flow and mode/device initialization. |
| `runtime/engine.py` | Main synchronization loop and per-frame pipeline execution. |
| `runtime/processing.py` | Frame-to-colors processing helpers and runtime glue. |
| `runtime/state.py` | Runtime status snapshots exposed to UI and diagnostics. |
| `runtime/errors.py` | Error normalization into user-facing categories and hints. |
| `runtime/zones.py` | Zone sizing/clamping helpers for device update payloads. |

### Capture backends

| Path | Responsibility |
| --- | --- |
| `capture/factory.py` | Capture backend selection (`kmsgrab` preferred, KWin fallback). |
| `capture/kmsgrab.py` | FFmpeg/DRM capture path and HDR-aware frame handling. |
| `capture/kwin_dbus.py` | KWin DBus ScreenShot2 and legacy fallback implementation. |
| `capture/mock_capture.py` | Deterministic synthetic capture for tests/mock mode. |
| `capture/replay_capture.py` | Replay capture frames from serialized test fixtures. |
| `capture/interfaces.py` | Capture protocol/interface contracts. |

### Color processing

| Path | Responsibility |
| --- | --- |
| `color/analyzer.py` | Representative color extraction and sampling. |
| `color/zone_mapper.py` | Mapping sampled colors to device zones/layouts. |
| `color/hdr.py` | HDR transforms and color-space transfer handling. |

### Device + transport

| Path | Responsibility |
| --- | --- |
| `device/nanoleaf_usb.py` | Public USB driver facade/compat import shim. |
| `device/usb_driver.py` | USB device session lifecycle and high-level operations. |
| `device/hid_transport.py` | HID read/write transport with timeout/retry behavior. |
| `device/protocol.py` | TLV command encoding/decoding and protocol constants. |
| `device/protocol_stub.py` | Test-oriented protocol shim where full hardware path is not required. |
| `device/mock.py` + `device/mock_driver.py` | Mock device behavior for safe/no-hardware operation. |
| `device/interfaces.py` | Driver contracts used across runtime + tests. |

### Config, UI, and tools

| Path | Responsibility |
| --- | --- |
| `config/model.py` | Typed config model/defaults. |
| `config/normalize.py` | Validation + normalization of external config input. |
| `config/store.py` | Config persistence/load/save behavior. |
| `ui/tray_app.py` + `ui/tray.py` | Tray application launch and compatibility entrypoint. |
| `ui/settings_dialog.py` | User settings dialog and validation UX. |
| `ui/zone_presets.py` | Preset zone layouts/options exposed in UI. |
| `ui/qt_lazy.py` | Deferred Qt import helpers for CLI/test friendliness. |
| `tools/doctor.py` | `nanoleaf-kde-sync-doctor` diagnostics command. |
| `tools/smoke_test.py` | `nanoleaf-kde-sync-smoke-test` one-shot runtime check. |
| `tools/config_init.py` | First-run config initialization utility. |
| `tools/rc_runner.py` | RC validation runner used by release workflows. |
| `tools/color_kmeans.py` + `tools/output_format.py` | Utility helpers for color experiments and CLI formatting. |

## 4) Tests map (`tests/`)

Tests are organized by behavior area rather than a strict mirror of source paths.

- `tests/device/`: protocol, HID transport, and driver contract tests.
- `tests/test_runtime_*`: runtime loop, error translation, startup flow, and service behavior.
- `tests/test_*capture*`: backend behaviors and fallback handling.
- `tests/test_settings_dialog.py`, `tests/test_tray_*`: UI-facing status/actions and labels.
- `tests/test_release_*`, `tests/test_validate_release_promotion.py`: release metadata/checklist regression guards.
- `tests/test_doctor.py`, `tests/test_smoke_test`-adjacent coverage: diagnostics workflows.

When adding a feature, place tests near existing coverage for that subsystem; if none exists, create a clearly named new test module.

## 5) Documentation map (`docs/`)

| File | Audience |
| --- | --- |
| `README.md` | Primary docs index (start here for docs navigation). |
| `INSTALL_ARCH.md` | End users installing on Arch/CachyOS. |
| `HARDWARE_SETUP.md` | Users enabling real USB hardware access. |
| `TROUBLESHOOTING.md` | Users debugging setup/runtime issues. |
| `SMOKE_TEST.md` | Maintainers/QA validating basic behavior. |
| `TECHNICAL_DESIGN.md` | Developers needing architecture and pipeline details. |
| `RELEASE_CHECKLIST.md`, `RC_TEST_MATRIX.md`, `RELEASE_TOOLCHAIN.md` | Maintainers preparing and validating releases. |
| `CHANGELOG.md` | Release and unreleased change history. |
| `DRIVER_INTEGRATION_PLAN.md` | Device integration roadmap/history context. |

## 6) Packaging + installation map

- `packaging/arch/PKGBUILD`: package metadata, build/install phases, runtime dependencies.
- `packaging/arch/nanoleaf-kde-sync.install`: post-install hooks.
- `install-nanoleaf-kde-sync.sh`: AppImage-oriented installer with desktop entry/config/udev setup.
- `installer/install-nanoleaf-kde-sync.sh`: path-stability wrapper that forwards to top-level installer.
- `scripts/setup_udev.sh`: direct helper to install udev permissions rules.

## 7) "Unnecessary or duplicate" policy used in this repo

The project intentionally keeps a small number of compatibility duplicates (for example, the installer wrapper under `installer/`) to preserve older automation paths.
A file is treated as unnecessary only when it has no active runtime, packaging, or compatibility purpose.

When removing files, update this map and the docs index in the same change so future readers do not need to rediscover intent.
