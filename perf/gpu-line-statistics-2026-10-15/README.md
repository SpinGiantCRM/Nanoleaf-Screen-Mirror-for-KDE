# Integer border-line statistics evidence

2026-10-15. [Implementation and limits](../../docs/GPU_LINE_STATISTICS.md).

- `paired-summary.json`: executable hashes, AB/BA order, pooled stage timings,
  min/max/p95 and transfer counts. Three pairs, two warmups and five timed
  samples per case/executable; normal nice 0, no Vulkan validation.
- `paired-*-baseline.json` and `paired-*-candidate.json`: generated case results
  and retained samples. Baseline `0fe14c2`; upload, startup, CPU oracle, compositor,
  USB and optical output are outside timings.
- `expanded-ordered.json`: candidate binary with old-reader callbacks on the
  expanded corpus, including dark noise/speckles and threshold stripes.
- `line-oracle.json`: 88,120 exact totals, certified CPU decisions, ambiguous
  fallbacks and column-range changes, with Vulkan validation.
- `texture-oracle.json`: existing zones/regions/reader plus 1,232 line totals,
  both packed formats and every alpha code.
- `calibrated-generated.json`: 28 complete calibrated output checks; calibration
  coefficients and colour arrays are not published.
- `checks.json`: local gates, separate live parity/recovery and validation stderr.
  Live desktop colour samples remain private.
- `package-smoke.json`: relocated package, isolated user directories, rollback
  and preservation; no capture/HID.
- `activation.json`: installed pair hashes, retained previous version, exact
  config/fallback/autostart preservation and read-only doctor.

Reproduction is in the report. No captured images, portal tokens, serial numbers,
calibration values, firmware or support correspondence are included. ACK timings
are not emitted-light timings; no optical, power or gaming gain is claimed.
