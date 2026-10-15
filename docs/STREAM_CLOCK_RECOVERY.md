# Streaming work clocks and recovery

15 October 2026, following the [GPU adoption checkpoint](STREAMING_ADOPTION.md).

## Observed stop and verified clock-contract defect

On the next live inspection the installed application was stopped with
`Screen sharing stopped: Stale capture frame. Start to request it again.`
Its tray remained alive. The original guard produced that message when the
timestamp difference was negative or at least ten seconds, without recording
which condition occurred. The exact triggering timestamp cannot be recovered.
A subsequent 120-second capture-only trace produced 4,039 records and no invalid
timestamp differences; it did **not** reproduce the original stop.

The guard nevertheless used the wrong contract for fresh streaming frames.
KWin writes its source clock into the PipeWire header; for monitor capture that
clock is the output render loop's **last presentation timestamp**. This does not
identify when the capture callback ran, how long sampling took, or how long a
prepared packet waited in a pipe. A newly rendered capture with an old display
marker is not by itself a stalled worker.
[Pinned stream implementation](https://github.com/KDE/kwin/blob/ab7df7ccb7c6af20f4b279cd6220f7cd3d2267d7/src/plugins/screencast/screencaststream.cpp),
[monitor source clock](https://github.com/KDE/kwin/blob/ab7df7ccb7c6af20f4b279cd6220f7cd3d2267d7/src/plugins/screencast/outputscreencastsource.cpp).

## Implemented correction

Capture protocol version 3 carries a required monotonic `frame_started_ns` for
both fresh capture work and cached-image processing. The worker anchors it to
the callback's start, including GPU sampling time. The parent validates that
work timestamp against the same ten-second bound. Missing, negative, future,
stale or ambiguous work packets still fail. Existing size, manual zone count,
colour, timing, version and backend-contract validation remains in place.
The parent also accepts legacy versions 1/2 with their existing guards, allowing
the older packaged pair to remain a fallback.

The original display PTS remains separate diagnostic metadata. Status and the
capture-only probe now identify `response_clock` and report
`source_presentation_age_ms` independently. Advanced UI explanations distinguish
sampling/processing-to-ACK time from display presentation age. Neither metric is
emitted-light latency. In particular, a lower new `response_ms` cannot be compared
with earlier PTS-to-ACK measurements as a physical speedup.

Temporal filters now advance on one monotonic sampling/work clock for both fresh
and cached processing. Previously, fallback work intervals during a held display
PTS could be counted again when that PTS advanced. The new clock cannot reverse
or double-count elapsed time. Sampling, calibration, transfer functions, black
handling, quantization, prediction guards and USB acknowledgements are unchanged.

No permission retry or automatic capture fallback was added. Portal closure,
connection loss, worker exit and watchdog expiry still stop mirroring; Start is
explicit. The ten-second packet check does not replace the shorter live worker
watchdog. Explicit sync remains experimental and disabled in daily use.

## Verification

- Protocol regressions accept fresh work with old/future/missing display markers
  and reject stale/future/missing work even with a fresh display marker. Legacy
  guards remain covered. Pipeline tests preserve exact calibrated integer and
  fractional colours with deliberately offset presentation metadata.
- Clock tests verify monotonic work intervals, backward/repeated input handling
  and elapsed-time partitioning. Static-source CPU-reference replay, actual ACK
  history and black-off tests continue to pass.
- The packaged helper passed 246 implicit and 208 explicit complete calibrated
  CPU/GPU comparisons, all exact, with Vulkan validation enabled. Both runs had
  zero validation stderr and exercised the new timing origin. No USB output or persisted screen
  images were used by these parity probes.
- Both packaged modes passed live Stop/tray persistence, exclusive preview,
  restart, terminated-worker recovery and frozen-worker stop/reap/explicit
  restart. Watchdog stopping was about 2.03 seconds. Controller power/brightness,
  copied configuration and fallback launcher preservation checks passed.
- The private recovery wrapper initially expected `--daemon` to stay stopped;
  the real saved `start_on_launch` setting correctly caused it to mirror. The
  wrapper was corrected to issue Stop and wait for stopped status. The subsequent
  installer precondition verified stopped state. This was a harness restoration
  error after successful app tests, not a failed recovery path.
- Local gates: 80 app tests (one normal-CI ignored operator pipe benchmark),
  12 streaming tests, formatting and warnings-denied Clippy. The relocated
  install/upgrade/rollback/autostart/live-service-exclusion/uninstall package gate
  passed. The unchanged interop tests passed in the preceding hosted checkpoint.

The corrected paired GUI/helper bundle is installed and actively mirroring using
implicit GPU streaming. The real TOML bytes, both calibration profiles, mapping,
manual count, FPS, priority and all other settings are unchanged. Older native
versions, exact backups, Python launchers and autostart preferences remain intact.

A 120-second running-app profile remained connected, with 4,459 ACKs between the
first/last snapshots, approximately 37.3 updates/s and no additional reconnects.
It also exposed much higher resource cost than the earlier short window: 74.52%
of one CPU core across parent/child, 199.65 MiB summed RSS, median capture 23.35 ms,
USB 5.68 ms and sampling-to-ACK 29.22 ms. Display-presentation age was separately
45.97 ms at the snapshot median. This uncontrolled window is not a before/after
performance comparison. The high capture cost requires further attribution;
the earlier 2% client-CPU observation must not be treated as a universal result.
The subsequent [border-readback correction](GPU_BORDER_CAPTURE.md) attributes
that cost to unnecessary full-frame analysis and replaces the common path with
exact bounded scanline batches; the shader and colour math remain unchanged.

Numerical evidence is in
[`perf/stream-clock-2026-10-15`](../perf/stream-clock-2026-10-15).
The software regressions demonstrate the repaired clock contract; they do not
prove the exact cause of the earlier unrecorded timestamp failure or long-term
reliability across suspend, monitor power changes and sustained game load. No new
physical unplug, external permission revocation, NL82K1, raw HDR, optical colour,
optical latency or system-power verification is claimed.
