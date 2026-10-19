# Streaming clock recovery — 15 October 2026

[Implementation, contracts and limits](../../docs/STREAM_CLOCK_RECOVERY.md).

`clock-summary.json` is a 120-second read-only pre-fix trace: 4,039 records, no
invalid clock differences. It did not reproduce the earlier stop; the triggering
signed difference was not logged by the old app. No source pixels/colours are saved.

`parity-summary.json` records 454 exact complete calibrated CPU/GPU comparisons
with Vulkan validation enabled. `recovery-summary.json` records both modes' live
Stop/exclusive-preview/restart and terminated/frozen-worker recovery results.
It explicitly records the private wrapper's corrected startup-state restoration.
`package-smoke.json` and `validation.json` record local package and Rust gates.

`activation.json` verifies the installed paired package and byte-identical saved
configuration, fallback/autostart preservation and retained older native version.
`daily-profile.json` records 120 seconds of uninterrupted mirroring. Its high
capture/CPU cost is an observed open profiling issue, not a claimed improvement:
74.52% of one core, 199.65 MiB summed RSS, 23.35 ms median capture, 5.68 ms USB,
29.22 ms sampling-to-ACK, approximately 37.3 acknowledged updates/s. No new
reconnect, frame overwrite or source-reuse counter increment occurred in this
window. Earlier short desktop resource results do not predict this window.

Response metrics now identify the work-clock origin and display-presentation age
separately. The lower numerical response compared with older PTS-based metrics
does not demonstrate a visible speedup. Resource measurements include parent and
capture child, excluding compositor/GPU/settings UI. No optical/system-power,
physical reconnect, external revocation, suspend, game-load or raw-HDR test is
claimed. Configuration, tokens, screenshots and screen colour samples are absent.
