# Measured Rust Vulkan sampling prototype

The subsequent [streaming/DMA-BUF experiment](RUST_STREAM_VULKAN.md) now
implements genuine shared-frame import and documents live results. This document
retains the original uploaded-frame baseline and its adoption decision.

Date: 2026-10-13. Built after the native application checkpoint `5531880`.
The normal Rust application and Python fallback are unchanged by this separate
prototype. Neither enables GPU sampling automatically.

## Implemented and verified

`native/gpu-probe` creates a hardware Vulkan device through wgpu 30.0.1, compiles
and dispatches an actual WGSL compute shader, then synchronizes and reads back
integer zone histograms. It rejects software Vulkan adapters as substitutes for
hardware measurements. This is real GPU sampling, not Vulkan library detection
or the GUI's renderer.

The shader retains every RGB8 source pixel. Integer atomic histogram counts make
parallel reduction exact; the CPU applies the same 256-entry sRGB lookup and
float64 mean/variance calculation as the established reference. That deliberately
keeps a small CPU reduction rather than introducing GPU floating-point error.
Each histogram is validated for matching channel totals and its expected pixel
count. An all-black zone is valid output, not a capture failure.

The source is explicitly SDR RGB8 with checked dimensions/stride/size. Input is
uploaded from CPU memory. At 48 zones, histogram readback is 147,456 bytes (144
KiB). It is **not** DMA-BUF import, zero-copy capture, HDR processing, streaming,
GPU adaptive-palette analysis or the ideal 576-byte float readback. No USB device,
capture permission or user configuration is opened by this executable.

Buffer/pipeline resources are reused within each resolution. Mapping waits have
a two-second bound; readback mappings are cancelled/unmapped on failure as well
as success. Existing app/core code forbids unsafe Rust in its own sources.
[wgpu compute pipeline API](https://docs.rs/wgpu/30.0.1/wgpu/struct.ComputePipelineDescriptor.html).

## Colour parity

The real adapter reported NVIDIA GeForce RTX 4080 SUPER, backend Vulkan,
DiscreteGpu, driver NVIDIA 615.78.08. The full probe measures 3 resolutions × 5
patterns × 5 alternating repetitions, 75 paired runs and 3,600 zone comparisons.
Patterns cover black, neutral grey, white, mixed colours and deterministic noise.
Rows contain padding; three source rectangles also exercise negative origins,
clipped remainder pixels and completely outside-frame geometry.

Every output matched exactly: encoded RGB, linear RGB, variance and pixel count.
There was no tolerance relaxation, brightness/gamut change, sparse sampling,
downscaling, smoothing change or neutral exception.

## Measurements and decision

Medians from alternating CPU/GPU order, after two GPU warmups per pattern.
Frame generation and pipeline creation are outside the measured sample call.
GPU-path timing includes staging/upload calls, submission, synchronization,
readback, histogram validation and the CPU reference reduction. It is wall time,
not pure shader duration or an optical response measurement.

| Resolution / pattern | CPU sampling ms | Complete Vulkan sample ms |
| --- | ---: | ---: |
| 640×360, black | 0.125 | 0.178 |
| 640×360, noise | 0.108 | 0.177 |
| 2560×1440, grey | 0.930 | 1.021 |
| 2560×1440, mixed | 0.795 | 0.691 |
| 3840×2160, grey | 1.852 | 1.361 |
| 3840×2160, mixed | 1.883 | 1.370 |
| 3840×2160, noise | 1.828 | 1.381 |

At 4K, the CPU-side upload/staging call alone takes approximately 1.11–1.14 ms.
The complete-path gain is about 0.25–0.51 ms, while live KWin capture takes
approximately 22–23 ms and USB acknowledgement remains another substantial
stage. Setup costs were 103–122 ms per resolution in the full run (254 ms for the
separately launched quick probe). These are not daemon startup measurements.

**Decision: retain CPU sampling as the default.** The prototype establishes
colour correctness and a modest high-resolution sampling gain, but does not
justify another driver dependency/context in normal daily use. It does not show
a meaningful complete-app latency benefit or lower total power. Lower-resolution
cases are slower, and default adaptive analysis is outside this prototype's
scope. No watts, GPU-kernel timestamps, emitted light or game workload measurements
were taken.

The next useful experiment is a persistent permission-mediated stream and a
validated frame-sharing/import path, which might avoid full CPU upload. Any such
path must preserve transfer/primaries/range/stride/modifier metadata, explicit
buffer ownership and fences, one selected monitor, revoke/reconnect recovery and
the same colour parity before promotion. Existence of this shader does not prove
those capture contracts.

## Reproduce

```bash
cargo build --manifest-path native/gpu-probe/Cargo.toml --release --locked
native/gpu-probe/target/release/nanoleaf-vulkan-probe --quick
native/gpu-probe/target/release/nanoleaf-vulkan-probe > /tmp/vulkan-zones.json
cargo +1.95.0 clippy --manifest-path native/gpu-probe/Cargo.toml --all-targets --locked --offline -- -D warnings
cargo +1.77.0 test --manifest-path native/Cargo.toml --locked --offline
```

The first build requires downloaded dependencies; they are locked separately
from the production app. Raw results are in
[perf/rust-vulkan-2026-10-13](../perf/rust-vulkan-2026-10-13/). A CPU-only or
Vulkan-unavailable host fails the hardware probe rather than inventing timings.
The core's new external-histogram API has independent black/linear-light,
overflow and inconsistent-channel regression tests; the application colour and
lifecycle suite also passed after the shared reduction was factored out.
