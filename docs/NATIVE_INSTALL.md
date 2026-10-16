# Native Nanoleaf Screen Mirror

This Rust application includes its GUI, tray, HID transport and supervised Vulkan
capture worker. Python and Qt are not runtime dependencies. The existing Python
application remains available with `pipx install nanoleaf-kde-sync`; do not run
both applications against the strip at once.

## Build and install

Main-branch pushes and pull requests that change native code or packaging build a Linux x86_64 bundle
in GitHub Actions. Open the **Native Rust bundle** run for the commit you want,
download the **nanoleaf-native-linux-x86_64** artifact, unzip it, then extract
`native.tar.gz`. Install with `./native/bin/nanoleaf-native --install-native`.
These are test builds, not replacements for the published Python release.
The Ubuntu-built binaries require compatible system libraries and a working
KDE Wayland session; CI does not verify physical LED output.

On KDE Plasma Wayland, build with Rust 1.95.0, Python 3 for build-time notice
generation only, a C toolchain, pkg-config,
PipeWire development files, the Wayland/GL libraries and Vulkan loader/driver.
On Arch/CachyOS these are provided by rustup, base-devel, pkgconf, pipewire,
wayland, libglvnd and vulkan-icd-loader plus the matching graphics driver.

```
bash scripts/build_native_bundle.sh
# Extract the archive on the target machine, then:
./native/bin/nanoleaf-native --install-native
```

The default prefix is `~/.local`; an absolute prefix can be supplied as the next
argument. Both binaries install together, with a checksum manifest and the available
published dependency licence/notice inventory. Versions
remain in `PREFIX/lib/nanoleaf-native/`. The command is
`PREFIX/bin/nanoleaf-native`; KDE's launcher points at the actual installed binary
and declares the normal ScreenShot2 permission. Installation refreshes KDE's
application cache. It does not start mirroring, request capture, grant
capabilities, enable login startup, install USB rules, or change calibration.
Use the KDE application launcher to start **Nanoleaf Screen Mirror (Rust)**.

Run `nanoleaf-native --doctor` for read-only readiness and device detection.
First launch creates a stopped, unconfigured settings file only if none exists.
Open Settings for the manual zone count, monitor, four corner anchors and
channel order. Save / Apply keeps the window open and backs up existing settings.
The file remains `~/.config/nanoleaf-kde-sync/config.toml` (or XDG_CONFIG_HOME).
Both calibration profiles and unknown legacy settings are preserved.

USB access normally uses the existing Nanoleaf udev rules. If the doctor detects
the strip but output reports permission denied, the supplied
`60-nanoleaf-kde-sync.rules` is the existing narrow NL82K1/NL82K2 rule for an
administrator to install. This native app needs no DRM capabilities or root.

## Capture and colour

KWin SDR display-referred capture remains the automatic backend. On the
validated KWin 6.7/6.8 paths, select `xdg-portal` in Advanced for the streaming Vulkan
backend and allow the configured monitor in KDE's picker. Permission revocation
stops mirroring and requires an explicit Start. Pixel-dependent colour policies
use the CPU pixel path; reference box sampling uses exact GPU histograms.
Unverified colour formats fail explicitly. Raw HDR/PQ/FP16 and native privileged
DRM capture are not supported; retain the Python fallback for those paths.

Reference/accuracy mode disables prediction and appearance-changing analyses.
Temporal accumulation now blends in linear light to preserve transition energy.
Black source zones now bypass accumulation and smoothing so a cut to black
immediately emits off. The old Python transition glow remains only in the
fallback and its retained regression oracle. Optional multi-moment sampling uses
actual dominant-bin pixels, rather than invented bin-centre colours. Wavelet
sampling is now a bounded linear-light detail-weighted mean. Scene adaptation
only improves temporal response; it does not change calibration, colour style or
FPS. Legacy virtual oversampling selects full pixel coverage without changing
physical mapping or bypassing privacy masks.
4D is an opt-in conservative cadence polish, capped at one extra packet and one
encoded colour code per observed frame. It is disabled with temporal dithering.
Inferred packets are counted separately; they do not increase capture FPS or
constitute measured optical frame generation.

## Upgrade, rollback and login startup

Quit the native tray before installing another bundle. Repeat `--install-native`
from the new extracted bundle, with the same prefix. An externally edited
launcher/command or a failed checksum causes a refusal. Previous binaries remain
available. To switch back:

```
~/.local/bin/nanoleaf-native --rollback-native
```

To remove the native command/launcher while retaining recoverable versions, use
`nanoleaf-native --uninstall-native` with the same prefix. Any previous native
launcher is restored.

Rollback swaps the previous and current versions; it never rolls configuration
back or edits the Python package. For the Python fallback, Stop and Quit the
native tray, then launch `nanoleaf-kde-sync` through its original launcher.

Login startup is separate and opt-in:

```
nanoleaf-native --autostart on
nanoleaf-native --autostart off
```

Only the native autostart entry is managed. It starts the tray; the existing
**Start mirroring when the tray launches** setting determines whether mirroring
starts. Leave the Python autostart disabled when enabling native mirroring.

## Releases and legacy fallback

Rust is the primary application. A published `native-vX.Y.Z` release builds and
attaches the native archive and checksum only when the tag matches the native
application version. Publishing a native release never publishes Python to PyPI.
Existing releases and tags are retained. Python publishing is available only
through the manual **Legacy Python release** workflow, with a separate opt-in
PyPI switch; normal releases do not trigger it.

The [legacy Python reference](LEGACY_PYTHON.md) retains its installation and
recovery instructions. The default PR pipeline checks one Python version as the
compatibility oracle; weekly checks retain the full legacy version matrix.

## Scope and verification limits

One selected monitor and one manually configured USB strip. Native packaging is
an additional local/tested distribution; no PyPI release or hosted native release
has been published. See `RUST_APPLICATION_MIGRATION.md`, `RUST_STREAM_VULKAN.md`
and the prediction/recovery report in the repository for measured evidence.
One real NL82K2 USB unplug/reconnect recovered acknowledged output and was
visually confirmed. Suspend/resume, NL82K1 hardware, optical latency and
colourimeter accuracy remain unverified. Software tests cannot establish those
physical results.
