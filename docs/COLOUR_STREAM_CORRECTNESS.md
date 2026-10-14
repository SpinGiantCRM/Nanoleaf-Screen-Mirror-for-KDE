# Colour and streaming correctness follow-up

This implementation follows the [14 October audit](IMPROVEMENT_RESEARCH_2026-10-14.md).
Colour accuracy remains ahead of latency/FPS and resource use. Changes are built
on a dedicated branch; installed native binaries, saved profiles, manual count,
anchors and autostart are unchanged. The Python reference remains available; its
colour arithmetic is unchanged, with the diagnostic recovery fix noted below.

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

## Preserve useful fallback USB errors

The full Python fallback gate exposed two failures caused by a process exiting
while HID error diagnostics inspected `/proc/<pid>/fd`. The secondary
`FileNotFoundError` hid the actual USB-open error. Both the process directory and
per-process inspection now tolerate OS errors. Three deterministic regression
cases cover disappearing processes, inaccessible processes and unavailable proc.
The targeted transport suite passes all 24 tests. No Python colour or USB wire
behaviour changed.

## USB transaction attribution

Native acknowledged frames now expose drain, report-write, first-response wait,
complete-ACK wait and total transaction timings, plus report counts. Only bounded
metadata is retained—no HID payloads or screen pixels. The five transport tests
cover fragmented and unrelated responses, failure handling, exact report lengths
and the new counters. Diagnostic timings do not change framing, retry policy or
the 250 ms ACK timeout. Actual host/firmware delay attribution still needs a live
run; no USB latency reduction is claimed from adding measurement.

## Static streaming source and recovery

The live PipeWire loop can now reprocess the most recent validated source at the
existing target FPS when no new image arrives. This allows accumulation, smoothing
and acknowledged dithering to keep progressing on a static desktop. A reuse
record is protocol version 2, explicitly marked as unchanged-source work, with a
separate monotonic processing timestamp. It is not prediction or a fresh capture.
The parent counts reused packets separately and never feeds them into prediction.
The displayed rate continues to mean acknowledged packets/s.

Only the live, Streaming-state, permission-bound child emits reuse. Pausing,
format changes, discontinuities, corrupt/empty buffers, cancellation and permission
closure invalidate or end it. A frozen/dead child cannot refresh the two-second
parent watchdog through an independent timer. Stop still clears output and keeps
the tray. USB recovery still releases capture before restarting its existing path.
No automatic switch or permission reacquisition follows a portal failure.

Direct sampling retains only zone statistics; CPU pixel policies retain one
validated RGB image until invalidation/exit (about 23.7 MiB for 4K RGB8, in addition
to other allocations). Parity diagnostics may also retain reference pixels. This
is bounded source state, not image history, disk recording or a memory-saving claim.

Synthetic tests compare 40 unchanged-source processing/ACK steps against the same
real-pixel inputs for both direct and CPU/privately masked paths. They verify exact
full output, dither input and GPU-shadow parity, cadence limits, cancellation,
invalidation and immediate black after reuse. Parent protocol tests reject missing,
future/stale work clocks, wrong protocol versions and count mismatches. The older
fresh-frame protocol remains supported. The streaming suite passes eight tests;
the app passes 68 at this combined checkpoint, with 21 core tests.

Physical static-desktop, portal revocation, worker SIGSTOP, suspend/resume and USB
reconnect tests of these new binaries remain pending the user's return. No updated
binaries were installed into the user's live setup or enabled at login.

The final fallback gate passes 1617 tests, 23 optional skips, with 77.89% coverage.

## Exact Vulkan edge readback batching

The direct path prefetches its two outside rows and columns in one bounded
submission/map. Existing CPU luma reduction and bounds decisions are unchanged;
column slices use the exact detected vertical range. Dark/wide-bar cases retain
the full-image fallback. New transfer-count metadata makes the analysis work
visible to probe diagnostics. Buffer layouts reject overflow, invalid rectangles,
overlapping offsets, excessive region counts and aggregate readback above 128 MiB.

The [extended synthetic texture oracle](../perf/colour-stream-correctness-2026-10-14/batch-texture-oracle.json)
passes 48 zone, 48 ordinary-region, 48 batch-region and 48 changed-zone comparisons
for both channel orders, including zero-alpha pixels. A pure layout regression
also passes without requiring a GPU.

The [paired edge benchmark](../perf/colour-stream-correctness-2026-10-14/edge-batch-benchmark.json)
uses 100 alternating-order trials on the RTX 4080 SUPER, after warm-up, with
identical generated 3840×2160 pixels. Sequential median/p95: **5.126 / 6.482 ms**;
batched median/p95: **1.273 / 1.745 ms**. This is about 3.853 ms less at the median
for the four-region transfer/conversion stage. It excludes DMA-BUF acquisition,
desktop capture, USB, optical response and power; there is no whole-application
latency or energy claim. Full application and driver recovery validation remains
necessary before changing the default backend.

## Build and delivery gate

The complete native archive at revision `0130739` passes relocation, helper
discovery, isolated user-prefix installation/upgrade/two-way rollback, autostart
tracking, live stopped-service exclusion and uninstall preservation. Tests use
isolated HOME/XDG directories and never start capture or LED output.
See the [package smoke result](../perf/colour-stream-correctness-2026-10-14/package-smoke.json)
and [verification summary](../perf/colour-stream-correctness-2026-10-14/verification-summary.json).
Final local gates: 68 app + 21 core + 8 streaming + one GPU-layout test; full Python
fallback 1617 passed / 23 skipped / 77.89% coverage; Ruff, format, mypy and Rust
Clippy checks pass. The installed native binary and user configuration remain
unchanged. Live hardware adoption is a separate follow-up, not an implied result
of package tests.

## Live validation after the user's return

The downloaded PR #367 package (code checkpoint `0130739`) now has real KDE
Wayland/NL82K2 evidence in
[live-validation.json](../perf/colour-stream-correctness-2026-10-14/live-validation.json).
No updated binaries were installed and the real config SHA remained unchanged.
All probes used copies of the saved configuration. The capture-only probe
completed 413 exact full-pipeline CPU/Vulkan comparisons in eight seconds, with
no errors or coalesced prepared frames. KDE restored its existing permission.

Low-brightness output passed Stop with the tray alive, exclusive single-zone
preview, restart, owned-worker SIGTERM and explicit recovery. Freezing the owned
worker with SIGSTOP stopped mirroring after 2.059 seconds; the service remained
alive, reaped the child and recovered on explicit Start. The repeatable lifecycle
script now includes that check, waits for asynchronous child reaping before
measuring stopped resources, and drains diagnostic output during failure cleanup
to avoid blocking on a full pipe. Its complete live rerun passed, including a
2.041-second stall response. The first combined rerun exposed the profiling
script's process-exit race; this was not an application recovery failure.

Physical USB unplug/replug was detected and acknowledged output resumed. The
user confirmed both normal screen-following colours and resumed colours after
reconnect. Real KDE Stop sharing stopped output, released the child, left the
tray service available and did not reacquire capture or resume output during the
subsequent observation. The first revocation attempt expired before user action;
the retry passed. Every successful live probe verified restoration of the
controller's original power and brightness.

In one five-second desktop window, parent plus capture child used **4.179% of
one CPU core**, with summed RSS **145708 KiB** and PSS **130613 KiB**. This includes
20 Hz status polling and excludes compositor/GPU work and the settings UI. The
process inherited nice -8 even though the configuration requested normal priority.
These are short-window observations, not new speedup or power claims.

USB stage medians over the active window's status snapshots were **3.962 ms**
writing three HID reports, **18.028 ms** waiting for the first response and
**21.991 ms** for the complete transaction. These snapshots can repeat a
transaction and are not a per-packet latency distribution. Waiting for a reply
dominates this window; the data does not separate host scheduling from firmware
or establish when the LEDs present the colours.

The compositor kept producing fresh frames, so no cached-source packets were
observed in these runs. The low-cadence/static-reuse path remains covered by the
synthetic tests, not a live sparse-source measurement. Physical suspend, NL82K1,
sustained video/game cadence, instrumented emitted colour/optical response/power,
explicit synchronization and raw HDR remain open. The next colour work remains
measurement-led calibration and colour-domain/time-based smoothing; native
streaming remains opt-in and Python remains the preserved fallback.

## Subsequent colour refinement

The next implementation checkpoints (`534fd37`, `1ba4043`) correct final
linear-light mixing, device-gamma order, calibrated-zero ACK holds and elapsed
response. See [COLOUR_REFINEMENT.md](COLOUR_REFINEMENT.md) for independent
references, paired benchmarks and limits. These later colour outputs passed
software/capture parity and package checks but still need the user's physical
transition/neutral/dark-colour observation. The preceding hardware confirmations
must not be treated as confirmation of these changed outputs.
