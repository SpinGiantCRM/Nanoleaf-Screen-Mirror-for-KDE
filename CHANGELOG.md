# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.6.5] - 2026-04-21

## What's Changed
* Add device model selection, SDR boost and UI/runtime improvements by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/144
* Redesign calibration to corner-anchor workflow by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/145
* ci: explicitly install pytest-cov in CI install step by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/146


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.6.4...v0.6.5

## [0.6.4] - 2026-04-21

## What's Changed
* Refactor calibration to live auto-send workflow and remove manual send/apply actions by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/141
* Preserve corner-refinement config, clear stale device metadata, and quiet startup diagnostics by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/142
* Improve tray UX, fix calibration preview HID conflict, and preserve settings on rerun by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/143


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.6.3...v0.6.4

## [0.6.3] - 2026-04-20

## What's Changed
* Fix tray Start crash path, localize corner calibration, and compact wizard layout by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/138
* Harden XDG portal negotiation and stream shutdown by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/139
* Improve settings UI tooltips, first-run tray behavior, and startup/config diagnostics by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/140


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.6.2...v0.6.3

## [0.6.1] - 2026-04-20

## What's Changed
* Per-corner calibration + honest latency diagnostics and UX cleanup (tray & setup wizard) by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/136


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.6.0...v0.6.1

## [0.6.0] - 2026-04-20

## What's Changed
* Rework setup/settings UX and fix zone calibration plumbing by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/133
* Fix probe tie-break and add Qt-stub fallbacks for dialogs by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/134
* Fix calibration preview RGB scaling helper and remove unused import by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/135


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.5.9...v0.6.0

## [0.5.9] - 2026-04-20

## What's Changed
* Unify calibration state; add combined corner+offset calibration and predictable latency checker by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/132


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.5.8...v0.5.9

## [0.5.8] - 2026-04-20

## What's Changed
* Calibration sequencing, coverage sanity and visible Diagnostics/Calibration Lab by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/131


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.5.7...v0.5.8

## [0.5.7] - 2026-04-20

## What's Changed
* Fix calibration wizard/test UX and harden runtime/config recovery paths by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/119
* Add latency measurement and backend auto-selection plan by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/120
* Add startup-safe capture backend auto-probing (probe_backends) by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/121
* Add auto backend probe controls, caching, and fallback logging by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/122
* Persist auto-probe policy/signature, implement re-probe rules, and add reset actions by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/123
* Expose capture backend decision metadata across runtime, tray/settings, and diagnostics by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/124
* Scoped cleanup: centralize capture backend selection, probe utilities, and config serialization by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/125
* docs: document policy-aware auto backend behavior and troubleshooting by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/126
* Add auto-probe, service status, config normalization, and doctor CLI tests by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/127
* docs: add repo cull audit with trim recommendations by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/128
* Complete repo cull audit: docs cleanup, udev standardization, rc_runner tests, and test fixes by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/129
* Remove obsolete REPO_CULL_AUDIT document by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/130


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.5.6...v0.5.7

## [0.5.6] - 2026-04-20

## What's Changed
* Add first-run zone calibration wizard and runtime derived zone mapping by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/117
* Optimize capture/runtime hot paths and tighten RGB conversion safety by @SpinGiantCRM in https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/118


**Full Changelog**: https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/compare/v0.5.5...v0.5.6

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
