# User guide

Install the [Rust native bundle](NATIVE_INSTALL.md), then open **Nanoleaf Screen
Mirror (Rust)** in KDE. Settings opens on demand. Select one monitor, set the
manual strip zone count, corner anchors and channel order, and preserve your
measured calibration profiles. Save / Apply applies changes and keeps Settings open.

Start begins mirroring. Stop releases capture and LED output while keeping the
tray running. Quit closes the application. Setup, calibration and manual preview
have exclusive LED ownership; stop other strip applications first.

Automatic capture uses KWin ScreenShot2. Advanced offers explicitly selected
portal/PipeWire/Vulkan streaming on validated KDE versions. Allow the selected
monitor when KDE asks. Stopping sharing ends capture; Start requests it again.
The selected backend is preserved. Raw HDR/PQ/HLG and privileged DRM capture are
unsupported; display-referred SDR capture must not receive a second HDR transform.

For the quickest faithful response, use the existing Target capture/output FPS
setting and inspect Advanced timing diagnostics. Colour smoothing/accumulation
can add deliberate settling time. Reference mode preserves measured colours and
disables appearance-changing prediction policies. Dithering is preserved at the
acknowledged output cadence. Optical delay needs a camera measurement; an ACK is
only a software/controller timing event.

Settings remain in `~/.config/nanoleaf-kde-sync/config.toml`. Calibration, manual
mapping and unknown fields survive native upgrades; saves retain private backups.
Do not delete that directory when removing the retired Python application.
Native bundles retain previous app/helper pairs for rollback. See
[Troubleshooting](TROUBLESHOOTING.md) and [diagnostics](DIAGNOSTICS.md).
