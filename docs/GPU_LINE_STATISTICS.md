# Faster exact border decisions for non-uniform dark scenes

15 October 2026. Priority: visible response time, faithful colour, FPS, resources.

The [uniform-dark shortcut](USB_AND_BLACK_RESPONSE.md) made uniform black cheap,
but a single differing pixel still forced the original scanline reader towards
a full-frame download. This change removes that cost for many non-uniform scenes
without changing the detector's threshold, scan order, chosen bounds or colour
sampling. The previous application remains as a recoverable installed version.

## Implementation and accuracy contract

The existing four-edge batch handles the ordinary bright-frame case. When an
interior scanline is required, a compute shader sums **integer RGB8 channels**
on the detector's forward/reverse step-eight grid. One batch covers candidate
rows. A separate lazy batch covers candidate columns over the exact top/bottom
range selected by the row search. Columns are invalidated on range changes;
both caches are confined to one dequeued image. Every pixel of each candidate
line participates. Each result is RGB sums and pixel count, 16 bytes.

Maximum line length is 16,384, so each channel total is at most 4,177,920 and
cannot overflow `u32`. RGBA/BGRA byte normalization and alpha-zero black match
the existing sampler. Only supported packed non-sRGB UNORM formats are accepted.
There is no HDR interpretation, thumbnail sampling, privacy or colour transform.

Summing channels and then computing luma is **not** assumed numerically equal to
the original ordered float32 pixel sum. Instead, the CPU bounds the reference
mean using integer sums and the exact float32 coefficients converted to float64.
For nonnegative terms, a conservative `gamma_(n+8)` relative bound uses float32
`EPSILON` (twice unit roundoff), plus an absolute `1e-9` float64 margin. Count is
exact in float32; allowed RGB8 inputs cannot underflow or overflow the reference
arithmetic. The summation-bound basis is [Higham, The Accuracy of Floating Point
Summation](https://nhigham.com/wp-content/uploads/2023/10/high93s.pdf).

A comparison is accepted only when the entire interval is on the same side of
the **existing 4.0 threshold**. Otherwise original RGB bytes and the original
ordered mean are used. Outermost lines also retain their original calculation.
There is no tolerance-based acceptance of a different crop. The detector shares
its existing search between mean callbacks and proven Boolean callbacks. GPU
floating-point luma reduction is avoided: [WGSL floating-point
rules](https://www.w3.org/TR/WGSL/#floating-point-accuracy) need not reproduce the
host's ordered result.

The all-image uniformity proof remains. Geometry, mapping, calibration, final
dithering and serial acknowledged USB are unchanged. Texture acquisition, all
GPU completion waits and foreign release stay inside existing DMA-BUF ownership.
Added buffers persist and are bounded by dimensions. At 4K, output and readback
are 15,360 bytes each plus a 16-byte parameter buffer; both axes read 24,000 bytes
of summaries per frame. Summary bytes are reported separately from RGB bytes.

## Paired generated-frame measurements

RTX 4080 SUPER, NVIDIA 615.78.08, Rust 1.95.0 locked release builds. Baseline is
`0fe14c2`; both binaries use the same generated scenes, GPU sampler and CPU oracle.
Three alternating AB/BA pairs include two warmups and five timed samples per
case/executable. Medians below pool **15 samples each**. Validation is disabled
for timings and enabled separately for correctness. Upload, startup, CPU oracle,
compositor, USB and emitted light are outside the timed analysis window.

| Generated 3840×2160 scene | Previous reader | Integer summaries + exact fallback |
| --- | ---: | ---: |
| Bright full frame | 0.153 ms | 0.220 ms |
| Thin horizontal bars | 0.548 ms | 0.243 ms |
| Cinema bars | 1.377 ms | 0.247 ms |
| Side borders | 6.571 ms | 0.239 ms |
| Uniform black | 0.235 ms | 0.239 ms |
| Single bright pixel in black | 24.547 ms | 0.412 ms |
| Near-threshold bars | 0.559 ms | 0.667 ms |
| Transparent border with hidden RGB | 0.563 ms | 0.264 ms |

Single-pixel RGB readback falls from 25,656,480 bytes to the four-edge 36,000
bytes, plus 24,000 summary bytes, with the same full-image bounds. Side borders
fall from 9,717,120 RGB bytes to 36,000 plus 15,360 summary bytes. These are
GPU/CPU transfers, not USB traffic.

The bright path submits no statistics dispatch but measured 0.067 ms slower in
this short run; it is not advertised as a speedup. Near-threshold bars regress
by about 0.108 ms because a summary may be inconclusive before original readback.
Deliberately threshold-adjacent stripes still cost about 23.5 ms: exact fallback
remains essential. Non-uniform dark noise and sparse speckles take about
0.37/0.38 ms in the expanded corpus; the same executable's old-reader controls
use full readback. Those controls are separate from the historical baseline.

This demonstrates a substantial reduction in the affected analysis stage. It
**does not** establish the same saving in optical response, all desktop content,
whole-system CPU/power or gaming performance. Content-dependent USB reply costs
remain; no ACK wait is bypassed.

## Correctness and recovery

- 1,008 paired bounds comparisons match the ordered CPU detector. Additional
  validation and same-binary controls cover the expanded 28 generated cases.
- 88,120 hardware integer line totals match normalized CPU pixels across RGBA
  and BGRA, odd/singleton geometries, up to 8,192-pixel lines, changing column
  ranges and five patterns including all alpha codes.
- 68,316 hardware threshold decisions match the CPU mean; 19,804 ambiguous results
  require original pixels. There are 136 accepted cached-column checks after
  span changes/reversal. The separate reader oracle checks 1,232 further line
  totals and the existing zone/region/reader outputs.
- Headless tests compare 1,600 deterministic line cases against the ordered
  reference, including 16,384-pixel lines, low light and threshold ambiguity.
  Invalid counts/totals/thresholds and scan-grid indexes are covered. Another 640
  headless cross-crate cases check certificates against the actual production
  pipeline mean, guarding against future coefficient/expression drift.
- All **28 generated complete outputs** using the saved calibration match:
  sampled colours, final colours, unquantized values and modes.
- Real capture-only checks match **572 complete CPU/GPU outputs**: 311 implicit
  and 261 explicit. These checks save no screen images and drive no LEDs.
  Vulkan validation stderr is empty.
- Both streaming modes pass Stop/tray persistence, exclusive single-zone preview,
  restart, terminated-worker stop/reap/recovery and frozen-worker stop/reap/
  recovery. Frozen-worker stop takes 2.019/2.018 seconds. Original controller
  power/brightness restoration is verified, with config and fallback preserved.
  These lifecycle probes do drive bounded test output.
- Local gates pass: **99 app**, **26 core** (Rust 1.77), **13 stream**, **6 interop**
  and **one GPU-layout test**. The existing operator pipe timing benchmark remains
  ignored in ordinary app tests. All-target Clippy with warnings denied and
  formatting pass for the changed crates.
- Relocated package install/upgrade/rollback/uninstall and live-service exclusion
  checks pass in isolated user directories.

The tested pair is installed as version
`18abd20eadafe11b3afd5041826a9af260474897b2ca4d16df3d9054a40be8b6`.
Previous versions remain. The native launcher points to the new version;
configuration/calibration, Python launchers and both autostart settings are
unchanged. Manual count stays 48 and saved implicit portal/Vulkan stays selected.
Installation does not start the previously closed app. No settings migration,
firmware change, privilege, extra FPS knob or priority mode is introduced.

The prior raw-level visual report remains inconclusive; this change makes no
claim about code 0 versus 15 or 16 on the strip. Physical USB reconnect, permission
revocation, suspend, raw HDR and optical metrology were not newly tested here.
Earlier physical confirmations retain their original scope.

## Reproduction

Build `texture-oracle` in release mode with Rust 1.95.0 and locked dependencies
from `native/stream-probe/Cargo.toml`. These use generated textures only:

```sh
NANOLEAF_VULKAN_VALIDATE=1 texture-oracle --line-oracle
NANOLEAF_VULKAN_VALIDATE=1 texture-oracle
texture-oracle --content-benchmark
texture-oracle --content-benchmark --ordered-readback
texture-oracle --content-benchmark --calibration /PATH/TO/config.toml
```

Retain a release `texture-oracle` built at `0fe14c2` before building the candidate,
then alternate their `--content-benchmark` runs. Use a quiet GPU, normal scheduling
and no validation for timings; both executables must pass exact bounds comparisons.
`--ordered-readback` is a same-candidate control for new patterns, not historical
code bytes. GPU oracles are hardware evidence, not hosted headless GPU execution.

Sanitized evidence: [perf/gpu-line-statistics-2026-10-15](../perf/gpu-line-statistics-2026-10-15/README.md).

The local [optical timing target](../tools/latency-pattern.html) and
[recording instructions](../tools/README.md) are prepared for the next measurement.
Browser checks cover countdown, completion and Escape; no real camera recording
or optical result exists yet.
