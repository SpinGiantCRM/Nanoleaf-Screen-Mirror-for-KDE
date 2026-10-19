# Streaming adoption evidence — 15 October 2026

See [interpretation, implementation and reproduction](../../docs/STREAMING_ADOPTION.md).

- `daily-profile.json`: sequential 20-second uncontrolled desktop windows;
  parent plus stable capture-child process ticks and RSS/PSS; 2 Hz status samples.
  The status counter interval is about 19.5 seconds; ACK rates are approximate.
  Different timestamp origins prevent direct KWin/stream response comparison.
- `user-comparison.json`: bounded low-brightness subjective comparison and
  verified controller restoration. No optical measurement.
- `activation.json`: package hashes, exact-backup and complete parsed-TOML
  preservation checks; only `capture_backend` changed. No raw config is included.
- `sync-suite-summary.json` and `sync-timings.json`: read-only implicit/explicit/
  explicit/implicit phases. Normal callback medians exclude diagnostic readbacks.
  946 frames, no errors, 1,536 diagnostic zone comparisons. Explicit is not faster
  in this idle sample and remains disabled for daily use.
- `self-test.json`: newly created private render-node syncobj export/import,
  unsignaled bounded timeout and eight signal/wait points. No capture or USB.
- `pipeline-parity.json`: 581 exact full saved calibrated CPU/GPU frame comparisons
  with Vulkan validation enabled; no error or validation stderr.
- `recovery.json`: both modes' live Stop/exclusive preview/restart and owned-worker
  termination/freeze/recovery checks, configuration/fallback/controller restoration.
  No new physical USB reconnect or external sharing-revocation test.
- `validation.json` and `package-smoke.json`: final local test and relocated
  package gates. Hosted CI is a separate check run for each pushed revision.

Hardware: KDE 6.7.5 Wayland, RTX 4080 SUPER / NVIDIA 615.78.08, selected DP-1,
3840×2160 packed SDR BGRA, single manually configured 48-zone NL82K2. All actual
capture remains display-referred SDR even with an HDR desktop. No emitted-light,
raw-HDR, sustained game-load or system-power measurement. Numerical evidence
contains no screen images, colour samples, configuration or permission tokens.
