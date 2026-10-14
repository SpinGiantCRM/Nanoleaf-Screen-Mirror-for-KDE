# Colour refinement: linear mixing and elapsed-time response

Implementation checkpoints: `534fd37` and `1ba4043`. This continues PR #367's precision and
chroma fixes. Colour accuracy remains the first priority, followed by response
and resource usage. The installed application, saved configuration, SDR/HDR
profiles, manual mapping and Python fallback are unchanged.

## Corrections

Final smoothing and optional neighbour spread previously mixed encoded values.
The modern path now decodes calibrated sRGB, mixes linear channel intensities
and encodes the result without integer rounding. Reference/natural mode continues
to bypass neighbour spread. The original hysteresis/scene thresholds remain;
the historical methods are retained for the offline Python oracle.

This follows the distinction between linear-light compositing and encoded RGB
mixing in [W3C CSS Color 4's interpolation discussion](https://www.w3.org/TR/css-color-4/#interpolation-space).
Our independent double-precision tests use the published sRGB transfer equations,
not the production helper functions. They check a half-step, weighted neighbours,
every neutral code, fractional static chromatic colours and partitioned time
intervals. The old polar interpolation/rounding remains in the historical oracle;
modern filtering preserves the energy of the channel mixture instead.

Device gamma compensation now runs after brightness, mixing and final dark
guardrails. Temporal history stays in the pre-compensation domain. This avoids
decoding gamma-compensated device codes as though they were source sRGB. Tests
verify final compensation for gamma 1.0, 1.5, 2.2 and 4.0 across neutral,
chromatic, white and black transitions. The profile's gains, matrix, white balance,
compression and stored values remain supported. Existing runtime clamps are
unchanged; a saved value outside the supported range still displays its effective
value in the UI. No claim is made that the strip's physical transfer function has
been measured or that this compensation model is a complete hardware model.

A reproduced black-off failure is fixed: with dithering disabled, the integer
ACK hold could retain code 1 after a true black source. True black and calibrated-zero output now bypass
that hold and send zero. Full responsiveness also bypasses tiny-change smoothing
caps; it no longer silently filters fractional changes despite a coefficient of
1.0. Neither correction alters the offline historical oracle.

## Time handling

Accumulation and final smoothing use the exponential coefficient
`1 - (1 - alpha_60hz)^(elapsed_seconds * 60)`. Offline inputs without timestamps
use the configured capture period. KWin uses elapsed capture-delivery time.
Uninterrupted fresh portal frames use source PTS differences. Across cached-source
work, delivery/work intervals prevent double-counting time or delaying new frames
behind the cached clock. Invalid, duplicate or backward PTS falls back to work time. Source
invalidation recreates temporal state. ACKs and predictions do not advance this
processing clock; acknowledged packets still determine physical dither phases.

Independent tests verify the coefficient, split intervals, a low-motion 128→129
accumulation at 60/30 updates per second, zero elapsed time and immediate black.
This establishes the time constants of these exponential components, not complete
cadence invariance of the adaptive application. Scene/hysteresis decisions,
palette dwell and optional analyses still have discrete state; their response
needs labelled sequences and live video/game measurements before further tuning.

## Measurements and verification

See [the bounded evidence directory](../perf/colour-refinement-2026-10-14/).

- Native tests: 71 application, 26 core, nine streaming; the unchanged GPU layout
  contract remains part of the prior gate. Rust format and Clippy checks pass.
- Historical complete-path comparison: 72 generated frames, exact sampled values
  and exact final packets against the retained Python implementation.
- Paired new/previous production replays: 640×360 and 3840×2160, reference/ambient,
  gamma 1.0/2.2, 12 frames, six alternating-order pairs per case. All 576 sampled
  frame comparisons are exact. Output differences are intentional transition and
  compensation corrections, not a parity claim with incorrect old arithmetic.
- In these cases, median colour-stage times fell from roughly 0.019–0.022 ms to
  0.014–0.020 ms. At 4K, complete-path medians were roughly 1.00–2.07 ms and were
  mixed within the observed short-run variability. No material whole-application
  speedup, power saving or capture-to-light reduction is claimed. Frame I/O,
  capture, USB and UI are outside those kernel timings. The source is generated
  and the benchmark disables accumulation to isolate the changed final stage.
- A capture-only test on real KDE Wayland completed 393 exact CPU/Vulkan
  full-pipeline comparisons, with no errors or coalesced prepared frames. Source
  clocks are identical for the GPU and CPU shadow pipelines. This saves no screen
  pixels and sends no USB output; the parity run is not a performance comparison.
- The complete GUI/helper package passes isolated relocation, install/upgrade,
  rollback, autostart, live stopped-service exclusion and uninstall preservation.

The only performance shortcut skips hue conversions when existing eligibility
conditions already rule out the oscillation test. Historical fixtures still match
exactly. No reduced pixel sampling, LUT approximation or global desaturation was
introduced for speed.

## Remaining physical gate

The new colour outputs need observation on the strip before adoption: neutral
grey/white ramps, dim chromatic patches, black cuts and transitions. A bounded
test package is ready; no new version is installed or enabled at login. The user's
earlier physical confirmation applies to the preceding build, not automatically
to these corrections.

Further changes to dim-colour guardrails, calibration/gamma, gamut mapping and
temporal thresholds should use measured strip/wall response. Raw HDR capture,
emitted-light timing and power remain separate open measurements. Prediction is
still guarded and opt-in; cached-source work never enters prediction history.
