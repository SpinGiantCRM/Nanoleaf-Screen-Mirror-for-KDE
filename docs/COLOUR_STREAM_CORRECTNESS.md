# Colour and streaming correctness follow-up

This implementation follows the [14 October audit](IMPROVEMENT_RESEARCH_2026-10-14.md).
Colour accuracy remains ahead of latency/FPS and resource use. Changes are built
on a dedicated branch; the installed application, Python fallback, saved profiles,
manual count, anchors and autostart are unchanged.

## First independently tested changes

- Correct the descending Oklab Cartesian/polar transition. Chroma compression and
  vivid boosts now affect saturated colours instead of being bypassed. Three new
  tests initially failed on the old code and now pass: strict compression, an
  independent published-coefficient float64 reference, and style/transition checks.
  All 256 neutral codes and black are checked across four styles and three
  compression amounts. This intentionally changes affected profile/style output.
- Parse the portal's `pipewire-serial` as uint64, retain support for older KDE's
  decimal string representation, and never replace the tuple node with `id`.
  Standard string source IDs, uint64 maximum, absent metadata, legacy responses
  and malformed serials are covered without capture permission or hardware output.
- Clarify that capture/active calibration are SDR even on an HDR desktop. Show
  acknowledged packets/s and the software response origin rather than implying
  captured FPS or emitted-light measurements. Explain runtime-clamped profile
  values while preserving the exact saved values.
- Keep the previous arithmetic as `apply_profile_legacy_oracle`, used only by the
  explicitly selected historical pipeline/replay. The service uses corrected
  colour handling. The replay CLI requires an explicit historical parity or
  production comparison mode; CI checks both and retains independent accuracy tests.

Fresh checks at this stage: 64 app tests, 20 core tests and 6 streaming tests pass.
The [production comparison](../perf/colour-stream-correctness-2026-10-14/chroma-production-comparison.json)
contains 18 cases × four frames × three repetitions. All 216 packets and samples
remain exact for that reference/ambient corpus with zero profile compression;
the meaningful compressed/vivid cases are checked independently by the new tests.
Some initial timing runs overlapped another replay; use this artifact for colour
regression evidence, not a controlled speed claim. Capture, USB, power, optical
colour and perceived frame rate were not measured in these runs.

No physical-light or newly supported compositor claim follows from these checks.
Further precision and streaming work is recorded below as it is validated.

## Fractional colour precision

Box sampling now passes its existing linear-light statistics into colour finishing
instead of discarding them through an RGB8 round trip. Accumulation retains those
fractions, and calibration, brightness and dark-neutral processing keep floating
values until the output quantizer. Byte-only artistic samplers remain byte inputs;
this is not a claim that all samplers or capture formats are higher precision.
The historical oracle preserves the earlier reductions and quantization exactly.

`apply_profile_unquantized()` retains calibration fractions. Exactly neutral
calibrated inputs use their analytical neutral result, avoiding numerical matrix
noise making different channels choose different dither phases. Channel-dependent
calibration is not averaged or desaturated. The earlier reference arithmetic
continues in the explicitly named legacy function.

A failing complete-pipeline test originally produced `[120,120,120]` where the
calculated neutral target is approximately 120.186. It now preserves that target
within 0.002 code; the eight acknowledged dither phases approximate it within
0.063 code. Another test retains the fractional mean of alternating 128/129
pixels and requires exact CPU/external-sample agreement. Immediate black-off,
calibration preservation and existing temporal recovery tests still pass.

The [fresh release comparison](../perf/colour-stream-correctness-2026-10-14/precision-production-comparison.json)
has 18 cases and 216 comparisons, with unchanged sampled and final byte packets
for this default-profile corpus. It is a processing benchmark, not a claim of
physical colour improvement or capture/USB latency. 4K reference medians range
2.040–2.852 ms, and ambient medians 3.185–4.916 ms across its three sequences.
No fixed speedup is claimed against earlier unmatched windows.

[Historical replay](../perf/colour-stream-correctness-2026-10-14/precision-historical.json)
checks 72 evolving frame comparisons in the small deterministic corpus.
[Synthetic Vulkan validation](../perf/colour-stream-correctness-2026-10-14/precision-texture-oracle.json)
on the RTX 4080 SUPER passes 40 zone, 40 region and 40 changed-zone comparisons,
with exact statistics/pixels. It does not exercise DMA-BUF import, desktop capture,
USB or emitted light. Native gates at this precision checkpoint pass: 66 app
tests, 21 core tests; Clippy passes on the pinned toolchains.
