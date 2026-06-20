# Changelog

## v1.0.0 — Public launch

First public release of Nanoleaf Screen Mirror for KDE.

### Features

- Real-time edge/zone screen mirroring to Nanoleaf USB strips on KDE Plasma 6 (Wayland)
- Tray app with settings, setup wizard, calibration, and diagnostics
- Capture backends: KWin DBus (preferred) with portal/kmsgrab fallbacks
- Arch/CachyOS packaging via PKGBUILD and local build scripts

### Quality & security

- Hardened CI: Semgrep, CodeQL, dependency review, Dependabot, bandit, pip-audit, gitleaks
- Security regression tests for doc paths, config writes, and HID validation
- Headless Qt tests for critical tray/settings flows
- User documentation shipped in the Arch package

### Fixes in this release

- Settings Save + Close no longer double-restarts mirroring
- Troubleshooting guide opens correctly from installed packages
- Setup wizard cancel copy clarifies draft-saving behavior
