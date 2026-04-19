# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Added core project health docs: troubleshooting, smoke-test guide, RC test matrix, hardware setup, security policy, and code of conduct.
- Added CI lint/type checks and Python 3.12 test coverage.

### Changed
- README now provides a clearer tray-first startup flow while still documenting direct service startup as an alternative.
- README troubleshooting highlights now use consistent KWin ScreenShot2 wording and clearer Wayland/environment guidance.
- README now links key operational docs in one documentation section and aligns quick-start wording with current commands.
- `docs/TROUBLESHOOTING.md` now uses clearer labels and action wording for KWin authorization, HID/udev checks, HDR tuning, and reconnect steps.
- `docs/HARDWARE_SETUP.md` now standardizes USB ID heading text, udev rule wording, and logout/login instructions.
- `docs/SMOKE_TEST.md` now clarifies that the optional test-frame command validates device output with a low-brightness RGB pattern.
- `docs/RC_TEST_MATRIX.md` now makes X11 rows explicitly compatibility checks and clarifies expected behavior for real-capture vs mock scenarios.
- `CONTRIBUTING.md` release guidance now reads: create and push a tag only after the release checklist is fully complete.
- Changelog documentation entries were expanded so each notable docs housekeeping change is recorded individually instead of in a single broad summary.
- Capture factory now accepts explicit HDR args; KWin DBus capture forwards HDR metadata and relies on conversion logic to interpret it.
- Empty `mode` values now raise a clear `ValueError` instead of defaulting to `full-real`.
- Settings dialog smoothing label now describes user-visible behavior (`0 = smooth`, `100 = instant`).
- Smoke test capture dimensions now use primary-screen detection with explicit fallback constants.
- Tray startup now handles config/service initialization failures gracefully and shows a user-facing warning.

### Fixed
- Doctor dependency guidance now recommends `pip install -e .[test]` instead of referencing `docs/requirements.txt`.


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
