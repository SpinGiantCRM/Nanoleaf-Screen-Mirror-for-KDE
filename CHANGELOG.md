# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
