# Rust application

The experimental replacement runs capture, calibrated colour processing, USB,
tray and settings entirely in Rust. It does not require Python, Qt or the old C
DRM helper. Development is on `codex/full-rust-rewrite`; the installed Python
application and its launcher remain the reference and fallback.

The priority is **colour accuracy > latency/FPS > resource usage**. Optional portal/Vulkan streaming is integrated and tested; native DRM/raw HDR
and optional analysis modes still require verification.
This is a working native application checkpoint, not a feature-complete release.
See [implementation, measurements and remaining gates](../../docs/RUST_APPLICATION_MIGRATION.md).

## Build and run locally

Rust 1.95 or later is required for the GUI; the independent core supports 1.77.
Dependencies are locked. The first build downloads dependencies; subsequent
builds can add `--offline`.

```bash
cargo build --manifest-path native/app/Cargo.toml --features gui --release --locked
native/app/target/release/nanoleaf-native --preflight
native/app/target/release/nanoleaf-native --install-launcher
native/app/target/release/nanoleaf-native --daemon
```

The separate native desktop entry authorizes the canonical Rust executable for
KWin ScreenShot2 using KDE's standard permission declaration. Moving the binary
requires updating that entry. It does not overwrite the Python launcher or change
autostart. Stop/quit the fallback before native LED output; run one application
at a time. The older fallback does not participate in the native output lease.

`--daemon` honours your existing `start_on_launch`; `--run` starts immediately.
`--headless` omits the tray but also honours `start_on_launch`. A second argument
selects a configuration file. Loading/preflight/settings alone never write config
or open USB. Missing calibration and unverified colour policies prevent Start.

```bash
native/app/target/release/nanoleaf-native --settings /path/to/copied-config.toml
native/app/target/release/nanoleaf-native --status
native/app/target/release/nanoleaf-native --stop
native/app/target/release/nanoleaf-native --start
native/app/target/release/nanoleaf-native --quit
```

Stop keeps the tray/service alive, clears the LEDs and releases capture/USB.
Setup previews pause mirroring and expire after ten seconds. Settings Save/Apply
keeps the window open; it preserves unknown keys/comments and both measured
profiles, rejects stale saves, and retains an exact backup before an atomic save.
The manual count and four anchors remain authoritative.

## Verification and profiling

```bash
cargo fmt --manifest-path native/app/Cargo.toml --check
cargo clippy --manifest-path native/app/Cargo.toml --features gui --all-targets --locked --offline -- -D warnings
cargo test --manifest-path native/app/Cargo.toml --features gui --locked --offline
.venv/bin/python scripts/benchmark_native_app.py --frames 12 --repeats 3 --output /tmp/native-replay.json
```

Offline replay compares evolving colour values and GRB packets against the
preserved Python implementation. It excludes capture, USB and optical timing.
Live probes are separate and drive the connected strip:

```bash
native/app/target/release/nanoleaf-native --capture-probe /path/to/config.toml 5
native/app/target/release/nanoleaf-native --live-probe /path/to/config.toml 8
.venv/bin/python scripts/profile_native_lifecycle.py --output /tmp/native-lifecycle.json
```

Capture probe has no USB output. Live probe limits controller brightness to 10,
restores power/brightness and verifies their readback, and fails if no frames were
acknowledged or restoration cannot be verified. Lifecycle profiling adds Stop,
exclusive preview and restart with real USB; it does not modify saved settings.
Measurements exclude emitted-light latency, colourimeter accuracy, total system
power, compositor/GPU cost and the separate settings process.

Frameworks: [eframe/egui](https://docs.rs/eframe/0.36.2/eframe/),
[ksni](https://docs.rs/ksni/0.3.6/ksni/),
[zbus](https://docs.rs/zbus/5.19.0/zbus/),
[hidapi](https://docs.rs/hidapi/2.6.7/hidapi/).
The GUI's OpenGL renderer is not GPU zone sampling.

Measured-profile import/export is available in Advanced / Troubleshooting through
KDE's file chooser. Import changes the draft only; Save / Apply applies it while
keeping Settings open. Profiles retain the Python-compatible schema, float64
calibration values and private atomic exports with exact backups.

Advanced / Troubleshooting can explicitly select `xdg-portal`, using the separate
streaming helper. Auto continues to use KWin. Build the helper beside a standalone
application as `nanoleaf-native-capture`, or build its development workspace:

```sh
cargo build --release --bins --locked --manifest-path native/stream-probe/Cargo.toml
native/app/target/release/nanoleaf-native --stream-capture-probe /path/to/config.toml 8
NANOLEAF_STREAM_PARITY=1 native/app/target/release/nanoleaf-native --stream-capture-probe /path/to/config.toml 8
.venv/bin/python scripts/profile_native_lifecycle.py --stream --output /tmp/stream-lifecycle.json
```

The worker verifies a single selected monitor and the researched KWin 6.7 sRGB
contract. Denial, revocation or worker failure stops sharing and requires Start;
it does not silently switch capture interfaces. Exact sparse letterbox analysis
and box histograms share the full calibrated output pipeline. Pixel-dependent
analysis retains complete CPU pixels in the helper. [Streaming/Vulkan implementation and evidence](../../docs/RUST_STREAM_VULKAN.md)
remain experimental; the normal capture backend is unchanged.
