# Adaptive colour migration checkpoint

2026-10-12, branch `codex/rust-adaptive-palette`, Python reference `920f575`.

## Direction

The user has now requested a **fully Rust service and UI**. This checkpoint is
an independently verified colour-core step toward that replacement, not a claim
that the rewrite is complete. The recovered Python app remains the fallback.
The priority order is colour accuracy, then latency/FPS, then resource usage.
Perceived-FPS/predictive features follow core correctness and refinement.

## Profile and implementation

The initial 12-frame cProfile diagnosis found these cumulative times at 1440p:

| Operation | Time across 12 profiled frames |
| --- | ---: |
| Full-frame initial mean/integral | 488.01 ms |
| Mixed-content detection | 301.60 ms |
| Adaptive palette frame candidates/scores | 489.55 ms |

These include profiler overhead; they establish where work is spent, not a
speedup measurement. The initial sequence used fixed palette state, with green,
white text, a red split and seeded noise. It is distinct from the final evolving
replay. Raw function timings are retained in `python-profile-before.json`.

The Rust core now performs batched mixed-content detection using SDR sRGB decode,
linear luminance standard deviation, saturation, prominence and hue coherence.
For mixed zones it computes the existing dark-biased linear mean, including
median-luminance-dependent weighting. It retains all pixels supplied by the
existing sampling plan. No new resolution/stride/FPS settings are introduced.

After a successful opt-in native prepass, the palette path skips its earlier
full-frame integral mean because every valid palette zone overwrites that result.
Invalid/inverted geometry and native failure retain the reference path. This
removes redundant conversion/cumulative sums; it does not replace adaptive colour
selection with simple averaging. Candidate generation/scoring and temporal
selection remain Python at this checkpoint and are the next full-rewrite targets.

The final paired profile confirms the removed costs. In the 1440p scene sequence,
the Python integral/detection costs were 472.55/335.50 ms across 12 profiled frames;
neither Python operation appears on the successful Rust route. Palette frame
processing remains the largest cost, at 674.35 ms on that profiled Rust route.
The profiling harness also includes untimed fixture generation/hashing in its
outer call tree; performance comparisons use only the explicitly timed frame path.

## Colour preservation and fallback

The core preserves float32 reference arithmetic/reduction ordering for decisions
and channel sums. Contiguous pairwise reduction ordering is adapted from
[NumPy's implementation](https://github.com/numpy/numpy/blob/main/numpy/_core/src/umath/loops_utils.h.src);
the [BSD notice](../native/THIRD_PARTY_NOTICES.md) accompanies the source and
development binary. Decisions near luma/prominence/coherence/median or output
quantization boundaries return a reference status, causing Python to decide and
average that zone. Patches above 1,048,576 pixels also use the reference status to
bound transient feature storage. Neither case disables the sampler.

Malformed native output/call failure logs once and disables the instance, returning
to the full Python path for the same frame. Privacy masking, source clipping and
sampling strides still happen before the prepass. Calibration, matrices/gains,
white balance, smoothing, palette temporal state, quantization, mapping and channel
order remain the same downstream operations. HDR/non-sRGB/non-BT709 and unsupported
modes do not invoke this SDR kernel. Nothing is enabled by normal runtime defaults.

## Performance evidence

Median of three replay medians, 24 evolving frames each, 48 zones. "Full path"
includes frame processing, diagnostics and GRB TLV construction, including copies
and conversion. It excludes capture and USB writes. Default colour modes, palette
history, accumulation and dithering are active. Replays alternate complete path
order and reset the global accumulator between paths. Fixture generation/hashing
and comparison are outside timing. No test/build ran concurrently with the recorded
comparison. The reference uses no native injections.

| Frame | Sequence | Python | Rust prepass | Ratio |
| --- | --- | ---: | ---: | ---: |
| 640×360 | Flashes, scene cuts, neutrals | 25.546 ms | 17.946 ms | 1.4× |
| 640×360 | Mixed, dark, noise | 11.553 ms | 2.381 ms | 4.9× |
| 640×360 | Profile, privacy, letterbox | 17.178 ms | 13.995 ms | 1.2× |
| 2560×1440 | Flashes, scene cuts, neutrals | 128.078 ms | 67.215 ms | 1.9× |
| 2560×1440 | Mixed, dark, noise | 89.515 ms | 25.180 ms | 3.6× |
| 2560×1440 | Profile, privacy, letterbox | 24.429 ms | 18.163 ms | 1.3× |
| 3840×2160 | Flashes, scene cuts, neutrals | 258.044 ms | 128.663 ms | 2.0× |
| 3840×2160 | Mixed, dark, noise | 186.021 ms | 61.424 ms | 3.0× |
| 3840×2160 | Profile, privacy, letterbox | 33.990 ms | 23.533 ms | 1.4× |

All 648 paired frames passed exact sampled RGB, selected-mode, serialized temporal
state and final GRB TLV equality. The prepass ran on 24/24 frames in the first two
sequences and 18/24 in the letterbox sequence; normal area-average mode handles the
other six. Mixed-sequence reference-zone counts per replay were 13, 102 and 160
at the respective sizes, out of 1,152 zone decisions. Other sequences had zero.
Timings are workload-dependent and are not interchangeable with the earlier fixed
box sampler/production fixtures. No whole-app native FPS, power or memory gain is
claimed. Python is still loaded in this checkpoint.

## Verification and preservation

Locally: 14 core Rust tests at Rust 1.77, 45 bridge/adaptive tests under the Rust
1.85 release extension on Python 3.14.7, and all 1,636 Python tests passed with
77.92% coverage. Clippy/format, Ruff, mypy and Bandit passed. The retained Python
production budget gate passes. Hosted CI has not run for this local branch.

The initial full suite exposed an inherited IndexError on deliberately inverted
geometry; the new regression checks that both paths preserve that failure instead
of letting the optimization silently bypass it. Normal config validation remains
unchanged. User calibration/configuration-directory and launcher hashes were
unchanged. No capture permissions, USB reconnect or optical/HDR tests were performed
for this step. The original app/package/capture/HID paths remain available.

Raw evidence and reproduction: [evidence directory](../perf/rust-adaptive-2026-10-12/README.md),
[development bridge](../native/python-bridge/README.md). The full Rust rewrite must
retain these fixtures and replace Python reference fallbacks with accuracy-tested
native handling before becoming the default.
