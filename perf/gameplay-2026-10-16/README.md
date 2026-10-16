# Actual gameplay observations — 2026-10-16

`summary.json` contains normalised timing/count/resource evidence only. Private
source JSONL is kept locally; no screen pixels, RGB, HID payloads, serial numbers
or calibration values are published. SHA256 values identify retained private
source records, not screen images.

Eight 60-second uncontrolled-gameplay windows compare GPU waits and full versus
shorter USB output. The same installed reference app/helper and saved Target60
configuration were used. Changing scenes, partial build load and differing
inherited nice snapshots prevent causal performance/adoption claims. Resource
figures are CPU percentages of one logical core and RSS, excluding compositor,
driver and game. Rolling last-512 response windows are not pooled.

See [report](../../docs/GAMEPLAY_PROFILING.md). Final installed bundle and one-minute
live smoke are identified separately. Python runtime retirement preserves native
fixtures, configuration and previous immutable native rollback versions. The second Pacman-owned installation and an unowned leftover privileged helper
have also been removed and their absence verified.
