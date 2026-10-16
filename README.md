# Nanoleaf Screen Mirror for KDE

[![CI](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/workflows/ci.yml/badge.svg)](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/workflows/ci.yml)
[![Native bundle](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/workflows/native-bundle.yml/badge.svg)](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/workflows/native-bundle.yml)
[![License](https://img.shields.io/github/license/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE)](LICENSE)

A Rust tray application that mirrors screen-edge colours to one Nanoleaf
NL82K1/NL82K2 USB strip on KDE Plasma Wayland. It includes settings, manual strip
setup, calibration, acknowledged USB output and reconnect recovery. The settings
window opens on demand; Stop pauses mirroring while keeping the tray available.

Priorities are visible response time, faithful colour, delivered FPS, then system
resource usage. Timing optimisations preserve calibration and colour correctness.
KWin capture remains the automatic backend. Optional permission-mediated
PipeWire/Vulkan streaming is available in Advanced, with exact zone sampling and
safe worker recovery. Reference/accuracy mode bypasses prediction and appearance
policies. Black turns off immediately and temporal accumulation blends in linear
light. Conservative 4D prediction is opt-in and disabled with dithering.

## Install and start

See [native installation, upgrade and rollback](docs/NATIVE_INSTALL.md) for the
complete requirements and instructions. Use a native release asset when available,
or the **nanoleaf-native-linux-x86_64** artifact from a passing **Native Rust bundle**
run on `main`. CI artifacts are test builds; a green build does not verify emitted
light on every device or desktop.

From a source checkout with the documented development dependencies installed:

```bash
bash scripts/build_native_bundle.sh dist/native
./dist/native/bin/nanoleaf-native --install-native
```

For a downloaded archive, extract it and run
`./native/bin/nanoleaf-native --install-native`. Open **Nanoleaf Screen Mirror
(Rust)** from KDE's application launcher, then Settings to select the monitor and
manually configure the strip's LED count, corner anchors and channel order.
Save / Apply keeps Settings open. `nanoleaf-native --doctor` checks readiness
without driving the LEDs.

Existing calibration and unknown configuration fields are retained in
`~/.config/nanoleaf-kde-sync/config.toml`. Validated saves create private backups.
The native installer keeps previous versions for rollback and does not enable
login startup automatically. Never run two applications against the strip.

## Scope and colour limits

One selected monitor, one USB strip and an authoritative manual LED count.
Streaming is opt-in on the verified KDE path. Captured SDR display-referred pixels
are not treated as raw HDR; unsupported raw PQ/HLG/FP16 formats and native
privileged DRM capture fail explicitly. No extra DRM capabilities are required
by the Rust app. The old Python application and privileged C helper are
[retired](docs/LEGACY_PYTHON.md). Previous native bundles support rollback.

The NL82K2 was tested with real output and physical USB reconnect; the user
confirmed colours resumed. A separate KDE Stop sharing test stopped mirroring
and required an explicit restart. NL82K1 emitted light, physical suspend/resume,
optical latency, colourimeter accuracy,
power and sustained game load remain unverified.

## Evidence and development

- [Research and architecture](docs/RUST_MIGRATION_RESEARCH.md)
- [Completion, measured performance and verification limits](docs/RUST_NATIVE_COMPLETION.md)
- [Streaming Vulkan backend](docs/RUST_STREAM_VULKAN.md)
- [Native application development](native/app/README.md)
- [Python retirement and configuration preservation](docs/LEGACY_PYTHON.md)

Rust contracts, colour/protocol replay, recovery and packaging tests run in CI.
Historical generated colour, geometry and protocol fixtures remain native
regression inputs; the old Python app, bridge and distribution CI are removed. Benchmark evidence lives in `perf/` and
separates software timing from unmeasured optical response.

Release history and tags are retained for recovery. Artifact cleanup only removes
old artifacts and protects the newest native download for main and open pull
requests. Native release tags use `native-vX.Y.Z`. There is no Python publishing workflow.
