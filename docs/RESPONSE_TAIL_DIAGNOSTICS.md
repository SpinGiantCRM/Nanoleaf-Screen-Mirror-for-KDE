# Measuring occasional response delays

Visible response remains the priority, followed by faithful colour, delivered
FPS and resource use. A high-speed camera is not available for the current
follow-up. That prevents a precise optical comparison; it does not prevent
software profiling or recovery tests. The precise cached-source timer remains
an opt-in experiment, because additional repeated packets could occupy USB when
a new scene arrives. This change does not enable it.

## What changed

The native service now measures every successfully acknowledged, non-predicted
mirroring update. It retains the latest **512 numeric samples per source kind**:
fresh captured frames and reprocessing of an unchanged image. Preview, cleanup
black and inferred packets do not enter these distributions. Failed transactions
are not successful response samples; their errors remain in service status.

Advanced/Troubleshooting and `--status` expose exact nearest-rank median, 95th and
99th percentile response times, with min/max in JSON. This replaces inference
from periodically polled snapshots: polling can miss a delayed update entirely
or count a repeated snapshot several times. Existing single-update fields remain
available and older service replies remain readable by the new settings client.

Each retained sample measures:

| Field | Boundary |
| --- | --- |
| `capture_ms` | Existing capture-work measurement for the selected backend |
| `processing_ms` | Existing complete colour-processing measurement |
| `queue_ms` | Parent latest-colour-slot insertion to USB transaction start |
| `usb_ms` | Serial transaction start through matching ACK return |
| `to_write_ms` | Capture/work start through final HID write returning |
| `to_ack_ms` | Capture/work start through matching ACK return |

The parent slot's insertion marker follows the retained packet on overwrite.
Queue time excludes capture and helper-to-parent IPC; it includes time occupied
by the preceding USB transaction and the small work before the next send.
`to_write_ms` includes capture, colour, IPC, parent residence and host writes.
These fields overlap: do not add their percentiles to estimate a total.
Fresh and cached work have different clock origins, so their distributions must
not be pooled. Presentation metadata age remains separate.

The windows reset on Start, successful settings Apply and USB reconnection.
Stop, Quit and failures flush the current distributions. During normal output,
summaries refresh at most once a second; every acknowledged sample is retained
regardless of refresh timing. Counts distinguish all valid observations since
the reset from the retained rolling window. Thus a percentile covers recent
packets, not necessarily a fixed wall-clock interval or the whole session.
For small windows, the 99th percentile can equal the maximum. Invalid or
non-finite timing samples are rejected and counted rather than poisoning results.

No colour values, pixels, configuration, calibration or controller identifiers
are stored in the collector. Numeric sample payload is bounded to 48 KiB across
both windows, plus container/summary overhead. There is no persistent diagnostic
log by default. Sorting happens at summary refresh, outside the timed capture
and USB transaction. No new setting, priority, thread, permission or FPS control
was added. Capture scheduling, output bytes, dithering phase and serial ACK
matching are unchanged.

## Verification and interpretation

The operator-only `response_stats_bench` records synthetic varying timings and
summarizes both windows after every 60 records. It needs neither capture nor USB.
The generated benchmark and live observations are saved under
[`perf/response-tails-2026-10-15`](../perf/response-tails-2026-10-15).

On this RTX 4080 SUPER host, one 30-second normal-mode, uncontrolled-desktop run
acknowledged 1,428 fresh updates. All entered the collector; the final 512-sample
window was independently recomputed from individual updates and matched exactly.
There were no cached samples in this particular window, so it says nothing about
the experimental idle timer's benefit. Original power/brightness were restored.

| Fresh-frame stage, final 512 acknowledged updates | Median | 95th | 99th |
| --- | ---: | ---: | ---: |
| Capture work | 2.37 ms | 14.86 ms | 15.44 ms |
| Colour processing | 0.029 ms | 0.034 ms | 0.042 ms |
| Waiting to send in parent | 8.77 ms | 17.30 ms | 18.93 ms |
| USB transaction | 20.99 ms | 21.00 ms | 21.01 ms |
| Work to final host write | 18.09 ms | 31.60 ms | 34.16 ms |
| Work to ACK | 35.18 ms | 48.64 ms | 51.20 ms |

This supports investigating capture completion and bus occupancy before colour
math tuning. The 204 overwritten prepared updates confirm the latest-only slot
is coalescing work under USB backpressure. They are not 204 additional delivered
frames. Capture substage tails included acquire, analysis, sampling and release
waits; their separate percentiles must not be added. The uncontrolled desktop and
different controller reply times preclude a causal comparison with older runs.

The synthetic collector benchmark retained 48 KiB of numeric samples and took
less than one microsecond per record, including one summary per 60 records.
That is collector overhead, not a whole-application CPU or power improvement.
The full native suite passed 103 tests (one existing operator benchmark ignored).
Separate implicit/explicit stream probes verified 321/307 exact complete-colour
outputs with Vulkan validation clean. Both recovery runs kept the tray alive
after Stop, enforced preview ownership, and stopped/reaped killed or frozen
capture children before allowing an explicit restart. Frozen-worker detection
took about 2.04 seconds. Package relocation/install/upgrade/rollback/uninstall
checks passed. This is not a new physical USB unplug or permission-revocation test.

Headless tests cover percentile ranks, eviction, source separation, reset,
invalid values, control-reply size/compatibility and overwritten packet timing.
The isolated settings layout check uses explicitly labelled synthetic status;
its screenshot is not a measurement. Live probes separately verify matching
controller power/brightness restoration and byte-identical real configuration.

These are software timings, not monitor-to-light latency, photometric colour
accuracy, panel scanout, physical reconnect or suspend verification. The latest
512 observations are a useful tail diagnostic, not a statistically established
long-term worst case. A controller ACK still does not establish when LEDs emit
light. No firmware behaviour or closed-case recovery route is inferred from it.
