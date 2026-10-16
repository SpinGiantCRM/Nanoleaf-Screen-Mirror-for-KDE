# Contributing

Build the Rust application and matching capture worker using [native installation](docs/NATIVE_INSTALL.md).
Read [AGENTS.md](AGENTS.md) for scope, colour, calibration and hardware guardrails.
One selected monitor, one manually configured strip and acknowledged serial USB
remain the product contract. Do not introduce new FPS or priority controls.

Run `bash scripts/release_gate.sh` for Rust core/application/capture tests, Clippy,
formatting and operator-script contracts. Python is used only for developer and
operator scripts; install Ruff for their lint/format checks. Hardware Vulkan
oracles, live colour parity, permissions and physical USB/session recovery are
separate from headless CI and must be reported accurately.

Keep calibration and unknown configuration fields compatible. Changes to mapping,
colour or schemas require meaningful regression tests under `native/app/tests/`
and `native/core/tests/`. The immutable native bundle must preserve user data and
keep earlier paired binaries for rollback. Validate package changes with
`scripts/verify_native_bundle.py` in isolated user directories.

The old Python app, C DRM helper, bridge and Python distribution are retired.
Historical evidence and native golden fixtures remain. Do not reintroduce them as
runtime dependencies. Keep public PR descriptions concise, include measured
benefits and verification limits, and never commit secrets or captured pixels.
