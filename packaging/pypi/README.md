# Nanoleaf Screen Mirror for KDE — native Rust application

Mirror one screen's edge colours to one Nanoleaf NL82K1/NL82K2 USB strip on KDE
Plasma 6 Wayland. Version 2.0.0 is a **Python installer for the native Rust
application and matching capture helper**. The wheel contains no native
executables. Its standard-library installer downloads the version-pinned native
release only when explicitly requested, then later commands execute the
installed Rust app. There is no Python GUI, capture, colour or USB runtime.

## Install

Use Linux x86_64, Python 3.11 or newer and pipx:

```bash
pipx install nanoleaf-kde-sync==2.0.0
~/.local/bin/nanoleaf-kde-sync --install-native
~/.local/bin/nanoleaf-native --version
```

The explicit `--install-native` step downloads the native-v2.0.0 GitHub archive
and checksum. It verifies the archive against the SHA-256 embedded when this
installer wheel was built, validates archive paths and the internal manifest,
then installs the native pair into immutable versions under `~/.local`. It
creates the `nanoleaf-native` command and installs the
KDE application launcher. Open **Nanoleaf Screen Mirror (Rust)** from KDE.
Installation preserves configuration and calibration and does not start
mirroring or enable login startup. To use a custom location, append an absolute
prefix to `--install-native`; the wrapper remembers the installed command path
for later invocations.

The wheel is genuinely pure Python (`py3-none-any`); the downloaded application
requires **Linux x86_64 with glibc 2.39 or newer**, using the Ubuntu 24.04 build
baseline. Use KDE Plasma Wayland with PipeWire, Wayland/GL libraries and the Vulkan
loader/driver for streaming. Normal HID user permissions are required. No Qt
runtime or privileged DRM helper is used. Installing the pipx package, running
help/version or invoking the wrapper without an action does not download the
native app. Install it explicitly before using mirroring commands.

If this exact version has not been published, pipx cannot install it from the
registry. The [GitHub native release](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/releases/tag/native-v2.0.0)
and its checksum-verified archive provide the direct installation route.

## Set up and use

Open **Settings and calibration** from the tray. Guided **Strip setup** walks
through connection, the authoritative manual zone count, four corner anchors,
colour order and an explicit finish/start choice. Save / Apply keeps Settings
open; Reload saved discards unsaved edits. Stop pauses mirroring while leaving
the tray running. Keep other strip-control applications closed.

See the [installation and onboarding guide](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/main/docs/NATIVE_INSTALL.md)
for setup, USB permissions, capture selection, calibration and troubleshooting.

## Upgrade, rollback and removal

Quit the tray before upgrading the pipx package or installing another native
version. Once native 2.0.0 is available, existing pipx users can run
`pipx upgrade nanoleaf-kde-sync`. After a pipx upgrade, run
`~/.local/bin/nanoleaf-kde-sync --install-native` again to download and install the new pinned native
pair and refresh the desktop launcher. Check the installed app using
`~/.local/bin/nanoleaf-native --version`. Before native installation, the wrapper
identifies its installer release; afterward it delegates to the native app. The previous native pair remains
available through `~/.local/bin/nanoleaf-native --rollback-native`.
Rollback changes binaries; it does not restore earlier settings.

For removal, Quit first, then remove both managed layers:

```bash
~/.local/bin/nanoleaf-native --uninstall-native
pipx uninstall nanoleaf-kde-sync
```

The first command removes the native launcher, command and native login startup;
the second removes the pipx wrapper and its wheel. Calibration and recoverable
immutable native versions are retained. Removing pipx alone leaves the installed
native desktop application available.

## Existing Python installations

Version 1.9.3 and earlier contain the retired Python/PyQt6 application. Quit that
app and disable its login startup before upgrading to 2.0.0. Keep
`~/.config/nanoleaf-kde-sync/`: native releases preserve the shared configuration,
manual mapping, calibration profiles and unknown fields. See
[migration guidance](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/main/docs/LEGACY_PYTHON.md).

Real NL82K2 output and USB reconnect have been exercised. Physical NL82K1 output,
suspend/resume, optical latency and colourimeter accuracy remain unverified.
Software timings and USB acknowledgements do not measure emitted light.

[Source and issues](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE)
· [Release notes](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.0.0/docs/RELEASE_2_0_0.md)
· [Licence](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/main/LICENSE)
