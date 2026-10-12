# Optional SDR development bridge

This separately locked crate exposes the existing safe Rust core through PyO3
0.29.3. It requires Rust 1.85 (the core remains dependency-free at Rust 1.77).
Our Rust sources forbid unsafe code; PyO3 contains the native Python ABI boundary.
The bridge is not part of the PyPI build or installation and is never discovered,
loaded or enabled by the normal application. Capture, UI, USB transport, output
ownership and persisted configuration all remain Python.

Build from the repository root using the development interpreter:

```bash
.venv/bin/python scripts/build_rust_bridge.py
```

The helper downloads only Cargo's locked build dependencies on first use, builds
a release extension for that interpreter, and copies it under the ignored
`native/target/bridge/` directory with its interpreter/platform suffix. It does
not install anything or modify the running launcher. Linux is the only target
supported by this helper. No capabilities or privilege changes are needed.
An explicit trusted extension path is required for loading. ABI version 1 is
checked; an absent, incompatible or unloadable library fails this explicit setup
step and leaves the normal application unaffected.

```bash
export NANOLEAF_RUST_BRIDGE="$(.venv/bin/python -c 'import pathlib,sysconfig; print(pathlib.Path("native/target/bridge") / ("_nanoleaf_core" + sysconfig.get_config_var("EXT_SUFFIX")))')"
NANOLEAF_RUST_BRIDGE="$NANOLEAF_RUST_BRIDGE" .venv/bin/python -m pytest -q tests/test_rust_sampling_bridge.py --timeout=60 --timeout-method=thread
.venv/bin/python scripts/benchmark_rust_bridge.py --bridge "$NANOLEAF_RUST_BRIDGE" --iterations 30 --warmup 5 --repeats 3 --output /tmp/bridge-results.json
```

`NANOLEAF_RUST_BRIDGE` selects native tests only; the application never reads this
variable. Nothing in these commands captures screen pixels or writes LEDs.
Normal tests run fake failure/bypass contracts without a native build; native
parity tests skip unless the explicit path is supplied. CI builds the extension
and runs these contracts on Python 3.11 and 3.14, with Rust 1.85.

For a controlled replay, `load_rust_box_sampler(Path(...))` creates a callable.
Inject it into an in-memory `ColorPipelineParams.box_sampler` using
`dataclasses.replace`; this internal parameter is not an AppConfig setting and
is not persisted. A normal configuration-derived parameter set leaves it `None`.
The sampler is called only by the existing box-filter branch when multi-moment
selection is disabled. Privacy masking and edge anchoring happen in Python first.
The same mapping, measured LED profile, colour style and smoothing then run as
before. The pipeline bypasses native for compositor HDR, non-sRGB transfer or
non-BT709 context, float input, palette/wavelet modes and virtual oversampling.

Each call makes an immutable contiguous RGB8 byte copy, including for noncontiguous
or reversed arrays. The Rust function borrows those bytes, releases Python's GIL
while sampling, and returns RGB and little-endian float32 variance bytes. Arrays
are copied back to preserve Python's writable-output contract. Output length and
finite nonnegative variance are validated. This costs memory bandwidth but avoids
unsafe buffer pointers, ownership mistakes and NumPy mutation races. Small
rectangle/output vectors are allocated per call; the decode LUT is reused.

A normal native call/validation exception logs once, permanently disables that
instance and falls back to Python for the same frame and subsequent frames.
This is an experimental local extension, not an isolation boundary: process-fatal
bugs in any loaded native library cannot be recovered by a Python exception handler.
No native extension is required for the fallback.

PyO3's documented [manual build and interpreter selection](https://pyo3.rs/v0.29.3/building-and-distribution)
and [thread detachment](https://pyo3.rs/v0.29.3/parallelism.html) define the ABI and
GIL contract. A zero-copy NumPy bridge is deferred until measurements justify its
additional lifetime/concurrent-mutation requirements.

See [measured complete-path results](../../docs/RUST_SAMPLER_BRIDGE.md).
