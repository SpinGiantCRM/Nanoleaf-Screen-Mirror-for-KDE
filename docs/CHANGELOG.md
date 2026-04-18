# Changelog

## Unreleased

### Release/install reliability fixes
- Fixed lazy Qt exports to include `QComboBox`, preventing Settings dialog crashes on open.
- Fixed the standalone installer cleanup trap so `set -euo pipefail` runs do not fail with `temp_rule: unbound variable`.
- Switched Arch/CachyOS user guidance to recommend `makepkg -si` as the primary install path.
- Clarified AppImage status on Arch/CachyOS as an experimental/secondary path.
- Made AppImage build/runtime Python invocation explicitly use Python 3.11 to avoid mixing 3.11 wheels with host Python 3.14.
- Changed default preferred real capture backend to `kwin-dbus` for KDE truthfulness.

### Release engineering
- Added GitHub Actions CI workflow for Linux tests and Arch packaging metadata sanity checks.
- Added GitHub Actions build workflow that produces `sdist` + `wheel` artifacts and uploads them.
- Added tag-driven GitHub release workflow that publishes built distribution artifacts.

### Tray UX
- Updated tray **Run Doctor** and **Run Smoke Test** actions to execute asynchronously in the background.
- Added tray completion/failure notifications with captured command output preview.
- Prevented duplicate doctor/smoke actions by disabling actions while background jobs are running.

### Packaging/install consistency
- Added release-asset consistency tests covering packaged docs, desktop, icon, and udev paths.
- Tightened install/release docs so package paths and manual setup paths agree.

### Documentation/supportability
- Refreshed top-level README to reflect first RC scope and quick-start flow.
- Added dedicated troubleshooting guide.
- Added GitHub issue templates for bug reports and feature requests.
- Updated release checklist to match CI/build/release process and Arch package workflow.

## 0.1.0

- Promoted the current release-engineering, reliability, and documentation improvements from **Unreleased** into the 0.1.0 release.

## 0.0.3

- Added Arch/CachyOS distribution assets:
  - `packaging/arch/PKGBUILD`
  - `packaging/arch/nanoleaf-kde-sync.install`
- Added first-run config helper command with mode presets:
  - `nanoleaf-kde-sync-init-config --mode {full-mock,capture-real,full-real}`
- Added tray first-run config auto-initialization and mode/device menu labels.
- Added smoke-test launch action from tray menu.
- Added/expanded docs for install, smoke-test, hardware setup, and release checklist.

## 0.0.2

- Added HDR-aware conversion utilities (`HDRMetadata`, `convert_frame_to_srgb8`) with EOTF handling and tone mapping.
- Added zone calibration mapping controls (`zone_offset`, `reverse_zones`, `device_zone_count`, `explicit_zone_map`).
- Wired calibration controls into runtime and settings UI.

## 0.0.1

- Implemented capture framework, color analysis, and service/tray scaffolding.
- Added mock device/capture paths for no-hardware development and testing.

## 0.0.0

- Initial scaffold for package structure, tests, and technical design notes.
