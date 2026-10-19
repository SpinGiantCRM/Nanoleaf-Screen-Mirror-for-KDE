# Release capture while a USB acknowledgement is outstanding

The sole USB owner previously processed Stop/Quit only after its current frame's
ACK or 250 ms timeout. Stop then waited for cleanup black before dropping the
capture producer. A slow or missing controller reply could therefore retain
capture unnecessarily while the user was trying to stop.

The transport now offers a progress callback **after all frame reports have
been written**, between its existing reads of at most 25 ms. The service inspects
at most 16 queued controls per callback, preserving their original order. If Stop
or Quit is found, it cancels the capture producer immediately and publishes
`Stopping`. The PipeWire child is killed through its existing supervised path;
the KWin worker is cancelled through its existing flag/unpark path. Capture
shutdown/reaping is asynchronous and is not assigned a hard 25 ms completion
guarantee. Scheduling and report-write delays also lie outside that read bound.

The already-written USB frame still waits for its matching ACK or timeout. There
is no ACK abandonment, concurrent writer, blind retry or interleaved black frame.
Afterwards the queued control performs normal cleanup. The running/preview flags
keep their previous semantics until cleanup finishes, so clients cannot mistake
early cancellation for a released output lease or acknowledged black. Stop keeps
the tray alive; Quit finishes its controller-restoration path. Normal Stop also
cancels capture before its cleanup-black transaction. Status replies release the
shared-state lock before writing to a socket, keeping a client write outside the
actor's publication lock.

This changes recovery/control responsiveness, not normal colour recreation time.
It does not make healthy firmware answer faster or promise immediate physical
black when the controller is unresponsive. No settings, calibration, dithering,
geometry, scheduling priority, capture permissions or wire bytes change.

## Evidence

The operator-only `control_response_bench` uses the real transport with injected
report I/O. It requests a simulated Stop after 20 ms, then supplies either an ACK
at 200 ms or no ACK until the existing 250 ms timeout. Four trials per combination
compare cancellation after the transaction with cancellation between reads.
The JSON records callback acceptance time, not real child teardown or emitted
light. All trials retain three report writes and correct ACK/failure results.

| Injected controller behaviour | Previous cancellation callback | New callback | Transaction duration, both paths |
| --- | ---: | ---: | ---: |
| ACK after 200 ms | 179.98 ms after Stop | 4.98 ms | 200.06 ms |
| No ACK | 229.92 ms after Stop | 4.98 ms | 250.00 ms |

These are medians of four synthetic trials each, not a measured bound on real
capture-process teardown. The native suite passed 106 tests (one existing
operator benchmark ignored), with all-target Clippy and formatting clean.
Separate real capture probes verified 346 implicit and 320 explicit complete
colour outputs exactly, with Vulkan validation clean. Both 30-second lifecycle
probes preserved Stop/tray behaviour, exclusive preview, worker kill/stall
recovery and explicit restart, and verified original power/brightness restoration.
Isolated relocation/install/upgrade/rollback/uninstall checks also passed.

Headless tests verify cancellation before a delayed ACK, failure on a missing
ACK, no callback inside a partial/short write, command order and bounded control
inspection. Existing fragmented/prefixed/unrelated/failed response tests continue
to exercise the same parser. Live Stop, exclusive preview, worker kill/stall,
restart and controller restoration are separate checks; they do not simulate a
physical missing USB ACK. Measurements and verification are under
[`perf/stop-during-usb-2026-10-15`](../perf/stop-during-usb-2026-10-15).
