# Response delay: findings and fast-response settings

Current user order: time to colour recreation > colour reproduction > FPS >
system performance. This supersedes the earlier colour-first ordering.

Latest substantive follow-up: [GPU streaming adoption](STREAMING_ADOPTION.md).
After the user confirmed equal/better response and stable colours, the tested
implicit Vulkan stream was enabled on this host with calibration and fallbacks
preserved. The new explicit timeline experiment remains opt-in because its idle
comparison did not demonstrate a response-time benefit.
The subsequent [stream work-clock correction](STREAM_CLOCK_RECOVERY.md) fixes a
timestamp-contract defect and makes sampling-to-ACK and display age explicit;
its changed counter origin is not evidence of an optical response improvement.

## The delay hidden by per-frame timings

The saved configuration has responsiveness 0.5 and, through its default,
temporal sample accumulation enabled. Accumulation starts at a coefficient of
0.05, with motion adaptation, then final smoothing filters that result again.
Capture-to-USB timings describe one processed update; they do not measure how
long these filters take to settle on a new colour.

The `response_bench` tool runs generated uniform SDR scene steps through the
actual pipeline with a copy of the user's calibrated configuration. A fresh,
unfiltered pipeline supplies the calibrated target. The error metric uses RGB
after undoing the configured device-gamma transfer. These are **synthetic source
clock** settling results at 60 updates/s, not wall-clock capture-to-light timings.

| Scene change | Saved settings: 90% settled | Accumulation off: 90% settled | Fast response |
| --- | ---: | ---: | --- |
| Grey 64 → 192 | 483 ms | 67 ms | First update |
| Grey 192 → 64 | 517 ms | 67 ms | First update |
| Grey 128 → 132 | 983 ms | 100 ms | First update |
| Grey 100 → 120 | 767 ms | 67 ms | First update |
| Red → blue | 533 ms | 67 ms | First update |
| Black → grey | 300 ms | 67 ms | First update |
| Grey → black | First update | First update | First update |

The model places the first update one configured frame period after the switch:
16.7 ms at 60 Hz. Fast response adds no settling across subsequent input updates;
this does not mean the LEDs emit the target light after 16.7 ms. Increasing the
responsiveness control alone leaves the accumulator active: grey rise still
takes 450 ms to reach 90%, and a small grey change takes 750 ms in this model.

## Implemented controls and safeguards

Settings now offers **Use fast response**, using existing settings only:
`smoothing=1.0` and `zone_temporal_accumulation=false`. It keeps colour style,
calibration, HDR/SDR profiles, selected monitor, mapping, manual strip count,
sampling quality, dithering, Target FPS and scheduling preferences unchanged.
The draft applies through the normal Save / Apply flow, which keeps Settings open.
The daily UI also warns when additional temporal averaging is active.

For operator use, `nanoleaf-native --fast-response [existing-config-path]` stores
the same two values through the existing transactional writer, retaining an exact
backup. It preserves inline comments, unknown options and both calibration
profiles. It does not reload, start or otherwise alter an active service; reload
or restart separately. This allows private trial configurations without changing
the live application. No new FPS, priority or queue-depth setting was introduced.

Tests establish that the recipe changes only those two controls, preserves the
calibrated target on the first changed reference-mode update at 30/60/120 Hz and
gamma 1.0/2.2, and preserves configuration comments, unknown fields and exact
backups. Reapplying it is idempotent. Existing native app tests total 74 and pass,
as do Clippy, format and isolated install/upgrade/rollback/uninstall package checks.
The underlying colour and USB algorithms are unchanged by this shortcut.

This removes intentional temporal blending; small variations can become more
visible. Other colour styles can still apply palette stabilisation or appearance
policies. The first-update guarantee is tested for the user's reference mode,
not asserted for every artistic sampling policy.

## Live comparison and what remains

A bounded low-brightness comparison used the same portal/Vulkan backend for
10 seconds with saved settings, then 20 seconds with fast response. It produced
448 and 953 acknowledged packets respectively. Median capture-to-ACK times were
41.028 and 41.068 ms, and median USB transaction times were approximately 21 ms
in both phases. The healthy capture/transport path is not where this large
settling delay was removed. These are short desktop observations, not a controlled
optical latency or FPS comparison.

Each phase verified original controller power/brightness restoration. The
original installed KWin application resumed with normal process priority, and the
real configuration/installed binary remained unchanged during the comparison.
That first comparison was missed. The subsequent assessment and daily activation
are recorded below. Actual emitted-light latency, sustained gaming cadence and
the firmware presentation/ACK relationship remain unmeasured; do not equate an
ACK timestamp with visible LED presentation.

## 15 October: confirmed response improvement and daily activation

The repeated low-brightness comparison produced 436 acknowledged packets with
saved settings (10 seconds), then 852 with fast response (20 seconds). The user
reported **“Noticeably faster; colours and stability still good.”** Both phases
verified controller power/brightness restoration; the real configuration was
unchanged during the comparison.

The harness's relative nice adjustment did not consistently preserve priority:
saved phase nice was 0, fast phase and the first restored process were 4. The
restoration check caught this; all original service threads were corrected to 0
and verified after Reload. Future launches use an absolute priority set before
execution. These uncontrolled phases are therefore a subjective usability check,
not a valid paired capture/transport performance comparison. Their different
capture-to-ACK medians must not be attributed to the two temporal controls.

After the positive observation, the tested GUI/capture bundle was installed
through the normal managed installer. The real configuration was edited through
the transactional fast-response command. A parsed comparison found exactly two
changed root keys: `smoothing` and `zone_temporal_accumulation`. Both calibration
profiles, mapping, monitor, manual count, FPS, priority, unknown options and
comments remain preserved; an exact original configuration backup is retained.
Older native versions, Python launchers and native/Python autostart settings were
retained. The installed app resumed KWin mirroring with real NL82K2 ACKs and
actual normal priority 0. The bundle's executable checksum matches the previously
tested build. Isolated install/upgrade/rollback/uninstall checks passed again.

A subsequent 20-second uncontrolled desktop profile sampled status at 2 Hz:

| Measurement | Result |
| --- | ---: |
| Acknowledged packets / rate | 895 / 44.65 updates/s |
| Capture median | 18.34 ms |
| Colour processing median | 3.52 ms |
| USB transaction median | 20.96 ms |
| Capture request to ACK median | 44.56 ms |
| Capture request to ACK snapshot p95 | 56.38 ms |
| Process CPU, percent of one core | 66.99% |
| Resident memory | 79.75 MiB |
| Dropped prepared frames / new reconnects | 2 / 0 |

These are status-snapshot distributions, not a full distribution of every frame
or controlled video/game results. CPU uses process tick deltas; the external
status sampler's CPU is excluded, although polling can affect the application.
A separate five-second attribution put approximately 65% of one core in the
capture/colour worker. Thus the daily KWin path still has meaningful CPU cost;
earlier low CPU results for portal/Vulkan do not describe this backend.

USB metadata splits its median transaction into about 2.98 ms writing three
reports and 18.03 ms waiting for the reply; draining reports takes less than
0.002 ms. This rules out the drain loop as a useful latency target in this run.
It does not identify whether firmware presents the colours before or after its
reply. Skipping ACKs or inventing colours would weaken correctness/recovery and
is not justified. The current latest-frame slot is already bounded, preventing
an unbounded queue of old scene colours. Further material improvements need
capture/pipe attribution or separately validated streaming capture; changing
more colour math would not address the dominant measured stages.

A three-second read-only KWin capture attribution ran alongside daily mirroring
(additional capture load): 113 actual captures at 3840×2160, Qt format 6.
Median reply, pipe transfer and conversion stages were 8.62, 7.04 and 7.02 ms.
This is stage attribution under concurrent load, not a clean daily-use benchmark.
The host permits an unprivileged 1 MiB pipe capacity (default 64 KiB), providing
a candidate for independent transfer tests without changing colour processing.

The opt-in `paired_4k_pipe_transfer_benchmark` exercises the production reader
with generated 4K bytes, two warm-ups and 12 alternating AB/BA pairs. Every
received byte matched. Default 64 KiB / requested 1 MiB transfer medians were
8.40 / 7.67 ms, including reader allocation. Only 7 of 12 pairs favoured the
larger pipe; paired savings ranged from −2.86 to +3.36 ms (median +1.17 ms).
This short synthetic run does not establish a useful whole-capture latency/CPU
benefit. **Production pipe capacity remains unchanged.** The ignored benchmark
is available for controlled follow-up, alongside ordinary regression tests for
short reads, complete byte preservation, truncation and stalled-pipe timeout.

Evidence: `perf/response-latency-2026-10-15/`. No optical latency, power, raw HDR,
sustained gaming or additional physical device verification is claimed.
Managed binary rollback does not revert timing settings; restore the exact
configuration backup separately if returning to the previous response behaviour.
The final app gate passes 77 tests, with the operator benchmark ignored in normal
CI; the benchmark was also explicitly run and passed all byte comparisons.
Native Clippy and format checks pass. No production reader or colour algorithms
were changed by this additional test/benchmark batch.

## Packed capture conversion follow-up

The next measured hotspot was conversion from KWin's premultiplied 32-bit image
to the RGB8 frame consumed by the colour pipeline. The old opaque path scanned
all alpha bytes, then traversed the image again to convert channels. It now
converts four pixels per block, checking that block's alpha alongside the
channel shuffle. A non-opaque block or row remainder uses the same integer
unpremultiplication, zero-alpha handling, rounding and saturation as the scalar
reference. Native-endian ARGB and byte-ordered RGBA remain distinct. Row padding
is never treated as pixels. RGB/BGR888 handling is retained, and unrecognised
formats still fail rather than being guessed. No unsafe code, new dependencies,
new capture permissions, image approximation or colour-policy changes were added.

The new independent scalar test covers all six packed format IDs, all alpha
codes, opaque and mixed frames, saturation, zero alpha, padding, multiple rows
and widths around block boundaries. The existing `decode_probe` also checks
complete generated frames against its frozen scalar reference. Four alternating
before/after executable pairs, each with 20 internal decode samples per case,
gave these pooled medians (allocation included):

| Generated frame | Previous conversion | Packed conversion |
| --- | ---: | ---: |
| 2560×1440, opaque | 2.42 ms | 2.00 ms |
| 3840×2160, opaque | 6.01 ms | 4.91 ms |
| 2560×1440, alpha 128 | 9.72 ms | 9.79 ms |
| 3840×2160, alpha 128 | 21.88 ms | 22.24 ms |

The opaque 4K stage improves about 18%; uniformly translucent frames are about
1–2% slower in this short run. Every output byte matched. These figures describe
generated conversion work, not whole capture or emitted-light response. Both
executables ran at actual nice 0 while ordinary mirroring continued.

The complete GUI/helper bundle passed 78 app tests, Clippy, format and isolated
package smoke tests before installation. A brief real KWin check then compared
the previous and new installed builds, with the exact same fast-response config:

| Short uncontrolled desktop observation | Before | After |
| --- | ---: | ---: |
| Daily acknowledged updates/s (8 s each) | 45.66 | 45.53 |
| Daily process CPU, percent of one core | 68.61% | 62.87% |
| Daily capture request to ACK median | 52.28 ms | 49.00 ms |
| Concurrent capture-probe conversion median (3 s each) | 6.19 ms | 5.37 ms |

The conversion-stage direction agrees with the synthetic benchmark. Other
capture/processing timings varied; the whole-app CPU/response difference cannot
be assigned entirely to this change. The stage saving is modest, output cadence
is still limited by roughly 22 ms USB transactions, and no optical gain is
claimed. Faster capture overwrote more prepared frames (19 → 51 in these short
daily samples), as expected with the existing latest-frame slot; no additional
USB reconnect occurred. This counter measures coalesced prepared work, not failed
USB writes. Point-in-time RSS differed between the long-running previous process
and fresh new process; peak RSS was about 80 MiB in both, so no memory saving is
claimed.

The new build remains installed and mirroring KWin at normal priority 0. The
configuration is byte-identical to the confirmed fast-response configuration,
including calibration, both profiles, mapping, unknown fields and comments.
The previous fast-response Rust build, older Rust version, Python fallback and
autostart preferences are retained. This binary-only upgrade needs no settings
rollback when switching back to the preceding fast-response build.

Evidence: `perf/packed-capture-2026-10-15/`. To reproduce the generated work, build
`decode_probe` with Rust 1.95.0, `--locked --release`, at `14a5015` and this change
in separate checkouts; alternate their executable order and compare `decode_ms`
for identical dimensions/alpha. Its internal `reference_ms` is the older scalar
oracle, not the immediately preceding production baseline. The private live
harness and metadata are retained under the local test state directory; screen
pixels were never saved.
