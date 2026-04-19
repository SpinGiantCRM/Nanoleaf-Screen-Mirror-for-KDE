# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.5.5] - 2026-04-19

## What's Changed
* Add missing `on_troubleshooting` handler to fix tray startup crash by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/116


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.5.4...v0.5.5

## [0.5.4] - 2026-04-19

## What's Changed
* Fix Settings UI ranges, add zone_sampling_stride control, and prefer CaptureArea in KWin capture by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/115


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.5.3...v0.5.4

## [0.5.3] - 2026-04-19

## What's Changed
* Refine HDR/latency behavior and refresh tray icon by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/114


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.5.2...v0.5.3

## [0.5.2] - 2026-04-19

## What's Changed
* Improve GUI launch robustness and add display configurator presets by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/113


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.5.1...v0.5.2

## [0.5.1] - 2026-04-19

## What's Changed
* Reduce latency; add Dynamic colour mode; Save-style settings; autostart & themed tray icon by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/110
* chore: align documentation versions and enforce version checks in CI by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/111
* fix: stabilize runtime loop shutdown behavior in CI tests by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/112


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.5.0...v0.5.1

## [0.5.0]

### Added
- Added XDG portal capture backend and wired config/UI support for portal-based capture workflows (PR #99).
- Integrated the alternative pipeline/platform systems path for broader runtime/capture flexibility (PR #102).

### Changed
- Optimized backend selection for CachyOS and enabled the `kmsgrab` path where available (PR #100).
- Improved visual fidelity with perceptual averaging and adaptive smoothing updates (PR #102).
- Applied follow-up capture/config stability improvements from CodeRabbit review feedback (PR #102).
- Refreshed README/troubleshooting docs and then standardized wording across setup, smoke-test, RC, and contribution docs (PR #101 and docs housekeeping follow-ups).
- Expanded changelog documentation entries so notable docs housekeeping is itemized instead of summarized in one broad line.

### Fixed
- Fixed KDE ScreenShot2 authorization by normalizing desktop launcher `Exec` handling and related desktop-entry nits (PR #98).
- Fixed portal capture and doctor backend-check regressions and resolved repo-wide Ruff lint violations (PR #99).
- Hardened CI with pytest retry/de-flake logic and strengthened color/dimension test reliability (PR #103 and PR #104).
- Fixed Qt module override behavior in primary-screen dimension detection tests (PR #105).

## [0.4.8]

### Changed
- Synced the project version to `0.4.8` for release packaging.
- Fixed KDE ScreenShot2 application identity handling and improved authorization diagnostics.
- Redacted launcher tokens in KDE diagnostics output.

## [0.4.7]

### Changed
- Synced the project version to `0.4.7` for release packaging.
- Added HDR conversion support in the KWin DBus capture backend.
- Improved real-mode KWin capture diagnostics and live settings feedback.
- Updated packaging metadata for modern setuptools/PEP 639 compatibility.

## [0.4.6]

### Changed
- Synced the project version to `0.4.6` for release packaging.
- Added autostart workflow and calibration-focused settings improvements.
- Fixed HID response framing autodetection and improved KWin authorization UX.
- Ensured release source archives include the updated `VERSION` file.

## [0.3.0]

### Changed
- Introduced `VERSION` as the unified release version source.
- Added checks to enforce version drift prevention in release workflows.

## [0.1.0] - Initial release

- Initial open-source release of Nanoleaf Screen Mirror for KDE.
