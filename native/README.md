> Historical prototype report. The application is now Rust; the Python runtime,
> bridge and benchmark generators described below were retired on 2026-10-16.
> Use [native installation](../docs/NATIVE_INSTALL.md) and [retirement details](../docs/LEGACY_PYTHON.md).

# Rust colour and protocol core

This workspace is an independently testable CPU/protocol prototype. It is not
installed by PyPI, automatically enabled by the Python app, a daemon, or a capture/HID backend.
The recovered Python runtime remains installed as the reference and fallback.
The separate [Rust application](app/README.md) now supplies capture, USB, tray
and a native UI; the core itself remains independent of those adapters.
The repository's existing license also covers this code; the crate is not
published to crates.io.

The core has no third-party dependencies and forbids unsafe Rust. Its modules are:

- `protocol`: NL82K1/NL82K2 identity checks, big-endian TLV framing and response
  validation, explicit channel order and authoritative manual output count.
- `sampling`: checked, borrowed SDR sRGB RGB8 buffers with explicit byte stride;
  full-pixel linear means and encoded-channel variance using reusable lookup data
  and stack histograms. Callers supply already anchored/masked source rectangles.
- `adaptive`: allocation-bounded SDR mixed-content classification and dark-biased
  means for the optional palette prepass. Borderline numerical decisions use the
  Python reference in the optional bridge; the application uses the native policy.
- `palette`: candidate scores, mixed-content guards and temporal selection.
- `colour`: measured LED calibration, sRGB/Oklab style and black/neutral handling.
- `blending`: temporal and neighboring-zone colour processing.
- `nanoleaf-core-probe`: bounded fixture reader, protocol oracle and release-build
  microbenchmark executable. It never opens USB, D-Bus, DRM or user configuration.

The sampler accepts an explicit SDR byte contract. It does not decode PQ, HLG,
FP16, colour primaries, display metadata or alpha. Calibration and smoothing
operate separately on small, explicitly SDR zone arrays.
The fixture reader rejects HDR-labelled input instead of silently treating it as
SDR. Empty/clipped zones produce black; a valid all-black frame is not an error.
No strip length is detected or promoted. GRB remains an explicit output choice,
and a count mismatch fails before framing a command.

## Verification

Run from the repository root. Rust 1.77 is the minimum compiler; 1.77 and the
host's 1.98 were verified locally. Cargo.lock is checked in. Cargo's offline mode
requires no crate downloads because this workspace uses only the standard library.

```bash
cargo fmt --manifest-path native/Cargo.toml --check
cargo clippy --manifest-path native/Cargo.toml --all-targets --locked --offline -- -D warnings
cargo test --manifest-path native/Cargo.toml --locked --offline
cargo build --manifest-path native/Cargo.toml --release --locked --offline
.venv/bin/python scripts/benchmark_rust_core.py --quick --iterations 3 --warmup 1 --repeats 1 --output /tmp/native-parity.json
```

The Rust tests cover both supported models/IDs, response status/padding/truncation,
16-bit length boundaries, all channel permutations, count mismatch, every neutral
code 0–255, mixed black/white linear means, padded rows, clipped/remainder pixels,
invalid/overflowing geometry, and a 4,096-case declared/actual response-length sweep.
The shared harness verifies 17 protocol vectors and eight malformed fixture
rejections against the release executable, alongside pixel/variance parity.

CI has a separate Rust 1.77 contract job and a quick cross-language fixture gate.
It does not gate performance using host-specific timings. Hosted CI has not yet
run for this local branch.

## Benchmark and fixture format

```bash
.venv/bin/python scripts/benchmark_rust_core.py --iterations 30 --warmup 5 --repeats 3 --output /tmp/rust-core-results.json
```

Both processes consume the same regenerated synthetic file bytes, including row
padding. Python calls the recovered application's `_zone_colors_via_box_filter`
with multi-moment selection disabled and anchoring already applied. Rust samples
the same effective rectangles. This compares the complete box mean/variance stage,
not the default adaptive-palette pipeline or end-to-end mirroring.

Fixture version 1:

- Frame: `NSRGB001`, three little-endian uint64 fields (width, height, byte stride),
  then RGB8 rows. File size is limited to 128 MiB. Last-row padding is optional in
  the core frame view; the harness writes it for all rows.
- Zones: `NZONE001`, little-endian uint64 zone count and manual count, then four
  little-endian int64 fields per rectangle (x, y, width, height). The CLI requires
  equal nonzero counts and limits the list to what fits a Nanoleaf TLV payload.
- Protocol: [shared JSON vectors](fixtures/protocol.json), read by the Python
  oracle and executed against the native command-line parser/encoder.

Fixtures live only in a temporary directory; no screen pixels or personal config
are saved. Source frame hashes, compiler identity, executable hash, raw timings
and operational preservation checks are recorded in the result JSON. The compiler
embedded by the probe is authoritative when the default installed compiler differs.

Kernel timing excludes file I/O, process startup and JSON serialization. Rust reuses
caller-owned sample output; Python returns its normal output arrays. Full child
CPU time and spawn/load/sample/exit time are separately labelled and include imports,
warmup and serialization. RSS/PSS snapshots include each standalone process and
loaded fixture, not a complete GUI/capture runtime. Native histograms retain every
pixel; no downscaling or sparse sampling is used.

The probe is an offline diagnostic executable, not a per-frame subprocess design
for mirroring. The optional [development bridge](python-bridge/README.md) measures
marshalling/copies and the complete processing path. Runtime defaults stay unchanged.

Parity permits at most one 8-bit code of rounding difference, absolute linear mean
error <=1e-7 and variance error <=0.002 code-squared. Black, uniform grey/white and
primaries must match exactly. Variance in the Python zone array is float32; Rust
keeps float64. Both use float32 sRGB decode entries with higher-precision reduction.
The native encoder uses ties-to-even quantization to match NumPy's rounding policy.
Rust's floating transcendental functions can have small platform/compiler differences;
the fixture tolerances remain required on every platform. [Rust float documentation](https://doc.rust-lang.org/std/primitive.f64.html#method.round_ties_even).

The probe applies `black_box` to inputs and outputs during timing as a best-effort
optimisation barrier; this is not a guarantee against every compiler transformation.
[Rust benchmark barrier documentation](https://doc.rust-lang.org/std/hint/fn.black_box.html).

See [measured results and adoption limits](../docs/RUST_CORE_PROTOTYPE.md).
