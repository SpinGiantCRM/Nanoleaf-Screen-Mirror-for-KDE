# KWin 6.8 compatibility — 2026-10-16

See [source review and verification limits](../../docs/KWIN_6_8_COMPATIBILITY.md).

The running host reports KWin6.8.0/Qt6.12.0 on Wayland. The previous6.7-only
selected-stream guard rejected it before capture. The initial failed lifecycle
attempt remains a failure; independent controller readback matched the original.

`source-review.json` pins upstream files/URLs, without redistributing their code.
The render-target header and implementation are byte-identical between6.7.5
and6.8.0. Both use the same sRGB-labelled BT709/gamma22 SDR target.6.8 PTS is
scheduled software-vblank metadata, not the prior last-presentation marker.

`parity.json` records independent live capture-only exact comparisons for both
modes. No screen images/optical timings. Lifecycle results separate actual
capture from the synthetic worker/real-HID repeat fixture. Package checks use
isolated directories. Configuration/calibration and fallbacks are preserved.

`installed-default.json` records the final app/helper pair installed together,
an eight-second default-policy live smoke, independent controller readback and
thirteen-path preservation check. Only managed native command/desktop changed.
Previous native/Python versions remain; no autostart was enabled and the app was
left closed. Repeat suppression and other experimental flags remain OFF.
