# Nanoleaf Screen Mirror for KDE

[![CI](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/workflows/ci.yml/badge.svg)](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/workflows/ci.yml)
[![Native bundle](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/workflows/native-bundle.yml/badge.svg)](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/workflows/native-bundle.yml)
[![License](https://img.shields.io/github/license/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE)](LICENSE)

Mirror screen-edge colours to **one Nanoleaf NL82K1/NL82K2 USB strip** on **KDE
Plasma 6 Wayland**. The Rust application includes a tray, Settings, manual strip
setup, calibration and acknowledged USB output. Closing Settings leaves the tray
running; **Stop mirroring** pauses output, and **Quit** exits the application.

The priorities are visible response time, faithful colour, delivered FPS, then
resources. KWin ScreenShot2 is the automatic capture backend. Optional
permission-mediated PipeWire/Vulkan streaming is available in Advanced. The native
bundle needs neither Python nor Qt, and capture needs no privileged DRM helper.

## Install

Use the Linux x86_64 `native.tar.gz` and matching checksum from a
[native 2.0.0 release](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/releases/tag/native-v2.0.0).
Native tags use `native-vX.Y.Z`; see the [2.0.0 release notes](docs/RELEASE_2_0_0.md).
PyPI `nanoleaf-kde-sync` **1.x** and GitHub `v1.9.3` contain the retired Python app;
[existing installations can migrate while preserving settings](docs/LEGACY_PYTHON.md).
In a fresh download directory containing both native release files:

```bash
sha256sum -c native.tar.gz.sha256
tar -xzf native.tar.gz
./native/bin/nanoleaf-native --install-native
```

Open **Nanoleaf Screen Mirror (Rust)** from KDE's application launcher. Installation
uses your user account, preserves configuration and keeps previous native
versions for rollback. It does not start mirroring or enable login startup.

Optional native package routes are available after their registry publication:

- **PyPI/pipx:** `pipx install nanoleaf-kde-sync==2.0.0`, then
  `~/.local/bin/nanoleaf-kde-sync --install-native` creates the native KDE launcher.
- **Arch/AUR:** the `nanoleaf-kde-sync-bin` recipe packages the native release;
  use the checked-out recipe until its AUR listing is published.

See [package availability, requirements and upgrades](docs/PACKAGING_AUR.md).
The PyPI wheel is a pure-Python installer with no native binaries. Explicit
`--install-native` downloads and verifies the pinned Linux x86_64 release
(glibc 2.39+); later commands execute the installed Rust app.

For source builds, requirements and CI artifacts, follow the
[installation guide](docs/NATIVE_INSTALL.md). CI artifacts are test builds;
a passing build does not establish physical output on every desktop or strip.

## Set up your strip

Open **Settings and calibration** from the tray. An incomplete configuration
opens **Strip setup**, with four guided steps:

1. **Connect your strip** — choose the model and screen, enter your actual
   **Manual zone count**, and use **Check USB connection**. Choose
   **Save count & continue**; reported counts never replace the manual value.
2. **Locate the corners** — use **Preview zone** and **Locate zone**, then assign
   four distinct corner indices. Numbering starts at zero. Choose
   **Save corners & continue**.
3. **Check the colours** — test red, green, blue, grey and black. Adjust channel
   order or strip direction if needed; **Save / Apply** before retesting.
   Choose **Save colour settings & continue**.
4. **Ready to mirror** — **Finish setup** saves and returns to Mirroring;
   **Save & start mirroring** also begins output.

Previews pause mirroring and clear after ten seconds. Use Start to resume normal
output. **Save / Apply** keeps Settings open; **Reload saved** discards unsaved
edits. **Mirroring** contains daily controls and **Use fast response**.
**Colour calibration** contains measured profiles, while **Advanced** contains
capture selection, login startup and diagnostics.
[Setup details and troubleshooting](docs/NATIVE_INSTALL.md#first-launch-and-strip-setup)
cover permissions, missing monitors and colour checks.

## Daily use and recovery

Use the tray to Start, Stop, open Settings or Quit. **Target FPS** is a target;
acknowledged USB output can run below it. **Advanced** contains
capture selection, login startup and software timing.
**Launch native tray at login** and **Start mirroring when the tray launches**
are separate choices.

A screen lock, sleep transition or loss of session monitoring stops the current
session. After recovery, select Start. Revoking portal sharing also requires an
explicit restart. A missing selected screen is retried without switching to a
different screen. Keep only one application in control of the strip.

Run `~/.local/bin/nanoleaf-native --doctor` for read-only readiness and device
detection. It does not test LED output. Before upgrading or rolling back, Quit the
tray. [Upgrade and rollback instructions](docs/NATIVE_INSTALL.md#upgrade-and-rollback)
explain how to keep the app and capture helper together.

Your configuration remains at `~/.config/nanoleaf-kde-sync/config.toml`.
Validated saves retain private backups, calibration profiles and unknown fields.
Binary rollback does not restore earlier settings.

## Scope and verification limits

One selected monitor, one USB strip and a manually configured zone count.
Captured SDR display-referred pixels remain SDR, including on HDR desktops.
Unsupported raw PQ/HLG/FP16 and privileged DRM capture fail explicitly. The
[retired Python implementation](docs/LEGACY_PYTHON.md) remains in Git history;
previous native bundles provide runtime rollback.

Real NL82K2 output and physical USB reconnect have been tested, with user
confirmation that colours resumed. Portal Stop sharing and worker recovery have
also been exercised. NL82K1 physical output, physical suspend/resume, optical
latency, colourimeter accuracy, power and long-duration soak behaviour remain
unverified. Software response and USB acknowledgement timing do not measure
emitted light. See [gameplay observations](docs/GAMEPLAY_PROFILING.md) and
[session recovery limits](docs/SESSION_RECOVERY.md).

## Development and evidence

- [Native application development](native/app/README.md)
- [Repository map and verification locations](docs/ai/repo-map.md)
- [Native completion and measured performance](docs/RUST_NATIVE_COMPLETION.md)
- [Streaming Vulkan backend](docs/RUST_STREAM_VULKAN.md)
- [Changelog](CHANGELOG.md)

Rust contracts, generated colour/protocol replays, recovery and packaging tests
run in CI. Historical fixtures remain regression inputs; the Python/PyQt6 app, bridge
and historical Python packaging are retired. The PyPI installer and AUR binary
recipe deliver the native Rust app/helper pair. Evidence in `perf/` separates software
timing from physical observations. Release history and tags remain available;
artifact cleanup protects the newest native download for main and open pull
requests.
