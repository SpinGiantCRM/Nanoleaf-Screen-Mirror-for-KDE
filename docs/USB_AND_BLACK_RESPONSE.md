# Black-screen response and the remaining USB delay

15 October 2026. Priority: time to colour recreation, colour reproduction, FPS,
then resources. This follows [border readback](GPU_BORDER_CAPTURE.md) and
[response timing](RESPONSE_LATENCY.md).

## What changed

The installed Rust capture worker now proves uniform dark images on the GPU
before running the expensive border search. It reads every normalized RGB8 pixel;
matching outer edges merely selects candidates. An integer OR reduction returns
256 flags (1,024 bytes). Any one-code difference prevents the shortcut. Zero-alpha
pixels normalize to black exactly as in the sampler and CPU readback.

For a constant image every row has the same mean, and every column has the same
mean. The existing detector therefore returns the full image, whichever side of
its threshold each mean falls on. Returning those same bounds avoids the CPU
search without changing the threshold, ordered floating-point sums, zone geometry,
colour processing or calibration. Only candidates with constant outer edges and
all three channel codes at most four invoke this proof. Other images use the
existing exact detector and full-readback fallback. No approximate black test,
desaturation, averaging, smoothing or prediction was added.

Three alternating reference/candidate pairs used the same release executable,
641×359 and 3840×2160 generated textures, two warmups and five timed iterations.
The reference mode bypasses only this new proof. Pooled 4K detector medians:

| Input | Existing exact reader | With GPU proof |
| --- | ---: | ---: |
| Black | 20.57 ms | 0.25 ms |
| Uniform grey, code 1 | 20.56 ms | 0.25 ms |
| Uniform grey, code 4 | 20.07 ms | 0.25 ms |
| Black with one different pixel | 19.95 ms | 20.35 ms |
| Thin bars | 0.51 ms | 0.51 ms |
| Cinema bars | 1.11 ms | 1.12 ms |
| Bright content | 0.13 ms | 0.14 ms |

Black CPU RGB analysis data falls from 25,656,480 to 36,000 bytes, plus the
1,024-byte proof flags. The counters count RGB bytes separately from flags and
GPU row-padding. These are analysis timings, excluding upload/startup and USB;
they do not establish an equally large capture-to-light improvement. Arbitrary
nonuniform dark content remains costly. The single-pixel case intentionally
retains the exact fallback and its extra proof round trip; its negative result is
included rather than presented as a universal speedup.

## USB investigation

The connected NL82K2 advertises full-speed USB, 64-byte interrupt endpoints and
1 ms IN/OUT polling intervals. The Rust HID backend writes directly to hidraw;
its read timeout uses an event-driven poll. The 25 ms read slice in the app is an
upper bound, not a mandatory sleep. Inspection of the locked hidapi 2.6.7 source
and the timing traces found no application delay being inserted after writes.

The operator-only `usb_bench` holds the same exclusive strip lease and rejects an
active native or Python owner before opening HID. It sends known dim grey/black
patterns with the unchanged authoritative manual count of 48: three reports of
65/65/20 bytes including their report IDs. Every frame waits for the matching
acknowledgement. Controller brightness is temporarily requested at 10 (a later overlap probe
reported 16 after that setup); original power
and brightness are restored and read back. Configuration is read only.

The cadence run sent 384 packets at maximum throughput and target periods of
16.67, 22.22 and 33.33 ms, with reversed repeats and constant/alternating patterns.
Slower cadence did not eliminate the content-dependent reply delay. A separate
352-packet content run used forward/reverse repeats, 16 packets per case and
excluded two warmups per case from the following pooled medians:

| Generated 48-zone payload | Host writes | Wait after writes | Total transaction |
| --- | ---: | ---: | ---: |
| All black | 3.97 ms | 3.03 ms | 7.00 ms |
| First zone grey, others black | 3.97 ms | 3.03 ms | 7.00 ms |
| 12 zones grey | 3.97 ms | 6.03 ms | 10.00 ms |
| 24 zones grey | 3.97 ms | 9.03 ms | 13.00 ms |
| 48 zones grey, code 8 | 3.97 ms | 15.03 ms | 19.00 ms |
| 48 zones grey, code 64 | 3.97 ms | 17.03 ms | 21.00 ms |

Codes 1/8/255 and individual red/green/blue channels are also recorded. An active
zone with only one nonzero channel still produced the longer reply wait; this
is not simply proportional to the number of nonzero RGB bytes. Packet lengths,
manual geometry and the host's write loop are identical throughout.

This strongly suggests a cost in the controller's processing or LED-output path,
rather than an avoidable host sleep or a fixed 20 ms USB polling interval. It
**does not prove** which firmware operation costs time, or when emitted light
changes relative to the reply. No firmware source or optical timing is available.
The reliable transport remains unchanged: no ACK skipping, overlapping unnumbered
transactions, omitted zones, new privileged USB access or colour substitutions.
A host transport rewrite has no demonstrated way to remove this reply cost.

Follow-up: [the bounded overlap experiment](USB_OVERLAP_EXPERIMENT.md) tested
sending during the reply wait. Isolated late overlap saved about 2–3 ms, but
repeated sustained trials lost an acknowledgement; it remains outside daily use.

## Better response attribution

Status and Advanced diagnostics now report `response_to_write_ms`, measured from
the capture work start to the final HID write returning. Existing `response_ms`
continues through acknowledgement. Per-report write durations expose the host's
three-write contribution. The native timestamp stays in process and is excluded
from serialized diagnostics. Neither counter measures USB arrival at the device
or visible light. This distinguishes timely sending from the strip's later reply
without mislabelling either one as optical latency.

## Correctness and recovery evidence

- 840 exact bounds checks in the paired generated benchmark, including odd sizes,
  black/near-black, one-pixel differences, borders and hidden transparent RGB.
- 690 full-image GPU uniformity checks and 690 reader candidate checks, including
  all grey codes, singleton/odd/4K sizes, both RGBA/BGRA formats, isolated one-code
  differences across the image and nonuniform hidden RGB under alpha zero.
- 500 CPU constant-colour bounds cases, including all 125 RGB combinations from
  codes 0–4 at four geometries, covering both sides of the floating threshold.
- 20 generated full calibrated CPU/GPU outputs and 870 live complete outputs
  (441 implicit, 429 explicit) matched exactly: sampled values, final colours,
  unquantized values and modes. Vulkan validation produced no stderr.
- Existing hardware reader oracle passed; both streaming modes passed Stop/tray,
  exclusive preview, restart, terminated/frozen worker stop/reap, explicit
  recovery, controller restoration and config/fallback preservation.
- 81 Rust app, 12 streaming and 4 interop tests passed; Clippy with warnings denied,
  formatting and relocated package install/upgrade/rollback/uninstall checks pass.
- After installation the user confirmed prompt black/bright transitions and
  correct colours. This is a qualitative physical observation, not a camera
  measurement or a verification of every dark video scene.

The daily backend remains implicit portal/Vulkan with normal scheduling and the
same monitor, manual count, FPS, reference colour mode, dithering, mapping and
calibration. Exact config bytes, Python fallback, previous native versions and
existing autostart preferences are preserved. Explicit sync remains experimental.
Capture remains display-referred SDR even on an HDR desktop. No new physical USB
unplug, permission revocation, suspend, NL82K1, game, power or raw-HDR test is claimed.

## Installed application profile

A 120-second uncontrolled desktop window after activation stayed healthy: 5,617
acknowledged updates, about 47.0 ACK/s, 5.78% of one core across app/capture child,
168.64 MiB summed RSS and 132.34 MiB summed PSS. Snapshot medians were capture
1.35 ms, colour 0.016 ms, USB 21.00 ms, work-to-final-write 14.40 ms and work-to-ACK
30.71 ms. Every recorded host-write endpoint preceded its ACK endpoint. There
were no additional reconnects; 68 cached-source outputs and 978 bounded latest-slot
overwrites were recorded. These are update counters, not fresh-frame or optical
measurements. Check the machine-readable summary for exact counters.

The user changed screen content during this window. It establishes ongoing
operation and useful timing attribution, not a controlled comparison with prior
CPU/RSS or latency samples. No memory saving or measured optical speedup is claimed.

## Reproduction

Build the native app's `usb_bench` operator binary and stream probe's
`texture-oracle` in release mode using Rust 1.95.0 and locked dependencies. Stop
mirroring and wait for its output lease to be released before the USB experiment;
keep the tray open and restart it afterwards. The benchmark itself refuses a
competing owner. `usb_bench EXISTING_CONFIG` runs cadence trials;
`usb_bench EXISTING_CONFIG --content` runs content trials. Do not terminate a
hardware experiment before its controller-restoration result.

`texture-oracle --content-benchmark --reference` uses the old analysis path;
`texture-oracle --content-benchmark` uses the GPU proof. Add
`--calibration EXISTING_CONFIG` instead of `--reference` to compare complete saved
calibrated outputs as well. `texture-oracle --uniform-oracle` checks the proof on
generated textures. Set `NANOLEAF_VULKAN_VALIDATE=1` for validation; experiment
flags are presence-based and should be absent from normal use. GPU checks require
actual hardware; hosted headless CI is not claimed as GPU execution.

Sanitized timings and checks are in
[`perf/usb-black-2026-10-15`](../perf/usb-black-2026-10-15). No captured pixels,
USB payloads from the desktop, portal tokens or saved calibration are included.
The next useful physical measurement is a high-frame-rate recording or light
sensor observing the screen and strip together. That can distinguish display,
capture, host-write and controller light delay; ACK timings alone cannot.
