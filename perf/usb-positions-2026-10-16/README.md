# Active-zone positions — 2026-10-16

See [research and interpretation](../../docs/USB_POSITION_AND_REPEAT_RESEARCH.md).

512 acknowledged full-length frames, generated codes8/64, forward/reverse cases.
Requested controller brightness10; readback16 in every case. Every aggregate
excludes only the first two of sixteen samples uniformly. Independent final
power/brightness readback matched the original. Real config remained byte exact.
`transactions.json` keeps every timing, including warmup; `summary.json` keeps
per-pass distributions. No user calibration, serial or screen data is included.
This does not identify a UART/MCU, LED protocol or optical latency.
