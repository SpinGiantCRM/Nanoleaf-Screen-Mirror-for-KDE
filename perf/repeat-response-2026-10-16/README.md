# Exact repeat-suppression prototype — 2026-10-16

See [implementation, results and adoption limits](../../docs/USB_POSITION_AND_REPEAT_RESEARCH.md).

`actual-usb.json` retains all32 generated-event trials: two baseline/candidate
comparisons at each of four offsets, for integer and fractional-control inputs.
The same serial acknowledged HID path and actual write-completion timestamp
were used. No capture or optical timing. Original controller state restored,
independently read back, configuration unchanged. Requested brightness10 read16.

Integer median event-to-host-write16.866→5.871ms; repeated unchanged transactions
84→4. At offsets near periodic refresh, individual candidate results were about
3ms slower. Fractional control refused all suppression and retained84 repeated
transactions per group. Eight samples per group do not establish stable tails.

`eligibility.json` is a separate offline256-source census through saved colour
settings, not a real-content speed test. It outputs counts without calibration
coefficients or RGB. `package.json` verifies the separate experimental bundle;
that initial experimental bundle was not installed. The later tested KWin 6.8
compatibility bundle includes prototype code, with suppression OFF for daily use.

`actor-fixture.json` records separate real-actor skip-branch coverage using a
constant-grey synthetic protocol worker and actual HID. It exercises Stop,
preview, restart, killed/frozen-worker recovery and restoration. No capture or
Vulkan occurs in this fixture; never install its helper.
