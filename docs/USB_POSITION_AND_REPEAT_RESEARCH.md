# USB active-zone cost and exact repeat suppression

16 October 2026. Follow-up to the supplied independent analysis and
[the existing USB measurements](USB_AND_BLACK_RESPONSE.md). Priority remains
visible response > faithful colour > delivered FPS > resources.

## Position versus active count: tested on the strip

The older partial-light cases illuminated a prefix, so active count and last
nonzero index were confounded. `usb_bench CONFIG --positions [--run]` now uses
complete manual-count frames with a single lit zone at first/middle/last, or
one-quarter lit at the start/end/evenly spaced. It defaults to a hardware-free
plan. The existing ordinary acknowledged transport, exclusive lease and guarded
black cleanup/controller restoration are reused. No short payload is sent.

The 48-zone NL82K2 completed **512 acknowledged frames**: codes 8 and 64,
16 transactions per case, forward and reverse passes. Only the first two samples
of each case are excluded uniformly from aggregates. Requested brightness was
10; the controller read back **16** in every case. This is not verified 10%
optical brightness. Original power/brightness were independently read back after
restoration; config/calibration and installed binaries were unchanged by the test.

Representative forward-pass median ACK waits:

| Lit arrangement | Code 8 | Code 64 |
| --- | ---: | ---: |
| None | 3.024 ms | 3.024 ms |
| One, index 0 | 3.023 ms | 3.026 ms |
| One, index 24 | 3.023 ms | 3.022 ms |
| One, index 47 | 3.022 ms | 3.022 ms |
| Twelve, first indices | 6.023 ms | 7.024 ms |
| Twelve, last indices | 6.023 ms | 7.022 ms |
| Twelve, evenly spaced | 6.023 ms | 7.023 ms |
| All 48 | 15.028 ms | 17.030 ms |

Host writes stayed approximately 3.97 ms. Reverse-pass results and all raw
transaction timings are retained in [the position evidence](../perf/usb-positions-2026-10-16/README.md).
The tested cost follows active count and drive values, rather than the last
active position. This does not locate the internal operation or measure emitted
light. It does not establish how an untested topology/colour would behave.

The proposed 115,200-baud, three-byte-per-active-zone 8N1 calculation gives
3.125/6.250/12.500 ms for 12/24/48 zones. That is a plausible numerical lead,
not a UART identification. A fixed byte-count/baud model alone does not explain
the extra brightness-dependent cost. Many per-active-zone loops or signalling
schemes could have a similar slope. MCU, LED IC/protocol and image decoder remain
unknown; no overclock or firmware write/recovery route was established.

## Exact repeat suppression: implemented as an experiment

There was no byte-identical suppression in the production actor. The new
operator flag `NANOLEAF_SUPPRESS_IDENTICAL=1` enables a conservative prototype;
it remains **off by default**, without a persisted setting or added FPS knob.

A candidate must match the last actually acknowledged complete colour frame.
With dithering enabled, every channel in every zone must produce those same
bytes in **all eight existing dither phases**. A missing/nonfinite/incorrectly
shaped precision input forces sending. With dithering disabled, exact current
byte equality suffices. Preview, inferred packets and prediction-enabled modes
bypass suppression. The controller assumption resets on controls that change
settings/session/output ownership, USB reopen and failures.

This stronger proof is necessary: one fractional zone at 64.25 can produce
identical frames at phases 0 and 1, yet needs higher output later to reach its
64.25 eight-phase average. Blind equality with phase advancement tied to ACKs can
freeze that phase indefinitely. Tests reproduce this counterexample and reject
suppression throughout its cycle. All integer neutral codes and refresh/reset,
changed-byte, unknown-precision and invalid-shape cases are covered.

Skipped work does not increment acknowledged frame count, produce a response
sample, send fake ACK feedback or advance the dither phase. A received healthy
source packet refreshes capture health; a parent timer cannot hide a stalled
helper. Repeated output is sent again after 250 ms when source work is available.
That is a conservative refresh policy, not a verified device offline timeout.
The unchanged-output count and experiment-enabled flag are explicit in status.

### Actual generated-event experiment

`usb_bench CONFIG --repeat-response [--run]` is plan-only by default. A separate
thread publishes one generated change independently of the actor's blocking USB
transaction. It compares saturated serial repeats against the same guarded
suppression, using full 48-zone raw neutral 8→64 frames. This deliberately
bypasses saved calibration for USB attribution; it does not modify that profile.
No monitor scene, captured image, prediction or firmware operation is involved.

Thirty-two trials use baseline/candidate/candidate/baseline at each of four
requested event offsets (101/137/251/263 ms), first with integer output and then
with one fractional zone as a control. The clock origin is actual event
publication, not the requested sleep deadline. Both paths measure the final real
HID write-completion timestamp and await its matching ACK. Requested brightness
10 read back 16; original controller state and exact config were restored.

| Generated source | Baseline median event→write | Candidate median | Repeated transactions, baseline→candidate |
| --- | ---: | ---: | ---: |
| Integer-stable | 16.866 ms | 5.871 ms | 84 → 4 |
| One fractional zone | 16.866 ms | 16.883 ms | 84 → 84 |

The candidate refused all fractional-control suppression. Integer changes at
101/137 ms reached host write in about 2.86–2.88 ms while the bus was idle.
At 251/263 ms the periodic refresh was in progress: candidate values were about
**3 ms slower** than their baseline comparisons. This regression is retained.
Eight observations per group mean p95/p99 equal the sample maximum; these are
not established long-term tails. This measures generated-event→host-write,
not screen/panel→light or a measured improvement to the daily application.

[All trials and aggregates](../perf/repeat-response-2026-10-16/README.md) are retained.
A separate offline census of 256 cold uniform neutral inputs through the saved
calibrated pipeline found 254 phase-invariant cases (239 nonblack); it changes
no coefficients and serializes counts only. This is a small synthetic source
family, not an eligibility estimate for real images. The live desktop lifecycle
run in fact suppressed **zero** packets: a real-workload gain is unproven.

A synthetic constant-grey **worker protocol fixture plus actual HID** separately
exercises the real actor's skip branch, Stop/tray, exclusive preview, restart,
worker termination/freeze and controller restoration. It does not capture the
screen or use Vulkan, and does not apply saved calibration to fixture values.
The fixture helper is under `tools/`; use it only beside a copied app in a private
test directory, never install it as a capture helper. Ordinary live CPU/GPU
colour parity and recovery checks are separate evidence.

## Review of the other proposed avenues

[Nanoleaf's product page](https://nanoleaf.me/products/pc-screen-mirror-lightstrip)
advertises 75 addressable LEDs for the complete product. That does not change
this user's authoritative 48-zone mapping. The generic 800 kbit/s, 24-bit RGB
calculation is 1.44 ms for 48 pixels before a latch; it is conditional background,
not identification or a measured lower bound for the Nanoleaf hardware.

The [official USB protocol](https://nanoleaf.atlassian.net/wiki/spaces/nlapid/pages/2615574530/Nanoleaf+USB+Lightstrip+Communication+Protocol)
permits variable-length RGB payloads divisible by three but does not establish
omitted-zone retention. Neither the test nor production relaxes the manual-count
encoder. The same document says offline mode retains the last displayed state,
with changed button behaviour; it gives no idle timeout that validates this
prototype's refresh interval. Button/long-idle behaviour remains an adoption gate.

[Linux usbmon](https://docs.kernel.org/usb/usbmon.html) records host-controller
requests; those records are not necessarily exact bus timing. No new root/module
or bus-wide capture access was requested. Optical timing remains unavailable;
do not ask again for the already-unavailable high-speed camera. Existing overlap
failures still rule out deploying write-only/overlapping transactions.

## Validation and delivery

The prototype code is included in the tested compatibility bundle, but is not
enabled for daily use or adopted as a performance change. Calibration,
manual count, selected monitor/backend, Target 60, prior native versions and the
Python fallback remain intact. The separately discovered KWin 6.8 compatibility
blocker and its verified repair are documented in
[KWin compatibility](KWIN_6_8_COMPATIBILITY.md).

Local gates: 120 native app tests (two operator tests separately excluded),
26 Rust 1.77 core tests, 20 streaming/operator tests, seven interop and one
GPU-layout test; warnings-denied all-target Clippy and formatting pass. The
plan-only CLI, full-length patterns, both trial orders, source/write clock checks,
dither-freeze regression and controller restoration error paths are covered.
Relocated package verification passes. No photometric colour or optical-latency
claim is made. A valid foreground static-to-change comparison, longer real-content
coverage and button/idle checks are still needed before enabling suppression.
