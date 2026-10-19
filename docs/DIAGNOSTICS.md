# Diagnostics

`nanoleaf-native --doctor` checks readiness without capture or LED output.
`nanoleaf-native --status` reports the running service's backend, acknowledged
frame counts, reconnects, per-stage timings and bounded response distributions.
Advanced / Troubleshooting displays these measurements in the UI.

For an existing mirroring session, observe without changing its settings or
focusing a window:

```bash
python3 scripts/profile_gameplay.py --seconds 120 --output /private/new-observation.jsonl
```

The file must be new. One-second snapshots contain timing and process-resource
metadata only. They are not a complete frame trace; rolling percentiles overlap
and must not be pooled as independent frames. CPU is calculated from process tick
deltas, including the isolated capture worker separately. Build jobs, changing
game scenes and GPU contention confound uncontrolled comparisons.

Capture-only and live-output probes must be bounded, use exclusive ownership,
and preserve original controller power/brightness. Live probes alter output:
do not run them against an active user session without authorisation. Their ACK
and host-write clocks are not optical latency. No colourimeter or camera result
can be inferred from software timing. Keep screen-derived HID traces private.
