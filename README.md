# nanoleaf-kde-sync

`nanoleaf-kde-sync` mirrors KDE Plasma screen colors to supported Nanoleaf USB light devices on Linux.

This repository is prepared as a **first public release candidate** focused on **Arch/CachyOS + KDE**.

## Quick start (Arch/CachyOS)

```bash
cd packaging/arch
makepkg -si
nanoleaf-kde-sync-init-config --mode full-mock
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync
```

## Installed commands

- `nanoleaf-kde-sync` — tray app
- `nanoleaf-kde-sync-service` — service-only runtime
- `nanoleaf-kde-sync-doctor` — diagnostics
- `nanoleaf-kde-sync-smoke-test` — capture/device smoke checks
- `nanoleaf-kde-sync-init-config` — first-run mode presets

## What is release-candidate ready now

- KWin capture path + runtime capture fallback selection
- Nanoleaf USB real driver path (with supported model validation)
- Doctor + smoke-test tooling
- Arch/CachyOS packaging assets (`PKGBUILD`, `.install`, desktop, icon, udev rule)
- Tray app with non-blocking doctor/smoke-test actions

## Intentionally deferred beyond first RC

- non-Arch distro packaging
- advanced effects/animations
- broader button-event integrations

## Documentation map

- Install: `docs/INSTALL_ARCH.md`
- Hardware/udev: `docs/HARDWARE_SETUP.md`
- Troubleshooting: `docs/TROUBLESHOOTING.md`
- Smoke-test procedure: `docs/SMOKE_TEST.md`
- Release checklist: `docs/RELEASE_CHECKLIST.md`
- Changelog: `docs/CHANGELOG.md`
