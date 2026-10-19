# Unchanged-source timer investigation

15 October 2026. Extends [exact GPU border optimisation](GPU_LINE_STATISTICS.md).

The installed GPU improvement is retained. A separate cached-source timer change
is implemented and tested **as an operator experiment**, not installed or enabled
by default. It needs an actual response/cadence comparison before adoption.

## Demonstrated scheduling defect

The existing capture loop passes a full `1/fps` timeout on each iteration, then
checks whether enough time elapsed since its previous output. In pinned PipeWire
0.10.1, finite loop timeouts convert with `Duration::as_millis()`, truncating the
fractional millisecond. At 60 FPS, 16.667 ms becomes 16 ms. An idle loop can wake
before the interval expires, produce nothing and wait another full interval.
Unrelated early events have the same full-period restart problem.

The inspected primary source is the locked crate's `src/loop_/mod.rs`; its exact
hash and API behaviour are recorded in `timer-api-provenance.json`. A unit test
uses the crate's actual timeout conversion and checks the remaining deadline.
This does not establish the cause of every low-FPS desktop observation.

## Prototype

`NANOLEAF_PRECISE_CACHE_TIMING=1` enables a one-shot SPA timer for the remaining
interval from the last output. It retains nanosecond duration precision and
wakes the existing loop without polling/spinning. Due work is processed without
a blocking wait; zero is explicitly handled because SPA treats a zero timer
value as disarmed. No valid cached source, invalidated format or cancellation
means no cached timer. A bounded 100 ms outer wait preserves permission and
cancellation checks. Fresh source callbacks still run immediately.

The timer is dropped before the owned loop. No new configuration field, FPS knob,
priority policy, thread, source permission, colour formula or USB command is
introduced. The backend diagnostic label identifies precise-cache mode when
active. Flags are presence-based; unset this variable for the daily policy.
The default branch retains its previous full-period wait exactly.

## Controlled actual-loop result

`cadence-oracle` uses the real PipeWire SPA loop and timer, with no server,
display, capture permission or HID. Each case runs for two seconds and includes
the same 100 microseconds of synthetic finishing work per output. Results from
this one run are software update counts, not captured or optical FPS:

| Target | Old full-period poll | Precise deadline timer |
| --- | ---: | ---: |
| 30 updates/s | 14.85 | 29.99 |
| 60 updates/s | 31.00 | 59.88 |
| 144 updates/s | 81.35 | 143.88 |

At target 60, the old median update interval is 32.261 ms and the prototype's is
16.680 ms. Wakeups are 124/120 for 62/120 outputs in their respective windows.
These measurements confirm the idle scheduling mechanism; they do not establish
an end-to-end latency reduction or overall CPU/power saving. Actual scheduler
overshoot and callback work remain variable.

## Accuracy, recovery and adoption gate

With the experimental flag enabled, complete CPU/GPU colour parity passed on
**561 real capture outputs**: 282 implicit and 279 explicit. Both modes passed
Stop/tray, exclusive preview, restart, terminated-worker recovery and frozen-
worker recovery, with original controller power/brightness readback restoration.
Frozen-worker stop was about 2.034 seconds in both modes. Validation stderr is
empty. Saved configuration and fallback launchers remain intact.

The capture workspace passes **16 tests** (15 worker/application tests and one
operator cadence test), warnings-denied all-target Clippy and formatting. These
include cached-source validity/cancellation and the existing static-source colour,
ACK-history and permission contracts. Isolated package install/upgrade/rollback/
uninstall checks pass. No new physical USB unplug, actual revocation, suspend or
optical measurement is claimed.

**Do not promote solely from the higher count.** More cached/dithered output
also occupies the serial USB bus more often. A newly changed scene may arrive
while such a transaction awaits its ACK. Visible response has higher priority
than extra packets. This tradeoff needs a measured screen/strip comparison;
unchanged-source packets are not newly captured frames or prediction.

The daily installed pair remains the verified GPU build, version
`18abd20eadafe11b3afd5041826a9af260474897b2ca4d16df3d9054a40be8b6`.
The precise-timer bundle is retained privately for the next bounded comparison.
Neither real settings nor installed defaults were changed by this experiment.
An optical comparison needs an external recording. The [local timing target](../tools/latency-pattern.html)
and [recording instructions](../tools/README.md) are prepared; no real recording
has been analysed.

## Reproduction

```sh
cargo +1.95.0 build --manifest-path native/stream-probe/Cargo.toml --release --bin cadence-oracle --locked
native/stream-probe/target/release/cadence-oracle
```

To test a built app/helper pair, set `NANOLEAF_PRECISE_CACHE_TIMING=1` only for the
bounded operator probe. Add `NANOLEAF_STREAM_PARITY=1` and Vulkan validation for
correctness, and leave them unset for performance measurements. Preserve output
ownership/controller restoration. No new timer experiment needs firmware access.

Evidence: [perf/cached-cadence-2026-10-15](../perf/cached-cadence-2026-10-15/README.md).
