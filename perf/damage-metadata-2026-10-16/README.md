# PipeWire damage metadata census — 2026-10-16

See [implementation and limits](../../docs/DAMAGE_METADATA_AUDIT.md).

Eight-second metadata-only DMA-BUF capture on the existing KDE 6.7.5 DP-1
permission. All 236 dequeued buffers carried a full-frame damage rectangle;
no missing, malformed or nonconsecutive metadata was seen. No local-damage
saving is demonstrated on this uncontrolled desktop. No screen pixels were
read, no images saved, no LED output or foreground scene was started, and the
real config remained byte-identical. This is not a colour-parity or GPU-speed
benchmark. Existing runtime sampling and all cache policies remain unchanged.

The helper hash in `summary.json` belongs to the separate operator build.
The installed daily recovery build predates this operator-only command.
