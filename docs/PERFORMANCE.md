# Native performance and benchmarking

Priorities are visible response time, faithful colour, delivered FPS, then
resources. Benchmarks must identify the full path and preserve calibration,
dithering, serial ACK transport and the user's capture backend.

For an active game, use the metadata-only [gameplay observer](DIAGNOSTICS.md).
It records actual capture, colour, latest-slot queue and USB timing, plus process
CPU/RSS, without painting fixtures or changing output. See
[2026-10-16 gameplay measurements](GAMEPLAY_PROFILING.md).

Controlled generated-event experiments and real capture are different workloads.
[Safe shorter USB updates](SHORT_UPDATES.md) include real-HID synthetic-source
response results and physical retention/reconnect evidence. The
[GPU wait experiment](GPU_WAIT_BATCHING.md) compares total completed capture work;
a smaller acquisition timer alone does not prove an improvement. Native golden
fixtures and Rust tests verify colour/protocol contracts, not live throughput.

Software work-to-write, work-to-ACK and compositor-PTS age have different clocks.
None is screen-to-emitted-light latency. Do not infer colourimeter accuracy,
whole-system power savings or sustained gaming behaviour from offline replay.
The retired Python CLI and migration benchmarks remain documented in historical
reports and Git history; they are no longer active CI gates.
