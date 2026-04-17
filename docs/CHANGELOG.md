## 0.0.0 (scaffold)
- Added repository scaffold: `src/` modules, `tests/`, packaging metadata, `README.md`.
- Added `TECHNICAL_DESIGN.md` and initial architecture notes.

## 0.0.1 (pipeline framework)
- Implemented capture framework scaffolding:
  - `KMSGrabCapture` (DRM/KMS placeholder + fallback path)
  - `KWinDBusScreenshotCapture` (stub)
  - `ScreenCapture` facade (fallback-first design)
- Added color analysis algorithms:
  - average color
  - NumPy k-means dominant colors (latency-bounded sampling)
  - per-zone averaging
- Added device layer scaffolding:
  - `NanoleafUSBDriver` (HID protocol stub with documented report packing placeholder)
  - `MockNanoleafUSBDriver` for no-hardware development
- Added service + KDE UI:
  - `NanoleafSyncService` main loop (capture → color → calibration → USB)
  - JSON config manager (`~/.config/nanoleaf-kde-sync/config.json`)
  - PyQt6 tray app (Start/Stop/Settings/Quit)
  - KDE autostart `.desktop` file
- Added initial unit test coverage for capture fallback behavior (mock device path).

## 0.0.2 (HDR correctness + calibration)
- Added HDR-aware conversion utilities (`HDRMetadata`, `convert_frame_to_srgb8`) with:
  - EOTF decoding (`srgb`, `pq`, `hlg`, `linear`)
  - primaries conversion (`bt709`, `bt2020`)
  - tone mapping into device-friendly `sRGB uint8`
- Added zone-to-strip calibration mapping:
  - `zone_offset`, `reverse_zones`
  - `device_zone_count` and optional `explicit_zone_map`
- Wired calibration into the service pipeline and exposed controls in the tray settings UI.

## 0.0.3 (deployment/demo readiness)
- Added `MockScreenCapture` backend so the app runs and produces meaningful colors even while DRM/KWin capture are still placeholders.
- Updated defaults to use `use_mock_device=true` and `use_mock_capture=true` for out-of-the-box operation.
- Added console script entry points:
  - `nanoleaf-kde-sync` (tray UI)
  - `nanoleaf-kde-sync-service` (service main loop)
- Updated README to document installation and the mock vs real capture/USB settings.

## Unreleased
- Arch/CachyOS distribution assets:
  - added `packaging/arch/PKGBUILD`
  - added `packaging/arch/nanoleaf-kde-sync.install`
  - package now installs desktop entry, icon, udev rule, and docs.
- First-run UX improvements:
  - added `nanoleaf-kde-sync-init-config` with safe mode presets (`full-mock`, `capture-real`, `full-real`)
  - tray now auto-creates first-run config if missing.
- Tray UX polish:
  - explicit mode/device labels in menu
  - clearer status message wording for device connection state
  - smoke-test launch action from tray menu.
- Documentation polish for end users:
  - updated top-level README install/first-run flow
  - added `docs/INSTALL_ARCH.md`
  - added `docs/RELEASE_CHECKLIST.md`
  - refreshed hardware + smoke-test guidance.
- Awaiting official Nanoleaf USB “PC Screen Mirror LS protocol” bytes to implement real HID report packing.
- Awaiting a concrete DRM/KMS + DMA-BUF binding implementation for true zero-copy low-latency capture.
- Awaiting a real KWin D-Bus screenshot call implementation (currently stubbed).
- Capture backend unification via a single `capture.factory` used by both runtime and tests.
- Config hardening:
  - atomic JSON writes (temp file + replace)
  - validation/clamping of brightness/smoothing/FPS/zone rectangles
  - corruption-safe config load.
- Service loop hardening:
  - per-frame exception handling (no single backend error kills the loop)
  - `is_running()` + `get_status()` for stable UI/status integration.
- UI hardening:
  - Settings dialog now preserves existing config fields (no silent HDR resets)
  - removed UI reliance on private `service._thread`.
- USB layer refactor (still stubbed protocol bytes):
  - separated transport (hid write/open/close) from protocol packing.
- Test suite expanded significantly around config, HDR conversion contract, zone mapping, and service robustness with injected mocks.
- Added `.gitignore` and `pyproject.toml` for more predictable deployment/CI installs.

