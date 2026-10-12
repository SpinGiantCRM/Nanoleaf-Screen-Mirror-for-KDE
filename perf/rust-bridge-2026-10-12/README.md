# In-process SDR bridge evidence

- `results.json`: stable Rust 1.98 release comparison, Python 3.14.7,
  three runs × 30 iterations × seven cases, 48 zones.
- `msrv-parity.json`: Rust 1.85 release correctness replay, not performance evidence.
- `validation.txt`: local regression, lint/type/security and native gate results.

The runtime does not load this extension by default. No config/calibration writes,
capture or USB output occurred. No build/test was run concurrently with the
recorded stable timing comparison. Report and interpretation:
[Rust sampler bridge](../../docs/RUST_SAMPLER_BRIDGE.md).
