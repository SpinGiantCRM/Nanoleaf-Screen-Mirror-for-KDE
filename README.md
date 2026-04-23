# Nanoleaf Screen Mirror for KDE

Personal-first Nanoleaf USB screen mirroring app for KDE Plasma 6 on Linux.

This repo is intentionally lean: app code, packaging, and only practical docs needed to install/run/troubleshoot.

## What it does

- Captures your active display on KDE Plasma 6
- Samples edge/zone colors
- Streams colors to supported Nanoleaf USB strips (`NL82K1`, `NL82K2`)
- Provides a tray app + settings + first-run display setup

## Install (Arch / CachyOS)

```bash
paru -S --needed python-dacite
cd packaging/arch
makepkg -si
```

## Quick start

```bash
nanoleaf-kde-sync-init-config
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync
```

Service-only mode:

```bash
nanoleaf-kde-sync-service
```

## Core commands

- `nanoleaf-kde-sync` — tray app (recommended)
- `nanoleaf-kde-sync-service` — headless runtime service
- `nanoleaf-kde-sync-init-config` — generate default config
- `nanoleaf-kde-sync-doctor` — environment/device diagnostics
- `nanoleaf-kde-sync-smoke-test` — quick functional sanity check
- `nanoleaf-kde-sync-autostart` — manage KDE autostart integration

## Practical docs

- [Hardware setup](docs/HARDWARE_SETUP.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Smoke test](docs/SMOKE_TEST.md)

## Release gate

Only CI needs to pass before release.

## Supported environment

- Linux
- KDE Plasma 6 (Wayland recommended)
- Supported Nanoleaf USB strip
