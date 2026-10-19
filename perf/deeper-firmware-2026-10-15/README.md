# Firmware follow-up evidence

2026-10-15. [Report](../../docs/FIRMWARE_ENCODING_FOLLOWUP.md).

No firmware bytes, proprietary source, serial identifiers or support correspondence
are distributed. No vendor application was launched. Scripts read local pinned
inputs and print JSON. They do not access USB or the network. The separate Rust
operator probe did perform two explicitly authorized live colour comparisons;
those results are labelled separately from offline analysis.

```sh
python analyse_symbols.py --self-test
python analyse_symbols.py /PRIVATE/images
node trace_early_transport.mjs /PRIVATE/2.1.0-minified-server.js
```

`images` holds the same five stock files pinned in
`../software-reverse-engineering-2026-10-15/firmware-hypotheses.json`.
`analyse_symbols.py` includes positive and negative synthetic relation controls.
It emits aggregate repeated-block counts and conditional GF(2) constraints,
not decoded firmware or a solved checksum. Modified inputs must be rejected.

The historical transport probe expects the `minified/server.js` ASAR member
extracted as data from the installer pinned in `earliest-desktop.json`. The
Acorn-derived class ranges are in `early-class-index.json`. It evaluates only
the selected pinned class with fake HID, a stub constructor timer and a
substitute serial queue. No startup initializer or complete vendor entry point
runs. The JavaScript VM is not a security boundary for arbitrary code.

`usb_levels` is built separately with Rust 1.95.0 and locked dependencies:

```sh
cargo +1.95.0 build --manifest-path native/app/Cargo.toml --features gui --bin usb_levels --locked
native/app/target/debug/usb_levels /PATH/TO/config.toml
```

The default command prints a plan without opening HID. Adding `--run` drives
generated neutral levels for nominally 18 seconds and emits timing/restoration
JSON. Read the plan first; the saved manual zone count remains authoritative.
It needs exclusive output ownership and fails if the app owns it. It does not
change saved settings or capture the screen. Power/brightness restoration is
attempted and read back; unplug or process termination can prevent it. Do not
terminate a running probe to shorten its test. Prior LED colours are unreadable,
so cleanup leaves a black frame before restoring power/brightness.

- `early-transport.json`: three fake-device colour cases, no optical timings.
- `symbol-analysis.json`: 870 records, 32 even relations, two header constraints;
  five synthetic controls, no cipher/MCU/checksum verification.
- `live-levels.json`: two real-device runs, 1,080 frame ACKs, separate human
  observation and its unresolved black-threshold limitation. No optical latency.
- `checks.json`: regression, reproduction, negative-input and preservation checks.

The daily native binaries, calibration/configuration and Python fallback are
unchanged. This tool is excluded from the packaged application. No firmware,
reset, DFU, erase or undocumented command was sent.
