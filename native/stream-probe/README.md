# Single-monitor streaming/Vulkan probe

Experimental, bounded Rust capture program. No USB output, original application
config edits or saved screenshots. It uses the standard ScreenCast portal, a
restricted PipeWire remote and a separate private native permission token.

Build with Rust 1.95+, PipeWire development headers, pkg-config/Clang and a
hardware Vulkan driver:

```sh
cargo build --manifest-path native/stream-probe/Cargo.toml --release --locked --bins
native/stream-probe/target/release/texture-oracle
native/stream-probe/target/release/nanoleaf-stream-probe --suite
```

Choose one monitor in KDE's screen-sharing dialog. Default mode runs the CPU
stream path for eight seconds; `--gpu-upload` adds a CPU-vs-GPU oracle;
`--dma-buf` requires actual importable GPU buffers; `--suite` runs all three
8-second modes on the same portal selection. Capture is capped at 30 FPS for
these bounded experiments, not a new application setting. Later runs can restore
the native permission without consuming the Python fallback's token. Stdout
contains timings, format, parity counts and process-only resource counters;
permission tokens and pixels are not printed.

For validation, with the Khronos validation layer installed:

```sh
NANOLEAF_VULKAN_VALIDATE=1 VK_INSTANCE_LAYERS=VK_LAYER_KHRONOS_validation \
  native/stream-probe/target/release/nanoleaf-stream-probe --dma-buf
cargo +1.95.0 test --manifest-path native/stream-probe/Cargo.toml --locked
cargo +1.95.0 clippy --manifest-path native/stream-probe/Cargo.toml --all-targets --locked -- -D warnings
```

The DMA pilot supports packed BGRA/RGBA, one plane and implicit synchronization;
multiplane, premultiplied, explicit SyncTimeline and raw-HDR paths are rejected.
It waits for producer completion and GPU ownership release before returning each
buffer. A GPU hang terminates this isolated probe instead of requeuing busy
memory. The normal Rust/Python apps and capture fallback are unchanged.

See [implementation, evidence and limits](../../docs/RUST_STREAM_VULKAN.md).
