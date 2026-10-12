# Rust core comparison evidence

See [the prototype results report](../../docs/RUST_CORE_PROTOTYPE.md) for methods,
interpretation and limits; [native verification instructions](../../native/README.md)
describe the shared fixture format and reproduction commands.

- `results.json`: three release-build comparisons per fixture, 30 samples after
  five warmups. The reference is the recovered Python box sampler at `6c2bbd5`.
  Fields include shared frame hashes, executable/compiler provenance, raw kernel
  timings, standalone process RSS/PSS, full-child CPU and numeric parity.
- `python-production.json`: current, unchanged full Python synthetic production
  benchmark; passed the existing `perf/baseline.json` budgets. It is a separate
  workload, not a native full-pipeline measurement.
- `msrv-parity.json`: Rust 1.77 release correctness check on small fixtures, 17
  protocol vectors and eight malformed-input cases. Its three-sample timings are
  verification data, not part of the performance comparison in the report.
- `validation.txt`: local Rust/Python checks and preservation evidence.

The timed comparisons ran sequentially, with execution order alternating between
languages. Raw results contain only generated synthetic pixels/derived colours,
not captures or user configuration. Calibration/config and launcher bytes were
checked without parsing or rewriting them. These core timings and memory snapshots
must not be used as the complete app's FPS, latency, memory or power results.
