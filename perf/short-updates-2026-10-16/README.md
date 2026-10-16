# Exact short updates — 2026-10-16

See [implementation, methodology and limits](../../docs/SHORT_UPDATES.md).

`actor-benchmark.json` records all12 read/write-traced full/short/short/full runs,
three generated source families,537 matched events and5,103 exact reconstructed
whole-strip comparisons. It retains all normalized event→write/ACK values, not
raw HID data, user calibration, source timestamps or screen content. Every
measured run uses the same actor binary. The synthetic worker does not capture
or use the GPU; it must never be installed as a real helper.

`recovery.json` separates synthetic-worker/real-HID lifecycle, real-capture/USB
lifecycle and physical unplug/reconnect. First full writes, full preview, worker
failure/stall recovery and controller restoration are checked explicitly. Exact
human observation is labelled. Metadata from failed preflight/audit attempts is
retained privately and explained in the report.

`package.json`, `parity.json` and `installed.json` record final bundle verification,
capture-only CPU/GPU checks and activation/default-policy smoke separately.
The installed actor adds Advanced diagnostic labels and stricter unknown-firmware/
malformed-ACK guards to the initial benchmark build. Valid verified-controller
prefix selection, dithering and acknowledged transport are unchanged. A separate
final-binary ABBA confirmation is retained without pooling different binaries. Exact binary hashes are
retained. No optical timing, whole-system power or universal-workload claim.
