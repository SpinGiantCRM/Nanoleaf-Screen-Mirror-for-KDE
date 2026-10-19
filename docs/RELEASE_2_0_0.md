# Native 2.0.0

Release tag: `native-v2.0.0`. This is the Rust application and matching capture
helper for one Nanoleaf NL82K1/NL82K2 USB strip on KDE Plasma 6 Wayland.

## What changes

- A native Rust tray and Settings replace the Python/PyQt6 runtime, bridge and
  privileged C capture helper. Guided strip setup walks through connection,
  corner mapping, colour checks and an explicit finish/start choice.
- Settings separates Mirroring, Strip setup, Colour calibration and Advanced.
  Save / Apply keeps the window open, and Reload saved discards unsaved edits.
- KWin ScreenShot2 remains automatic capture. Explicit portal/PipeWire/Vulkan
  capture uses a supervised helper and the validated KDE SDR colour contract.
- Calibrated processing retains neutral/black handling and linear-light temporal
  transitions. **Use fast response** offers prompt transitions without replacing
  saved mapping, profiles or capture selection.
- Serial USB output remains acknowledged. Qualified NL82K2 firmware 1.5/hardware
  1.1 with manual 48 zones can shorten a trailing portion only when its encoded
  bytes exactly match the last acknowledged output. Dithered changes are sent;
  other identities retain full frames.
- Stop keeps the tray running. Previews own output exclusively. Portal revocation,
  lock/sleep notifications and session-monitor loss stop the old session and
  require explicit Start after recovery.
- Bundles install the app/helper pair together, preserve prior native versions and
  support checksum-verified rollback. Calibration and unknown configuration fields
  remain compatible.

The Python/PyQt6 application, its historical packaging and privileged DRM capture
are retired. Native PyPI distribution uses a pure-Python installer wheel with
no bundled ELF binaries: explicit installation downloads and verifies the pinned
Rust pair, then later commands execute the native app. A native AUR binary recipe
is provided. Registry publishing requires
separate maintainer setup and verification. No firmware
upgrade, loader or recovery feature is included.

## Install or upgrade

Follow [native installation and setup](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.0.0/docs/NATIVE_INSTALL.md). A published release
provides [native.tar.gz](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/releases/download/native-v2.0.0/native.tar.gz)
and its [checksum](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/releases/download/native-v2.0.0/native.tar.gz.sha256); verify the checksum, extract,
then run `./native/bin/nanoleaf-native --install-native` as your normal user.
Quit an existing tray before upgrading. Installation does not start mirroring or
enable login startup. Launch **Nanoleaf Screen Mirror (Rust)** afterward.

PyPI `nanoleaf-kde-sync 1.9.3` and GitHub `v1.9.3` remain historical Python
distributions. Native PyPI 2.0.0 and AUR `nanoleaf-kde-sync-bin` are additional
channels; see [distribution and availability](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.0.0/docs/PACKAGING_AUR.md).
Use the GitHub native archive for a direct installation.

Existing users retain `~/.config/nanoleaf-kde-sync/config.toml`, calibration
profiles and private save backups. Remove obsolete Python autostart entries and
keep only one output owner. Native binary rollback restores the app/helper pair;
it does not restore earlier settings.

## Verification boundaries

The source includes Rust colour/protocol contracts, generated historical replays,
transport faults, worker recovery, session monitoring and isolated packaging tests.
A release build must pass the repository's current validation gates; documentation
alone does not certify those results for a newly tagged commit.

Real NL82K2 output, physical USB reconnect, portal permission revocation and worker
recovery were exercised in the retained evidence. Human colour observations are
not colourimeter measurements. NL82K1 physical output, physical suspend/resume,
optical latency, power and long-duration soak behaviour remain unverified. SDR
capture on an HDR desktop is not raw HDR. USB ACK timing is not emitted-light
latency, and Target FPS is not a promise of delivered updates.

Evidence and implementation details:

- [Native completion](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.0.0/docs/RUST_NATIVE_COMPLETION.md)
- [Colour refinement](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.0.0/docs/COLOUR_REFINEMENT.md) and [response work](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.0.0/docs/RESPONSE_LATENCY.md)
- [Streaming colour contract](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.0.0/docs/RUST_STREAM_VULKAN.md)
- [Short USB updates](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.0.0/docs/SHORT_UPDATES.md) and [ACK path experiments](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.0.0/docs/USB_ACK_PATH_EXPERIMENTS.md)
- [Stop during USB](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.0.0/docs/STOP_DURING_USB.md) and [session recovery](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.0.0/docs/SESSION_RECOVERY.md)
- [Gameplay profiling](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.0.0/docs/GAMEPLAY_PROFILING.md)
