# Rust application migration and measured refinement

Date: 2026-10-12. Branch: `codex/full-rust-rewrite`.
Update 2026-10-13: a [separate hardware Vulkan prototype](RUST_VULKAN_PROTOTYPE.md)
now demonstrates exact zone parity on the RTX 4080 SUPER. Its measured benefit
does not justify enabling it in the application; frame import/streaming and GPU
adaptive analysis remain pending.
Priority: **colour accuracy > latency/FPS > system performance**, including when
the target FPS cannot be reached. Predictive output follows core validation.

## Current delivery and adoption boundary

The repository now contains a working entirely Rust capture/colour/USB service,
KDE system tray, and on-demand Rust settings/calibration application. This is an
implemented and hardware-tested migration checkpoint. It is not yet a complete
replacement release: alternative capture backends, some optional analysis modes,
and predictive output remain behind verification gates.

The recovered Python implementation remains installed, unchanged, and available
through its existing launcher. Its calibration, real configuration, autostart,
udev rules and helper capabilities were not changed during these experiments.
Only a separate native desktop entry was installed to grant the new executable
KWin's normal screenshot permission. Never run both output implementations at
once: the Rust service checks for a running fallback, but the older fallback
does not cooperate with the Rust output lease if started afterwards.

Recovery checkpoints are `6c2bbd5` (recovered Python), `ebed5e3` (Rust core),
`920f575` (optional bridge), `cd63d81` (adaptive bridge), `c2787ae` (application
foundation), and `d982cf9` (native frame pipeline). The implementation built on
these checkpoints preserves one manually configured strip and one selected
monitor; it introduces no device platform, plugins or automatic length promotion.

The earlier [research audit](RUST_MIGRATION_RESEARCH.md),
[core prototype](RUST_CORE_PROTOTYPE.md), and
[adaptive migration measurements](RUST_ADAPTIVE_MIGRATION.md) remain evidence.
The user's subsequent explicit full Rust request supersedes the earlier hybrid
destination. Retaining the hybrid as a reversible fallback remains useful.

## Component disposition and architecture

| Component | Implemented replacement | Retained reference / remaining gate |
| --- | --- | --- |
| Python service/runtime | Rust control actor, private local socket, capture/colour worker | Python launcher and installed package retained |
| Python/NumPy adaptive analysis | Rust mixed-content decisions, palette candidates and temporal state | Optional bridge remains independently testable |
| Python calibration/style/blending | Rust sRGB/Oklab transforms, profile application, accumulation, smoothing and quantization | Golden oracles generated from recovered implementation |
| Python mapping/config | Rust single-strip geometry and versioned TOML import/edit | Unknown settings and both measured profiles retained |
| PyQt tray/settings | Rust `ksni` tray and on-demand `eframe/egui` Wayland process | Guided wizard, profile-file UX and other optional UI parity remain |
| Python HID | Rust `hidapi` native Linux backend and strict TLV/ACK transport | Both model contracts; live NL82K2, NL82K1 hardware not available |
| Python KWin/Qt decoding | Rust `zbus`, descriptor reads, validated raw QImage decoding | Portal/PipeWire/native DRM streaming not adopted |
| C DRM helper | Unused by native KWin application | Preserved for existing fallback, not removed or granted new privileges |

The capture/colour worker owns its D-Bus connection, raw frame and pipeline state.
Only a small completed strip-colour frame crosses to the USB actor. A one-slot
queue replaces obsolete frames rather than accumulating delay; replacement and
missed capture budgets are counted. Quantization history receives acknowledged
USB colours. Stop, preview and reload cancel their producer generation; an old
worker cannot deliver old colours into the new generation's slot.

The actor exclusively owns HID output. Stop clears LEDs and releases HID/capture
while leaving the tray and control service running. Preview pauses mirroring,
uses the same owner and expires after ten seconds. Reload clears old output
before changing geometry and cancels stale preview. Recovery reopens USB with a
two-second backoff; failed/uncertain writes are not blindly retried.

The private runtime directory is mode 0700 and the control socket 0600. Instance
and output leases use advisory locks. Config save uses the Python-compatible
config lock, validates before writing, rejects external edits and symlinks,
preserves comments/unknown fields, writes an exact private backup, and atomically
renames/fsyncs the replacement. Startup migration is in memory only. Calibration
values stay `f64` in storage/UI; conversion to the reference's `f32` happens at
the colour calculation boundary. This prevents decimal drift from opening and
saving Settings.

The existing `performance_priority` policy is best-effort nice adjustment only
(normal/high/very_high). Permission failure is visible and nonfatal; no
FIFO/RR scheduler or privileged fallback is used. There is still one Target FPS
setting. Quality is not silently reduced to meet it.

## Colour contract and intentional corrections

KWin 6.7's screenshot path uses an 8-bit RGBA render target and ARGB32
premultiplied QImage output. Its output layer defaults to sRGB. On this HDR-enabled
desktop the observed screenshot format was Qt format 6. Treat that capture as
display-referred SDR sRGB, apply the SDR LED profile, and avoid decoding the bytes
as PQ or applying display-primary adaptation a second time. This does not
recover original HDR scene luminance or establish correctness for future KWin
formats. Unsupported floating/HDR formats fail explicitly.
[KWin screenshot implementation](https://github.com/KDE/kwin/blob/Plasma/6.7/src/plugins/screenshot/screenshot.cpp),
[output-layer colour description](https://github.com/KDE/kwin/blob/Plasma/6.7/src/core/outputlayer.h).

Native decoding checks format, dimensions, row stride, total size and bounded
pipe completion. It handles native-endian ARGB, RGB/RGBA/BGR and premultiplied
alpha. Transparent premultiplied pixels are unpremultiplied; zero alpha maps to
black. Opaque pixels retain every source byte without unnecessary integer
divisions. No image downscaling was introduced to obtain performance results.

Reference/natural styles force full-pixel reference sampling and suppress
prediction and spatial stylistic spread. Adaptive sampling retains the existing
selected quality and its dark/letterbox fallback. Non-box area sampling now
retains spatial edge weighting; it no longer silently becomes an unweighted
mean. Privacy masks, corner mapping and manual order/reversal are preserved.

The old dither multiplied nominal noise by 255, allowing roughly 18-code colour
perturbations. The Rust implementation intentionally does not reproduce that
error: its eight-phase equal-channel dither is zero-mean and at most 0.4375 of
one code before quantization. Black remains off, integer neutral codes remain
exact, and fractional brightness keeps its intended duty cycle. Integer output
holding is bypassed when dithering, because holding first destroys that duty
cycle. This is ordered temporal dithering, not a claim of blue-noise spectrum.
Existing field names are preserved for configuration compatibility.

Colour evidence:

- 8,288 calibration/style oracle colours matched exactly on this host.
- 41 palette candidate cases and a 36-frame temporal sequence preserve choices.
- 576 blending frames stay within 0.0000458 of an 8-bit code before quantization.
- 84 layout/anchor cases preserve source rectangles, mapping and reversal.
- 480 evolving whole-pipeline frames include high/balanced quality, four styles,
  weighted/non-box edges, three localities, privacy, dark noise, black bars,
  neutrals and scene changes. Samples matched exactly; final output differed by
  at most one code. Separate dither tests verify black, all 256 neutral codes,
  bounds and fractional brightness.
- The user observed the real strip and confirmed: “Colours followed the screen
  correctly.” This is qualitative visual validation, not measured emitted gamut,
  white point, colour temperature or colourimeter ΔE.

## Measurements and optimisation decisions

Host: CachyOS, KDE Plasma 6.7.5 Wayland, Ryzen 7800X3D, RTX 4080 SUPER, selected
4K output at scale 1.5 with HDR enabled, NL82K2 with manual count 48. Raw evidence
is under [perf/full-rust-2026-10-12](../perf/full-rust-2026-10-12/).

### Complete offline colour and GRB framing

Before/after high-quality replay uses 18 cases × 12 evolving frames × 3 repeats,
648 paired frames per run, at 640×360, 2560×1440 and 3840×2160. Both paths receive
identical synthetic bytes, calibration and quality; dither is disabled equally
and checked separately. Samples, final colours and packets were exact on this
host. Timing excludes frame-file I/O, process launch, capture, USB and the GUI.

| Quality / input | Python median ms | Initial Rust ms | Refined Rust ms |
| --- | ---: | ---: | ---: |
| High adaptive, 1440p flashes/neutrals | 356.838 | 49.842 | 2.118 |
| High adaptive, 1440p mixed/dark noise | 253.523 | 37.602 | 8.892 |
| High adaptive, 4K flashes/neutrals | 997.117 | 114.214 | 4.791 |
| High adaptive, 4K mixed/dark noise | 785.493 | 85.356 | 20.772 |
| High adaptive, 4K privacy/letterbox | 1002.854 | 115.240 | 5.548 |
| Reference, 4K mixed/dark noise | 13.094 | 2.169 | 2.134 |

Python medians here are from the refined paired run; initial native medians are
from the earlier run. These synthetic sequences contain many uniform patches
and are not representative game-average speedups. High quality is also not the
default balanced quality; do not compare these numbers to older balanced runs.
The separate balanced replay checks the same full path at the default quality.
It covers 216 paired frames, with exact samples, output colours and packets on
this host. An initial harness run accidentally applied balanced quality only to
Python while leaving Rust at high; that invalid comparison is labelled and
retained separately. The harness now writes the selected quality to both inputs.

Profiling identified mixed-content analysis, rather than profile application,
as the expensive native stage. Exact uniform-patch detection avoids unnecessary
classification/candidate work. An exact cached dark-RGB hue calculation removes
repeated trigonometry; percentile selection avoids sorting an entire patch.
None of these changes subsamples more pixels or replaces colours with a global
average. The full paired replay gate remained required after optimisation.

### Live capture and acknowledged USB

| Stage / run | Measured result |
| --- | --- |
| Capture attribution before opaque-alpha fix | Reply 8.116 ms, pipe 6.517 ms, decode 26.585 ms median |
| Capture attribution after fix | Reply 8.626 ms, pipe 6.777 ms, decode 10.388 ms, total 26.086 ms median |
| Serial native reference run | 125 acknowledged frames / 8 s; response median 62.973 ms |
| Overlapped native reference run | 258 acknowledged frames / 8 s; reported ~32.35 FPS; response median 49.828 ms |
| Default adaptive/balanced, copied calibration | 207 acknowledged frames / 8 s; last FPS window 24.78; colour 4.933 ms, capture 26.878 ms, USB 16.826 ms, response 50.848 ms median |
| Native reference client CPU | ~66% of one core in lifecycle windows |
| Native adaptive client CPU | ~68% of one core in lifecycle windows |
| Active native client resident memory | Approximately 78–84 MiB across these short runs |
| Stopped native service CPU | 0 to 0.50% of one core in two-second, instrumented windows |

Live reference measurements use the user's actual reference style; the adaptive
test changes style/quality/sync only in a copied config. The saved `4d` preference
is retained but reference mode suppresses prediction. Adaptive tests explicitly
use standard sync because predictive parity is still gated. A probe attempting
unverified prediction produced zero frames, opened no USB and exited as a failure.

The worker overlap improved delivered FPS without dropping acknowledgements.
USB remained approximately 14–20 ms and did not become faster from matching the
Python transport's short final report. The initial native probe failed before
output because GET_LENGTH was wrongly interpreted as a two-byte body; actual
firmware returns one byte. The TLV header's length is two bytes. This was fixed
with a protocol regression test and live retesting; failed evidence is retained.

Reported response starts at the capture request and ends at USB acknowledgement.
It is **not optical end-to-end latency**. Changing-desktop runs are not a
controlled Python/Rust full-app comparison. Earlier recovered Python runs used
logical 2560×1440 capture, roughly 86–88% one-core CPU and 147–160 MiB RSS; native
runs use 3840×2160. These observations do not establish a percentage reduction
in total system CPU, GPU work or watts. No power measurement was taken.

Lifecycle profiling polls status at 20 Hz and excludes compositor/GPU and the
separate settings process. Stop releases capture descriptors: stopped FD count
returned to nine in both snapshots. RSS remains allocated after Stop; this is
not evidence that capture continues, nor a promise of low retained idle memory.
Start-command-to-first-ACK was approximately 155–169 ms in the bounded native
probes. This counter starts in the service actor; it excludes process launch and
opening the separate settings window.

Further raw-decoder attribution led to an explicit opaque conversion loop, with
alpha checked before entering it and a separate premultiplied format-6 path.
Synthetic 4K opaque conversion fell from 10.417 to approximately 6.4 ms in the
batch experiments. The paired probe alternates a frozen pre-specialization
format-6 reference and the native decoder on identical inputs, checks exact
pixels, and includes allocation. Its detailed timings are in
`decode-paired-final.json`; they should not be confused with complete capture.
Live capture subsequently measured 22.511 ms median. A later adaptive live run
sent 246 acknowledged frames in eight seconds with no queued-frame drops and a
51.843 ms median capture-to-ACK response. Processing and USB varied with changing
desktop content, so the extra delivered frames do not establish an optical
latency improvement. Controller power and brightness restoration were verified.

Settings uses a separate process and is measured separately in
`ui-resources.json`. That test runs in isolated KWin; its process-only memory/CPU
does not include compositor or GPU cost. The five-second idle window measured
0.20% of one core, 116.8 MiB RSS and 75.3 MiB PSS. Closing Settings removes that
process; those figures must not be hidden inside service-only memory claims.
Calibration sliders clamp only explicit
edits, so simply rendering an advanced profile cannot mutate a saved value.

## Capture research and remaining gates

| Option | Decision and evidence needed |
| --- | --- |
| KWin D-Bus | Implemented, unprivileged, normal KDE authorization, currently usable. Full-frame screenshot/pipe/CPU conversion remains the primary client bottleneck. |
| Portal + PipeWire | Preferred next streaming prototype. Must preserve permission/restore-token lifecycle, explicitly select one monitor, bound queued buffers, and establish format/colour metadata before adopting. |
| DMA-BUF | A transport/memory path, not a colour-processing algorithm. Requires plane offsets, strides, modifiers, ownership/synchronization and driver interoperability tests; CPU mapping/copies can erase its benefit. |
| DRM/KMS | Existing helper remains fallback infrastructure. Native replacement must not inherit privileged KWin-fd discovery or add capabilities without a demonstrated need. Host helper readiness was not established by the recovery audit. |
| Vulkan compute | Requires a real compute shader over a correctly imported frame, linear-light zone reduction, explicit synchronization and GPU-vs-CPU parity. The egui OpenGL renderer does not satisfy this requirement. Prototype before default; do not claim it implemented. |

See the [original primary-source research](RUST_MIGRATION_RESEARCH.md) for capture,
HDR metadata, HID and UI alternatives. Current KWin authorization matched the
canonical native executable through its separate desktop entry's
`X-KDE-DBUS-Restricted-Interfaces`. There was no permission override, root launch
or capability change.
[KWin 6.7 permission matching](https://github.com/KDE/kwin/blob/Plasma/6.7/src/utils/serviceutils.h).

Raw HDR transport is a separate correctness task: retain transfer, primaries,
reference white, scene/display interpretation, luminance units and buffer format;
then apply a measured strip gamut/brightness transform. Hardware brightness and
gamut limits preclude reproducing a 1,000-nit monitor literally. No calibration
quality can be inferred from arithmetic parity alone.

## Verification, remaining scope and stopping criterion

Rust core tests pass at 1.77. The application is checked and tested at its 1.95
minimum, including GUI compilation, Clippy with warnings denied, protocol I/O
faults and a real subprocess control/lifecycle test. The preserved Python suite
passes 1,636 tests with the optional bridge enabled and coverage above 75%; the
fallback-only run passes 1,613 with 23 optional tests skipped. Ruff, formatting
and mypy remain required. A Rust application CI job was added; hosted CI has not
run for this local branch.

Real NL82K2 checks cover capture authorization, acknowledged output, Stop,
exclusive zone preview, restart, descriptor release and controller restoration
readback. Copied-config settings tests verify Save/Apply leaves the UI open and
preserves both calibration profiles and the entire calibration table exactly.
No physical unplug, suspend/resume, NL82K1 emitted-light, colourimeter, optical
timing or sustained thermal/power testing has been claimed.

Remaining adoption gates:

1. Complete optional sampling/analysis policy and UI parity, or explicitly retire
   a feature only with correctness evidence. Unsupported policies fail before
   opening USB and leave their persisted configuration intact.
2. Validate native streaming permission, reconnect, format and HDR contracts;
   compare GPU compute only after correct stream/import synchronization exists.
3. Long-run and physical reconnect/suspend tests, controller-model verification,
   full-app GUI-inclusive resource measurement and measured optical colour/latency.
4. Packaging/desktop integration and migration/rollback validation before
   replacing the normal launcher or removing Python.
5. Predictive/perceived-FPS refinement after those core gates: measure prediction
   error, clamp extrapolation, reset on cuts/stalls, keep neutrals/black correct,
   and disable it in reference/accuracy mode. Extra writes are not captured FPS.

Stop micro-optimizing a stage when its measured cost is small relative to capture
or acknowledged USB and further changes risk fidelity. Current profile/style
math is already inexpensive; removing calibration, colour guards or ACKs to
inflate FPS is unacceptable. Capture transport is the next major architecture
experiment; the existing working fallback remains the regression reference.
