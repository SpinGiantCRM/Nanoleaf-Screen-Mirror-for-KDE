# Rust sampler bridge: measured stage 2

Recorded on 2026-10-12 on the same local host as the first core prototype.
Branch: `codex/rust-sampler-bridge`, based on `ebed5e3`. The recovered Python
implementation remains preserved at `codex/recovery-rust-audit` (`6c2bbd5`).

## Result and adoption decision

The optional in-process SDR box sampler remains faster after including frame
copies and the rest of the Python colour pipeline. It produces identical sampled
RGB and final GRB command bytes for every recorded fixture/repetition.
It is useful enough to continue testing, but is **not enabled by default**.

The default adaptive colour mode did not use the native box sampler in the control
fixture. Its near-identical timings do not establish an improvement for daily use
under that mode. Replacing its algorithm with a box mean would change behaviour
and is not justified by this test. Nor does this result justify a UI rewrite.

## Scope and implementation

The Rust core remains unchanged and dependency-free. A separate optional PyO3
crate wraps it without raw-pointer or unsafe code in our source. Rust 1.85 is the
bridge's minimum supported compiler; the core's Rust 1.77 contract remains intact.
An immutable byte copy is the initial ownership boundary. Borrowed Python bytes
stay alive while native computation releases the GIL. Copy cost, rectangle
conversion, result allocations and conversion back to writable NumPy arrays are
included in measured calls. No per-frame subprocess is used.

An internal in-memory sampler parameter passes through the existing full colour
pipeline. The normal loader never sets it or searches for native libraries.
The PyPI build/install method, launcher, configuration schema, UI and runtime
capture/HID paths are unchanged. No privileged access was added.

Python still applies privacy masks and effective anchoring, letterbox clipping,
calibrated zone ordering, LED profiles/matrices/gamma, brightness, colour styles,
smoothing and protocol output. HDR or non-sRGB/non-BT709 context, floating-point
input, multi-moment selection and non-box modes retain Python processing.
Native failures/invalid outputs disable the experimental sampler once and return
to Python for the same frame. Missing libraries affect only explicit experiment
setup; the application requires no Rust installation.

## Measurements

Median of three run medians, 30 timed paired iterations and five warmup iterations
per run, 48 source zones. Python and Rust call order alternates each iteration.
No tests/builds ran concurrently with the recorded timing comparison.
The reference is the recovered box implementation, reached with native injection
`None`; the experimental path changes only that injection.

"Full path" below means `process_frame` plus GRB TLV construction. It includes
sampling, copies, letterbox work and downstream colour/calibration/smoothing.
It excludes capture, permission setup, USB transmission, LEDs' physical response,
startup and display/compositor costs.

| Frame | Case | Python full path | Rust bridge full path | Speed ratio |
| --- | --- | ---: | ---: | ---: |
| 640×360 | SDR box | 2.381 ms | 0.755 ms | 3.2× |
| 2560×1440 | SDR box | 6.164 ms | 1.839 ms | 3.4× |
| 3840×2160 | SDR box | 11.642 ms | 3.511 ms | 3.3× |
| 640×360 | Profile + privacy + letterbox | 2.493 ms | 1.010 ms | 2.5× |
| 2560×1440 | Profile + privacy + letterbox | 6.232 ms | 2.660 ms | 2.3× |
| 3840×2160 | Profile + privacy + letterbox | 11.826 ms | 5.637 ms | 2.1× |
| 640×360 | Default colour modes control | 7.038 ms | 6.954 ms | No native calls |

For the plain box case, process CPU time medians were 2.322→0.748 ms,
6.140→1.823 ms and 11.549→3.468 ms at the three respective sizes. These are CPU
time per replayed call, not measured whole-app CPU percentages or power savings.
Standalone contiguous byte copies measured 0.014, 0.240 and 0.803 ms; the privacy
case adds a separate mask copy and has different memory/cache behaviour. The
full path already includes its copies; do not add these isolated timings again.

All fixtures are deterministic synthetic random RGB8 frames (seed 42), with extra
black bars and a privacy rectangle for the second profile. A nonidentity LED
matrix, channel gains and gamma exercise calibration. Reverse output mapping
exercises zone ordering. No personal screen pixels or calibration contents are
stored. The harness hashes all files in the user's configuration directory and
the desktop launcher before/after; hashes were unchanged. Those private file
names/contents are not included in published results.

Previous output history is fixed to black. Global temporal accumulation and
frame-index dither are disabled equally for timing so state contamination cannot
affect the paired comparison. Separate sequence tests verify accumulated/dithered
output parity. This is not the earlier production benchmark workload: default
mode, frame content and state choices differ, so its timings cannot be compared
directly with the previous 24.5 ms production-pipeline number.

Raw per-call wall/CPU/copy samples, frame/library hashes, actual embedded compiler,
native invocation counts and preservation status are in
[`perf/rust-bridge-2026-10-12/results.json`](../perf/rust-bridge-2026-10-12/results.json).
Every box full-path run recorded 30 native calls; every default control run recorded
zero. All output parity checks passed exactly. Variance uses the existing float32
contract with an absolute tolerance of 0.002 code-squared.

## Validation and limits

The bridge tests exercise padded/reversed/channel-strided frames, clipping,
negative/empty geometry, privacy masking, all 256 neutral codes, malformed/HDR
input, calibration/mapping/smoothing sequences, temporal accumulation/dither,
failure fallback and unsupported-mode bypass. Native Rust core contracts and
normal Python regression/lint/type/security gates are retained. The CI bridge
matrix adds Python 3.11/3.14 checks but has not been run on GitHub for this local
branch. See the accompanying validation record for local command results.

Locally: 23 bridge contracts passed under both Rust 1.85 and 1.98 builds on Python
3.14.7; the full Python suite passed all 1,614 tests with 77.86% coverage. The nine
Rust core contracts passed at Rust 1.77. Format/Clippy, Ruff, mypy and Bandit gates
passed. The original Python production benchmark still passes its budgets. This
validates the retained default path; it does not demonstrate a native speedup for
that different production workload. Python 3.11 bridge support awaits hosted CI.

There are no new live capture, USB reconnect, HDR correctness, power, full-app
memory or end-to-end latency measurements. Those claims cannot follow from this
CPU replay. Python/Qt remain loaded, so the earlier standalone Rust-versus-Python
process memory comparison does not predict this bridge's application footprint.

## Next evidence required

1. Profile the default adaptive palette path with representative replay sequences;
   migrate its expensive operations while preserving neutral/black and temporal
   contracts if the measured cost warrants it.
2. Compare replayed full configuration/mapping/profile sequences, then bounded live
   capture/output with explicit SDR provenance before exposing a runtime opt-in.
3. Measure capture/USB distributions and stale-frame/drop behaviour after integration.
   Evaluate streaming capture separately from sampler/GUI changes.
4. Consider zero-copy buffers only if copy bandwidth meaningfully limits the real
   workload; test lifetimes and concurrent mutation before adopting them.

Reproduce the prototype with the [development bridge instructions](../native/python-bridge/README.md).
