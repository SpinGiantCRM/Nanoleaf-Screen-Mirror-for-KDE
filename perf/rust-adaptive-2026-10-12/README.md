# Adaptive prepass evidence

- `python-profile-before.json`: initial cProfile diagnosis on unchanged commit
  `920f575`, 12 frames each at 640×360 and 2560×1440. Profiling overhead is included;
  this fixed-history diagnosis is not used as a speed benchmark.
- `results.json`: Rust 1.98 release, Python 3.14.7 / NumPy 2.5.1; nine cases,
  three repeats × 24 evolving frames per case. Full colour processing plus GRB
  message construction. Includes default accumulation/dither and privacy/profile
  variants. No capture or USB writes. No concurrent build/test during recording.
- `profile-after.json`: separate paired cProfile replays using the final evolving
  sequence harness; 12 frames per case, one repeat. Not benchmark timing evidence.
- `msrv-parity.json`: Rust 1.85 release correctness replay; not timing evidence.
- `python-production.json`: retained Python production budget check; Rust is off.
- `validation.txt`: local regression/native/lint/type/security results.

Exact RGB, algorithm/mode, temporal state and GRB TLV parity are asserted on every
paired sequence. No personal frames or config/calibration contents are recorded.
See [method, findings and limits](../../docs/RUST_ADAPTIVE_MIGRATION.md).
