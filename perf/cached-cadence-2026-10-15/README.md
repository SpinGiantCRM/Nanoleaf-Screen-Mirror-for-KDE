# Cached-source cadence experiment

2026-10-15. [Report and adoption gate](../../docs/CACHED_SOURCE_CADENCE.md).

- `loop-benchmark.json`: real SPA loop/timer, synthetic constant finishing work;
  all retained update intervals at target 30/60/144. One two-second window per
  mode/target, no display/USB. Not end-to-end latency or emitted FPS.
- `timer-api-provenance.json`: locked PipeWire source hash and timeout/timer API.
- `live-checks.json`: 561 complete live colour parity checks, both modes' worker
  failure/stall recovery and controller restoration with the experiment enabled.
- `package-smoke.json`: isolated package/rollback/preservation checks.

Default daily timing is unchanged. No optical recording, user calibration,
source images, portal tokens or firmware bytes are included. More cached USB
traffic may delay fresh output, so the higher software cadence is insufficient
for default adoption. Run `cadence-oracle` as described in the report.
