# Sending a second frame before the first acknowledgement

15 October 2026. **Tested on the NL82K2; not enabled in the daily app.**

## Result

The host can finish sending another complete frame during the first frame's
reply wait. The controller did not reliably acknowledge both frames. Early
sending failed, and a later timing that passed isolated pairs failed twice
under sustained pair trains. This experiment does not justify replacing the
reliable serial transport.

| Experiment | Observation |
| --- | --- |
| Second source available immediately | Second write finished at 5.91 ms; only one ACK observed, at 18.93 ms |
| Second source available after 8 ms | Second write finished at 11.92 ms; only one ACK observed, at 18.94 ms |
| Isolated pairs, 16.67 ms source interval | Both ACKs received; grey8/black cases finished about 2 ms sooner, grey64 cases about 3 ms sooner |
| Isolated 20 ms interval control | First ACK already received before second write; no useful gain |
| Consecutive pairs, 16.67 ms interval | Serial passed 32 pairs; overlap passed one pair then missed a reply in the second pair |
| Independent consecutive-pair repeat | Same result: 32 serial pairs passed, second overlapping pair failed |

In the sustained failures, both complete writes returned by approximately 20 ms,
but only one ACK was observed, at approximately 22 ms. The experiment waited
250 ms from window start before declaring a missing reply. Sending the bytes
sooner did not establish reliable completion of both colour updates.

The two ACKs have identical command/status framing and no frame identifiers.
We cannot tell whether a frame, a reply, or both were dropped/merged, or which
colours were physically displayed. Do not infer a latest-frame mailbox or a
firmware queueing guarantee from the single reply. No optical improvement or
physical colour parity is claimed for overlap.

## Test implementation

`usb_overlap` is an operator-only Rust binary, separate from the daily app and
absent from the managed application bundle. It uses the existing exclusive
output lease and refuses competing native/Python strip owners. It reads the saved
manual zone count and channel order, sends the exact existing zone TLVs in
65/65/20-byte reports for this 48-zone strip, and never interleaves reports from
different frames. No root access, kernel changes, firmware changes, dependencies,
UI settings, FPS controls or configuration migrations were introduced.

Each window submits exactly two frames, at most two awaiting replies. The serial
variant waits for ACK 1 before writing frame 2. The overlap variant writes frame 2
when the generated second source is ready, checking for any already-readable ACK
first. Both variants count **all** replies, with a persistent TLV decoder inside
the pair. They reject malformed, failed, unrelated or excess ACKs, partial trailing
responses and uncertain short writes. They never retry an uncertain frame.

Isolated trials use a 30 ms quiet check after each completed pair. Sustained
trials remove that pause: the next pair starts as soon as both previous replies
are observed. They retain end-of-case quiet checks and a distinct-command barrier.
These are consecutive groups of two, **not** a production rolling-credit transport
or an end-to-end screen-mirroring benchmark. There is no accumulating host queue.

Pairs start their own monotonic clock. Write times are userspace write-return
observations; ACK times are userspace read observations. A reply can arrive while
a synchronous write is in progress, so its observation time can be later than
USB arrival. ACK indices assume FIFO and are not verified frame identity.

## Evidence and preservation

Seven recorded runs contain **434 completed pairs and four failed pairs**: 876
issued frames, including the eight frames in failed windows. Initial patterns
were constant grey8, grey8-to-black and black-to-grey8; later trials added grey64
and grey64-to-black. Every isolated case used serial/overlap/overlap/serial order,
with eight pairs per case. Trains requested 32 pairs per case and stopped at the
first failure. Failed windows are retained regardless of warm-up position.

The per-run binary hashes, pattern-set provenance, case medians and every pair's
numeric timings are in
[`perf/usb-overlap-2026-10-15`](../perf/usb-overlap-2026-10-15).
No captured pixels, portal tokens, saved calibration or desktop USB payloads are
stored. Frame inputs are generated neutral patterns.

The experiment requested brightness 10; this controller reported 16 after setup.
An initial baseline-only pilot incorrectly assumed readback must equal 10 and
stopped before overlap. That guard was corrected to validate the reply and
record its actual value. Its unrecorded pair timings are excluded from the seven
runs above. The generated values remain bounded at code 64; requested brightness
must not be represented as verified effective brightness.

Every recorded run quiesced the connection, verified an ordinary command reply,
sent an acknowledged black cleanup frame and restored/read back original power
and brightness, including after all four missing-ACK failures. Exact configuration,
calibration, installed binary pair, Python fallback, launchers and autostart
preferences were preserved. The tray was absent on entry and was left absent.
Its prior exit was not reproduced or attributed to this experiment.

**88 app tests pass**, including seven new overlap contracts covering exact
reports, serial versus overlapping order, fragmented/prefixed/coalesced replies,
extra/unrelated/failed/payload-embedded replies, missing ACKs, short writes, invalid
geometry and late third replies. All-target GUI Clippy with warnings denied and
formatting pass. No existing colour formula or daily transport path changed.
No new physical reconnect, permission-revocation, NL82K1 or optical test is claimed.

## Reproduce

Build `usb_overlap` in release mode from `native/app/Cargo.toml` with Rust 1.95.0
and locked dependencies. Stop mirroring and wait for its output lease to release.
Run `usb_overlap EXISTING_CONFIG 16.666667` for isolated ABBA pairs, or append
`--train` for consecutive-pair trains. Source intervals are operator experiment
inputs, not new app FPS settings. Missing replies intentionally produce a nonzero
exit after cleanup/restoration; do not interpret that as a reason to retry frames.

The initial early grey8 runs used the three-pattern pilot order; the retained
source starts with the slower grey64 case. Other intervals, including 0 and 8 ms,
are bounded to 0–40 ms. Do not interrupt hardware probes before their restoration
result. The normal app remains on one acknowledged frame at a time.
