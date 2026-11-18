# Native 2.1.0

Release tag: `native-v2.1.0`. This release is the Rust application and matching
capture helper for one Nanoleaf NL82K1/NL82K2 USB strip. It supports KDE Plasma 6
Wayland and now also Hyprland 0.57.

## What changes

- **Hyprland support.** Portal/PipeWire/Vulkan capture detects the running
  compositor. KWin 6.7/6.8 keeps its original validated contract, version gate and
  error text. Hyprland 0.57 with xdg-desktop-portal-hyprland 1.5 gets its own
  contract, live-probed on an NVIDIA HDR desktop:
  - Capture is untagged 8-bit BGRA, which xdph returns as bit-exact SDR sRGB even
    when the output runs HDR.
  - Synchronisation is implicit only.
  - The shared monitor is matched by its connector name (`mapping_id`).

  Other compositors and other Hyprland releases are refused rather than guessed.
- **Choosing capture on Hyprland.** KWin ScreenShot2 exists only on Plasma, so
  on Hyprland set **Capture** to **Portal / Vulkan** in Settings → Advanced.
  Ticking **Remember this choice** in the screen-sharing picker lets later starts
  skip it.
- **Remembered screen-sharing permission.** The permission is stored per desktop,
  so alternating Plasma and Hyprland logins keep their own.
- **Lock detection.** If the screen-saver service has no lock state (as with
  Noctalia on Hyprland), lock state comes from logind's `LockedHint`. If the
  service itself is missing, the app still fails closed.
- **Start at login.** A Start requested at login that was refused only because
  the desktop session was not ready yet is retried once when it becomes ready.
  Stop, a successful start or a later lock/sleep cancels the retry. Unlock and
  resume still never start mirroring on their own.
- `NANOLEAF_CAPTURE_FPS=1..240` can lower the frame rate requested from the
  screen-cast portal for experiments. By default the request still follows
  Target FPS.

Behaviour on KDE Plasma is otherwise unchanged. Configuration, calibration and
unknown fields remain compatible with 2.0.0.

## Install or upgrade

Follow [native installation and setup](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.1.0/docs/NATIVE_INSTALL.md).
The release provides
[native.tar.gz](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/releases/download/native-v2.1.0/native.tar.gz)
and its [checksum](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/releases/download/native-v2.1.0/native.tar.gz.sha256).
To install:

1. Quit the running tray.
2. Verify the checksum and extract the archive.
3. Run `./native/bin/nanoleaf-native --install-native` as your normal user.

Previous native versions are kept for rollback.

## Verification boundaries

Hyprland evidence comes from one system: an RTX 4080 SUPER with the NVIDIA 620.70
open driver, a 3840×2160 240 Hz HDR output, Hyprland 0.57.2, xdph 1.5.0 and
PipeWire 1.6.11. It is recorded in
[Hyprland compatibility](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/native-v2.1.0/docs/HYPRLAND_COMPATIBILITY.md).

Verified there:
- Portal probe colour checks were exact.
- The installed daemon mirrored to a real NL82K2.
- Restarts restored the screen-sharing permission silently.
- 240 fps recordings of a blurred live wallpaper dropped the same frames with
  mirroring on and with it off.

Not verified:
- Whether a given lock screen sets logind `LockedHint`.
- HDR-tagged client content (PQ video or games).
- Other GPUs, and Hyprland releases other than 0.57.x.

The fix for the login race was tested in code; its live check is a real login.

The 2.0.0 limits still apply. USB ACK timing is not emitted-light latency,
human colour observation is not colourimeter measurement, and NL82K1 output and
physical suspend/resume remain unverified.
