# Native application work in progress

The replacement application is entirely Rust, including its settings UI. It is
being built incrementally on `codex/full-rust-rewrite`. It is not ready to replace
normal mirroring. The recovered Python application remains installed and is the
reference/fallback until full colour/capture/output/lifecycle gates pass.

The priority order is colour accuracy, latency/FPS, then resource usage. Predictive
or perceived-FPS features follow core refinement. No optimisation may bypass
colour-domain/metadata validation or silently change a measured calibration.

Current modules:

- `config`: version-aware, read-only startup import of existing TOML and LED profiles;
  comment/unknown-key-preserving edits, exact backups, atomic/fsynced writes, stale
  save rejection and the same advisory lock as the Python config manager.
- `geometry`: the single-strip edge layout and corner-anchor mapping; shared
  Python/Rust geometry golden tests are still required before enabling output.
- `capture`: KWin ScreenShot2 through Rust zbus, bounded descriptor reads and
  explicit raw-format decoding. Unsupported colour formats fail instead of
  being silently interpreted as bytes. Portal/streaming/native DRM remain pending.
- `device`: Rust hidraw-native hidapi for NL82K1/NL82K2, manual count authority,
  TLV/report framing and acknowledged writes. Recovery/ownership and hardware
  validation remain pending. No device is opened by the preflight/settings modes.
- `ui`: Rust eframe/egui on Wayland, opened separately from the eventual tray service.
  Settings Save/Apply keeps the window open. UI has been launched in an isolated
  Wayland session using a copied configuration, not the real settings file.
- `nanoleaf-core::colour`: measured LED calibration/style/Oklab transforms;
  8,288 oracle colours currently match the Python reference exactly on this host.

Dependencies are locked. Native app requires Rust 1.95 for the GUI framework;
the standalone colour/protocol core still supports Rust 1.77. UI uses `glow`,
not a browser runtime. Frameworks: [eframe](https://docs.rs/eframe/0.36.2/eframe/),
[ksni](https://docs.rs/ksni/0.3.6/ksni/),
[zbus](https://docs.rs/zbus/5.19.0/zbus/),
[hidapi Linux native backend](https://docs.rs/hidapi/2.6.7/hidapi/).

```bash
cargo test --manifest-path native/app/Cargo.toml --locked --offline
cargo run --manifest-path native/app/Cargo.toml -- --preflight /path/to/copied-config.toml
cargo run --manifest-path native/app/Cargo.toml --features gui -- --settings /path/to/copied-config.toml
```

Neither command starts capture or LED output. The real config has only been read
for preflight and copied into ignored local test storage. Normal install/autostart
and launchers are unchanged. Do not interpret UI/preflight measurements as complete
app performance. Full native pipeline, tray/service control, setup/calibration UI,
HDR/SDR metadata, reconnect and lifecycle validation must precede adoption.
