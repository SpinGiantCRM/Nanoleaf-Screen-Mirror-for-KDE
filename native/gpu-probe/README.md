# Vulkan zone-sampling experiment

This independent Rust workspace actually dispatches a WGSL compute shader through
Vulkan. It is not wired into the application, does not open USB/capture/config,
and does not change either working fallback. Software Vulkan adapters are rejected
as hardware benchmark substitutes.

The shader counts every RGB8 pixel into integer zone histograms. Readback uses
the same CPU float64 linear-light mean/variance reduction as the reference,
retaining exact colour arithmetic and valid all-black frames. At 48 zones this
reads back 144 KiB, not a full 4K image or a claim of the ideal 576-byte float
result. Full source RGB bytes still upload from the CPU; this is not DMA-BUF,
zero-copy capture, streaming, raw HDR handling or GPU adaptive-palette processing.

```bash
cargo build --manifest-path native/gpu-probe/Cargo.toml --release --locked
native/gpu-probe/target/release/nanoleaf-vulkan-probe --quick
native/gpu-probe/target/release/nanoleaf-vulkan-probe > /tmp/vulkan-zones.json
```

The bounded synthetic probe checks black, grey, white, mixed colours and noise,
with padded input rows, alternating CPU/GPU timing order and reused resources.
Every sample field must match exactly. Wall timings include CPU upload/staging,
dispatch, synchronization/readback and CPU reduction; they are not pure GPU-kernel
timings. Adapter identity and startup are recorded separately. No screen pixels,
controller state, calibration or user configuration are written.

Promotion requires proof of a faster complete capture/colour path with colour
parity, correct permission and buffer lifetimes, and driver/format recovery.
Readback and upload costs must remain in the comparison. The normal application
retains its measured CPU implementation even when Vulkan is installed.

[wgpu 30 API](https://docs.rs/wgpu/30.0.1/wgpu/),
[Vulkan compute dispatch](https://docs.vulkan.org/refpages/latest/refpages/source/vkCmdDispatch.html).
