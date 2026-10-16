# KWin 6.8 streaming compatibility

16 October 2026. During the USB repeat-prototype recovery check, the live desktop
reported **KWin 6.8.0**, Qt 6.12.0 and Wayland. Installed packages were kwin
6.8.0-1.1, qt6-base 6.12.0-3 and plasma-workspace 6.8.0-1.1. Earlier research had
verified a 6.7.5 desktop; that snapshot no longer described the running host.

The existing selected portal/Vulkan backend rejected the compositor at its
6.7-only colour-contract guard before capture started. The failed attempt is
retained as a failure, with independent controller restoration checked. The
selected backend/config were preserved. This was a new live usability blocker,
not a result of the LED timing probe or evidence of a USB fault.

## Source contract review

Pinned upstream 6.7.5 and 6.8.0 were inspected, with file URLs/hashes in
[the evidence](../perf/kwin-6.8-2026-10-16/README.md):

- [Output source](https://github.com/KDE/kwin/blob/v6.8.0/src/plugins/screencast/outputscreencastsource.cpp)
  still requests ARGB8888. Normal capture negotiates the existing supported
  packed 8-bit RGB formats; raw HDR/FP16/YUV is not enabled.
- [Screencast layer](https://github.com/KDE/kwin/blob/v6.8.0/src/plugins/screencast/screencastlayer.cpp)
  still constructs the SDR render target.
- [RenderTarget](https://github.com/KDE/kwin/blob/v6.8.0/src/core/rendertarget.h)
  defaults to the same sRGB-labelled colour description. Its header and source
  are byte-identical across the two inspected tags.
- [Colour description](https://github.com/KDE/kwin/blob/v6.8.0/src/core/colorspace.cpp)
  defines that target with BT709 primaries and gamma22 in both tags. This
  source-level naming detail is retained explicitly; no new transfer decoding
  or display transform was added to the application's established SDR path.

The guard now accepts only the researched 6.7/6.8 stable families (numeric patch
below50, with ordinary downstream suffixes). Missing/malformed/other families
and development/beta version numbers are rejected. Every-frame range/matrix/
transfer/primaries contradictions and unsupported formats still fail. Version
matching alone does not authenticate downstream distro patches or prove the
colour behaviour of every compositor build.

The 6.8 [stream implementation](https://github.com/KDE/kwin/blob/v6.8.0/src/plugins/screencast/screencaststream.cpp)
uses software-vblank scheduling and puts its scheduled capture/vblank timestamp
in PTS, whereas the inspected 6.7 output used last display presentation. PTS must
remain compositor metadata, separate from capture-work and temporal clocks. The
Advanced label is now **Compositor PTS age**, and comments record both meanings.
Do not compare 6.7/6.8 PTS-age numbers as physical latency. No capture default,
permission route, calibration, geometry or USB scheduling is changed by this fix.

## Verification and limits

Separate eight-second capture-only probes on this actual KWin 6.8 desktop checked
**290 implicit + 298 explicit = 588 exact complete-colour CPU/Vulkan outputs**,
with Vulkan validation stderr empty and the real config byte-identical. No images
were saved and these parity probes did not drive the LEDs. The proof concerns
software colour reproduction on captured inputs, not a colorimeter measurement
or new optical verification of the compositor's display output.

Both synchronization modes then exercised live capture, acknowledged USB,
Stop/tray, exclusive preview, restart and killed/frozen-worker recovery with
controller restoration. The repeat experiment flag was enabled, but this changing
desktop produced no eligible skips. This checks compatibility and conservative
bypass, not repeat-suppression speed. A separate synthetic-worker/real-HID fixture
covers the skip branch and is labelled as such.

The operator lifecycle script now retains stdout reports and stderr even when a
probe fails before its first ACK, rather than discarding its restoration result.
Package relocation/install/rollback checks remain separate from live hardware.

The complete tested app/helper pair was installed together using the existing
immutable installer, retaining previous versions and Python fallback. An
eight-second installed default-policy probe completed 403 real ACKs with repeat
suppression off and independently verified controller restoration. Of thirteen
preserved user paths, only the managed native command and desktop launcher
changed. The app was left closed; no autostart was enabled. Exact saved
config/calibration, Target60, selected portal/monitor and autostart are preserved.
Repeat suppression, GPU wait batching, precise cached timing and explicit-sync
experiments remain off for daily use. No new physical lock/unlock, suspend,
USB-unplug, optical timing or user-observed emitted-colour validation is claimed.
