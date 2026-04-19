# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Added core project health docs: troubleshooting, smoke-test guide, RC test matrix, hardware setup, security policy, and code of conduct.
- Added CI lint/type checks and Python 3.12 test coverage.

### Changed
- Capture factory now accepts explicit HDR args; KWin DBus capture forwards HDR metadata and relies on conversion logic to interpret it.
- Empty `mode` values now raise a clear `ValueError` instead of defaulting to `full-real`.
- Settings dialog smoothing label now describes user-visible behavior (`0 = smooth`, `100 = instant`).
- Smoke test capture dimensions now use primary-screen detection with explicit fallback constants.
- Tray startup now handles config/service initialization failures gracefully and shows a user-facing warning.

### Fixed
- Doctor dependency guidance now recommends `pip install -e .[test]` instead of referencing `docs/requirements.txt`.

## [0.1.0] - Initial release

- Initial open-source release of Nanoleaf Screen Mirror for KDE.
