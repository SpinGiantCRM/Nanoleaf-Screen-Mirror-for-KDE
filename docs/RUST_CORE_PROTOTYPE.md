# First Rust core prototype: results and adoption limits

Date: 2026-10-12, Australia/Adelaide. Branch: `codex/rust-core-prototype`.

This records the first standalone prototype. The subsequent
[optional in-process bridge](RUST_SAMPLER_BRIDGE.md) now measures copy/conversion
overhead and the complete offline colour path; normal mirroring defaults remain unchanged.
Python reference/fallback: recovered commit `6c2bbd5`, retained on
`codex/recovery-rust-audit`. The live Python source, calibration/config schema,
capture/USB paths, UI and installation were not changed by this prototype.

## Implemented

The dependency-free `native/` workspace contains a checked SDR CPU sampler and
Nanoleaf TLV helpers. It preserves NL82K1/NL82K2 IDs/model validation, manual count
authority, channel permutations including GRB, big-endian lengths, HID response
padding, status validation and response-type wrapping. It does not perform HID
writes. Protocol framing and sampling are separate modules; no daemon, generic
mapping engine, plugins, UI or configuration writer was added.

The sampler takes an explicitly SDR sRGB RGB8 frame, byte stride and the existing
effective source rectangles. It counts every pixel once and derives linear-light
means and encoded variance from histograms. Output buffers are reusable and there
are no per-pixel allocations. Frame dimensions, stride, required length and
arithmetic are checked before indexing. Unsupported HDR fixture labels, malformed
headers, missing bytes and inconsistent manual counts fail before sampling.

The core cannot read or overwrite calibration. The harness compares the user's
config and launcher bytes before/after testing and confirmed they were unchanged.
No installed fallback, capabilities, udev permissions, capture session, physical
LED state or autostart settings were modified. Cargo build outputs stay ignored
under `native/target/`; the Rust 1.77 verification toolchain was added without
changing the default Rust toolchain.

## Measured comparison

Host: Ryzen 7 7800X3D, Linux 7.2.9 CachyOS-style environment; Python 3.14.7 and NumPy
2.5.1; Rust 1.98 release build with thin LTO and one codegen unit. The same seeded
frames, 48 tight source zones, effective anchoring and seven bytes of row padding
were used for both languages. Each size was repeated three times, with five
warmups and 30 timed samples per language/run; execution order alternated. No
other task tests/builds were run concurrently with the recorded comparison.

The table reports the median of the three run medians:

| Frame | Recovered Python box sampler | Rust core sampler | Ratio |
|---|---:|---:|---:|
| 640×360 | 1.608 ms | 0.084 ms | 19.2× |
| 2560×1440 | 4.950 ms | 0.743 ms | 6.7× |
| 3840×2160 | 9.147 ms | 1.597 ms | 5.7× |

Rust p95 ranges across the three runs were 0.104–0.238 ms, 0.810–0.982 ms and
1.680–2.051 ms respectively. Small-workload ratios reflect removal of Python
call/array overhead as well as native looping; they are not whole-app ratios.

All three random-frame sizes and the black, grey, white, primary, mixed-neutral,
remainder-pixel and local-edge fixtures produced **zero RGB code differences** in
these measurements. Maximum linear mean difference was approximately 2.45e-8;
maximum variance difference was 0.000244 code-squared, within the explicit fixture
tolerances. The variance difference comes from Python's float32 zone-output array
versus Rust's float64 result. Every native sampled GRB TLV matched the Python
encoder for the same sampled colours. No physical colour accuracy is inferred.

Standalone process PSS medians were approximately:

| Frame | Python sampler process | Rust sampler process |
|---|---:|---:|
| 640×360 | 32.2 MiB | 1.3 MiB |
| 2560×1440 | 42.4 MiB | 12.1 MiB |
| 3840×2160 | 56.0 MiB | 25.7 MiB |

These snapshots include the loaded fixture and each process's libraries. They do
not establish the memory footprint of a Rust capture daemon, GUI, Vulkan driver
or the full recovered app. Both processes read identical file bytes, but native
allocation strategies differ. Whole-child CPU and spawn/load/sample/exit values
are recorded separately; Python import/native-library startup activity is included
in those values, so they must not be reported as per-frame CPU or power savings.

## Boundaries of the result

The measured Python function is the box mean/variance stage used by the recovered
application. The rest of the colour pipeline, palettes/prediction, HDR/gamut/LED
calibration, queues, capture and USB are excluded from the native comparison.
The existing full Python production benchmark was also run and passed its timing
budgets; it remains a separate workload, not a native full-pipeline benchmark.

Rust is **not integrated into mirroring**. Therefore this prototype changes neither
live output FPS nor measured screen-to-light latency. The earlier recovered app's
~28–29 FPS and ~18 ms screenshot call must not be replaced by a frame-rate or latency
calculation derived from this isolated kernel. IPC/FFI overhead is unmeasured, and
no watts, battery savings, optical response or Rust HID reconnect result is claimed.

The existing calibration, metadata handling and output ownership stay in Python.
PQ/HLG/FP16, alpha, primaries conversion, privacy-mask construction, device mapping,
calibration matrices, dither and temporal processing are not ported yet. Native
sampling must receive the same effective rectangles/masked pixels and a verified
colour-domain label; an unknown/HDR buffer cannot simply be relabelled sRGB.

## Validation and next stage

- Nine native contract tests pass on Rust 1.77, and in a Rust 1.98 release build.
  They include all neutral codes and a 4,096-case malformed-length sweep.
- Seventeen shared Python/Rust protocol vectors and eight malformed fixture
  rejection cases pass. The latter include HDR labels, invalid stride/dimensions,
  truncation, overflow and manual-count mismatch.
- The complete Python suite passes: **1,591 tests**, **77.52% coverage** (75% gate).
  Lint, format and source type checks pass; the workflow YAML parses locally.
- A separate CI job checks the minimum Rust compiler and quick cross-language
  fixtures. This branch is local; hosted CI has not run for it.

The evidence justifies evaluating an optional in-process native sampler bridge
next, initially in offline/replay comparisons. Measure the bridge plus the full
Python colour/calibration path on identical frames, including data-copy cost,
before enabling it for mirroring. It must remain explicitly selectable with a
Python fallback and retain exclusive preview/output ownership. Streaming capture
still deserves a separate prototype because capture dominates the recovered live
timings. Neither result justifies replacing the UI or removing Python now.

The [benchmark harness and fixture contracts](../native/README.md) contain commands
to reproduce the work. [Raw timings, compiler/executable provenance and parity
results](../perf/rust-core-2026-10-12/results.json) accompany this report; the
[current Python production benchmark](../perf/rust-core-2026-10-12/python-production.json)
is retained separately. The earlier [architecture research](RUST_MIGRATION_RESEARCH.md)
continues to define the broader migration and hardware acceptance gates.
