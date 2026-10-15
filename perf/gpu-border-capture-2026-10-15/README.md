# Exact GPU border-analysis readback — 15 October 2026

[Interpretation, reproduction and limits](../../docs/GPU_BORDER_CAPTURE.md).

- `before-live-stages.json`: actual configured capture, 346 frames; median
  analysis 20.80 ms / 24,965,280 CPU RGB bytes, sampling 0.43 ms; cache hits 99.1%.
- `sampling-oracle.json`: generated 4K sampler cases, 2,016 exact zone comparisons.
  This isolated the fast shader/readback/reduction from expensive border analysis.
- `0-before.json` through `5-band.json`: three AB/BA executable pairs. Each has
  odd-size and 4K generated patterns, two excluded warm-ups and five timed runs.
  All 588 bounds comparisons including warm-ups match the ordered CPU detector.
- `summary.json`: pooled 15-sample distributions per case/variant. Completely black
  remains approximately 20 ms; no universal speedup is asserted. CPU RGB byte
  counts differ from padded RGBA GPU transfers and USB traffic.
- `rejected-pilot.json`: individually padded column copies regressed side borders;
  they were replaced by contiguous bands before adoption. Preserve this negative
  result when explaining why the row and column paths differ.
- `reader-oracle.json`: byte-exact arbitrary row/column access, direction/range
  changes, both RGBA/BGRA, alpha-zero hidden RGB, existing zone/region contracts;
  Vulkan validation enabled with no validation stderr.
- `pipeline-parity.json`: 667 exact complete calibrated CPU/GPU frames in implicit
  and explicit modes, with Vulkan validation enabled and no validation stderr.
- `recovery.json`: both modes' live Stop/tray persistence, exclusive preview,
  restart, owned-worker termination/freeze and explicit recovery; controller and
  configuration/fallback preservation. No new physical unplug/revocation test.
- `activation.json` and `package-smoke.json`: exact installed pair, byte-identical
  real configuration, preserved fallback/autostart and retained older version;
  isolated relocated package install/upgrade/rollback/service-exclusion checks.
- `daily-profile.json`: 120 seconds of current mirroring and summed client CPU/
  RSS/PSS. Content and USB timing differ from the earlier desktop window; total
  work-to-ACK did not improve in those windows. No controlled whole-app/optical
  or memory-saving claim follows from them.

Host: KDE 6.7.5 Wayland, RTX 4080 SUPER / NVIDIA 615.78.08; real capture DP-1
3840×2160 display-referred SDR, one manually configured 48-zone NL82K2. Generated
benchmarks require no capture permission or USB output. No screenshots, captured
colour samples, config or permission tokens are committed. No optical latency,
emitted-colour metrology, system power, game-load, suspend, raw HDR or additional
physical device verification is claimed.
