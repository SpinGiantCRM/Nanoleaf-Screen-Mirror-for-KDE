# Native installation and daily use

The Rust application includes Settings, a tray, HID transport and a supervised
capture helper. It supports one NL82K1/NL82K2 USB strip and one selected monitor
on KDE Plasma 6 Wayland. The native bundle has no Python or Qt runtime dependency.
A PyPI install uses Python only for a standard-library installer and launcher for
the installed Rust binary. Its wheel contains no ELF binaries. Calibration and
the existing configuration path remain compatible.

## Requirements

Use a Linux x86_64 system with KDE Plasma Wayland, PipeWire, Wayland/GL system
libraries, and the Vulkan loader with a compatible graphics driver for streaming.
Release/CI binaries use the Ubuntu 24.04 build baseline and require
glibc 2.39 or newer with compatible system libraries.
The application needs normal user access to the strip's HID device; it requires
no privileged DRM helper, capabilities or root execution.

For a source build, install Rust 1.95.0, a C toolchain, pkg-config, PipeWire
development files, Wayland/GL development files, the Vulkan loader/driver and
Python 3 for build-time dependency notices. On Arch/CachyOS these are supplied
by rustup, base-devel, pkgconf, pipewire, wayland, libglvnd and
vulkan-icd-loader, plus the matching graphics driver.

## Download and install

From a [native 2.0.0 release](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/releases/tag/native-v2.0.0),
download `native.tar.gz` and `native.tar.gz.sha256`.
PyPI `nanoleaf-kde-sync` **1.x** and GitHub `v1.9.3` retain the old Python application;
see the repository’s [migration guide](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/main/docs/LEGACY_PYTHON.md)
if you installed one of those versions. Use a fresh directory and
verify the archive before extracting:

```bash
sha256sum -c native.tar.gz.sha256
tar -xzf native.tar.gz
./native/bin/nanoleaf-native --version
./native/bin/nanoleaf-native --install-native
```

Native PyPI and AUR routes are described in the repository’s
[distribution guide](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/main/docs/PACKAGING_AUR.md).
For native PyPI 2.0.0, once published:

```bash
pipx install nanoleaf-kde-sync==2.0.0
~/.local/bin/nanoleaf-kde-sync --install-native
~/.local/bin/nanoleaf-native --version
```

The wheel is a pure-Python installer. Only explicit `--install-native` downloads
the pinned GitHub native archive and checksum, verifies the embedded release
SHA-256, archive paths and manifest, then installs the native pair and KDE
launcher. Installing the Python package, viewing help/version or invoking the
wrapper without an action does not download the app. The native runtime still
requires Linux x86_64 and glibc 2.39 or newer. The pipx wrapper
remains `nanoleaf-kde-sync`; the managed native command is `nanoleaf-native`.
Quit before upgrading pipx and rerun its `--install-native` afterward. Use the
installed native command for the app version. A fresh wrapper identifies the
installer; after installation it delegates to the native app. To remove both layers, run native `--uninstall-native` first, then
`pipx uninstall nanoleaf-kde-sync`. Your configuration and retained versions stay
available.

The AUR binary recipe is `nanoleaf-kde-sync-bin`. A system package owns its files
under `/usr` and is upgraded/removed with Pacman/AUR tooling, rather than the
user-prefix native installer. Registry availability is separate from this source
tree. Use the checked-out recipe until its AUR publication is confirmed.

For a test build, open a passing **Native Rust bundle** run for the desired
commit in GitHub Actions and download **nanoleaf-native-linux-x86_64**. Unzip the
artifact, extract its `native.tar.gz`, and run the installer above. CI artifacts
are test builds; CI does not verify physical output.

From a source checkout:

```bash
bash scripts/build_native_bundle.sh dist/native
./dist/native/bin/nanoleaf-native --install-native
```

The builder refuses to overwrite an existing destination. For another build,
choose a fresh bundle directory and install from that directory's `bin/`.

The default installation prefix is `~/.local`. Supply an absolute prefix after
`--install-native` to use another location; use that same prefix for subsequent
upgrade, rollback and uninstall commands. Both binaries install together with
a checksum manifest and dependency notices. Immutable versions remain under
`PREFIX/lib/nanoleaf-native/`, and `PREFIX/bin/nanoleaf-native` selects the current
version. KDE's launcher points to the installed binary and declares the normal
ScreenShot2 permission. Installation refreshes KDE's application cache.

Installation does not start mirroring, request capture permission, install USB
rules, enable login startup or change calibration. Open **Nanoleaf Screen Mirror
(Rust)** from KDE's application launcher. If `~/.local/bin` is not on your PATH,
use the full command path shown below.

## First launch and strip setup

First launch creates a stopped, unconfigured settings file only if none exists.
An existing file is loaded without replacement. From the tray, open
**Settings and calibration**:

An incomplete configuration opens **Strip setup** automatically. The guided
steps save progress while keeping your existing calibration:

1. **Connect your strip** — choose **Strip model**, enter the actual
   **Manual zone count** (4–512), and select the screen. **Check USB connection**
   enumerates the selected model without writing lights; output access is checked
   when you test a colour. Choose **Save count & continue** before testing zones.
2. **Locate the corners** — adjust **Preview zone**, choose **Locate zone**, then
   use the matching **Use zone** button or enter the index for **Top left**,
   **Top right**, **Bottom right** and **Bottom left**. Numbering starts at zero;
   all four corners must be distinct and inside the saved manual count. The
   diagram shows your current mapping. Choose **Save corners & continue**.
3. **Check the colours** — use **Red**, **Green**, **Blue**, **Grey** and **Black**.
   Grey should look neutral and black should turn the strip off. Adjust
   **Strip channel order** or **Reverse strip order** if necessary. Choose
   **Save / Apply** before testing changed settings, then
   **Save colour settings & continue**.
4. **Ready to mirror** — review the saved model, count, screen and corner indices.
   **Finish setup** saves and returns to Mirroring. **Save & start mirroring**
   saves and begins capture/output.

Manual zone count remains authoritative. Device-reported counts are diagnostic
only. A saved unavailable screen is retried without switching monitors. Previews
pause normal mirroring and clear after ten seconds; **Stop mirroring** clears a
test immediately. Choose Start to resume ordinary output.

The sidebar separates **Mirroring**, **Strip setup**, **Colour calibration** and
**Advanced**. The footer's **Save / Apply** validates/saves the draft and reloads
the service while keeping Settings open. **Reload saved** discards unsaved edits.
If the service is absent, open the app from KDE's launcher: a Settings window
alone does not create the tray. Closing Settings leaves an existing tray running.

Settings stay at `~/.config/nanoleaf-kde-sync/config.toml`, or under
`$XDG_CONFIG_HOME/nanoleaf-kde-sync/` when set. Saves retain private
`config.toml.native-backup-*` files beside the configuration. Both calibration
profiles and unknown fields are retained. Keep a separate known-good copy before
making substantial calibration changes.

## Daily controls

**Start mirroring** acquires capture and output. **Stop mirroring** stops the
session and keeps the tray available. **Quit** exits and releases the controller.
Only one application may own the strip; quit any other Nanoleaf output software
before starting.

**Mirroring** contains brightness, Target FPS, colour style and response speed.
For prompt transitions, **Use fast response** followed by **Save / Apply** disables
additional temporal averaging and selects full response. Small variations may
become more visible. **reference** style or **Accuracy mode** bypasses prediction
and appearance policies while retaining calibration.

**Colour calibration** contains measured profile import/export and calibration
controls. **Advanced** contains capture selection, detailed software timings and
login startup. Target FPS is a
capture/output target; the serial acknowledged controller can deliver fewer
updates. An ACK confirms a USB transaction, not emitted-light timing.

To control an already running tray from a terminal:

```bash
~/.local/bin/nanoleaf-native --status
~/.local/bin/nanoleaf-native --stop
~/.local/bin/nanoleaf-native --start
```

## Capture, colour and session recovery

**Automatic** uses KWin ScreenShot2. To explicitly select streaming, choose
**Portal / Vulkan** under Advanced → Capture, save, and allow the
configured monitor in KDE's picker. The validated path is KWin 6.7/6.8 with the
matching PipeWire/Vulkan worker. Your selected backend remains authoritative.
Revoking sharing stops output and requires an explicit Start to request capture
again.

Captured pixels are SDR display-referred sRGB, including on an HDR desktop, so the
SDR LED profile applies. The HDR profile is retained. Unsupported raw HDR/PQ/HLG/
FP16 and native privileged DRM capture fail explicitly. Do not enable capabilities
or a retired capture helper to work around this boundary.

The app stops its session when KDE reports a lock, logind reports a sleep/resume
transition, or session monitoring becomes unavailable. Unlock, resume or monitor
recovery leaves the tray stopped; choose Start. Pre-suspend cleanup is best
effort, and physical suspend/resume remains unverified. See the source repository's
`docs/SESSION_RECOVERY.md` for the evidence and limits.

## Troubleshooting

| Symptom | Next step |
| --- | --- |
| No tray or Settings says the service is not running | Open **Nanoleaf Screen Mirror (Rust)** from KDE's launcher. Check KDE's hidden tray icons. |
| Start reports incomplete strip setup | Save the manual count and four distinct corner indices within that count. |
| The strip is detected but output reports permission denied | Check the supplied narrow `60-nanoleaf-kde-sync.rules` for an administrator to install. Run the app as your normal user. |
| No device is detected | Check the USB connection, chosen model and that another output application is closed. |
| The saved screen is unavailable | Reconnect it or explicitly choose an available screen and save. |
| Output stopped after lock, sleep or Stop sharing | Restore the desktop/session services, then choose Start; accept the portal picker if requested. |
| Colours are reversed or channels differ | Use saved channel-order/reverse settings and the setup previews. Check neutral grey and black before adjusting calibration. |
| Transitions feel delayed | Try **Use fast response**, then Save / Apply. Review software stage timings in Advanced. |
| Installer refuses an upgrade | Quit the tray first. Preserve externally changed launchers/commands; obtain a clean bundle for checksum errors. |

Read-only readiness and device detection:

```bash
~/.local/bin/nanoleaf-native --doctor
```

Doctor reports configuration readiness, Wayland availability, helper presence
and enumerated USB devices. It does not write LED output or prove USB access,
colour accuracy or optical latency. For support, include the app version,
selected backend, manual count and relevant error text; review any diagnostics
for private paths before sharing.

## Acknowledged USB updates

On the tested NL82K2, firmware 1.5/hardware 1.1 with manual 48 zones, a trailing
portion can be omitted only when its actual encoded bytes exactly match the last
acknowledged output. Dithered changes still require transmission. Every update
sends a nonempty prefix and waits for its ACK. Initial/reconnected
output, previews, cleanup and periodic refresh use full frames. Other identities,
manual counts or failed identity queries retain the full-frame path. The manual
zone count never changes automatically.

Advanced shows payload size and shortened-update count. To
force full frames, Quit the tray, then run:

```bash
NANOLEAF_SHORT_UPDATES=0 ~/.local/bin/nanoleaf-native --run
```

This changes no saved configuration. Source evidence is in
`docs/SHORT_UPDATES.md`; USB timing is not optical latency.

## Upgrade and rollback

The following commands apply to a user-prefix native installation, including
one installed through the pipx wrapper. Use Pacman/AUR tooling for system-owned
packages. Quit the tray before maintenance; Stop alone keeps the service running. Install
from the newly extracted bundle using the same prefix. The app and matching
capture helper upgrade together, while previous versions and configuration remain
available. Start the application again from KDE's launcher after installation.

To switch to the previous installed native pair:

```bash
~/.local/bin/nanoleaf-native --rollback-native
```

Rollback swaps current and previous versions and requires a previous installation.
It does not restore earlier settings. To restore settings, Quit first, preserve
the current file, copy your chosen known-good backup to `config.toml`, then
relaunch. Do not edit configuration while Settings has unsaved changes.

To remove the managed command, launcher and native login startup while retaining
versions and calibration:

```bash
~/.local/bin/nanoleaf-native --uninstall-native
```

Any previous native launcher is restored. The uninstall leaves recoverable
version directories; it is not a full data purge.

## Login startup

In Advanced choose **Launch native tray at login** or
**Disable native login launch**. Terminal equivalents:

```bash
~/.local/bin/nanoleaf-native --autostart on
~/.local/bin/nanoleaf-native --autostart off
```

Login startup launches the tray. **Start mirroring when the tray launches**
separately controls capture/output. Remove obsolete Python startup entries before
enabling mirroring; the native app manages only its own entry.

## Releases and verification limits

Native tags use `native-vX.Y.Z`. A matching version tag starts the release
workflow: it builds and tests the archive, stages a draft release, verifies the
uploaded archive/checksum, then publishes. Failed verification leaves publication
incomplete. Existing
releases and Git history are retained. The Python/PyQt6 application, bridge and historical Python packaging are retired.
Native PyPI/AUR distribution is supported without restoring the old runtime.
Choose the installation channel’s own upgrade/removal commands; the immutable
user installer and the system package manager own different locations.

Real NL82K2 output and physical USB reconnect have been exercised and visually
confirmed. NL82K1 physical output, physical suspend/resume, optical latency,
colourimeter accuracy, power and long-duration soak behaviour remain unverified.
Software tests and CI do not establish those physical results. For 2.0.0 scope
and the source evidence index, see `docs/RELEASE_2_0_0.md` in the repository.
