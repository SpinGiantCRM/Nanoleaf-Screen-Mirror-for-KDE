# Remove full-frame readback from ordinary border detection

15 October 2026. Priority: recreation time, colour reproduction, FPS, resources.

Follow-up: [uniform-dark GPU proof and USB investigation](USB_AND_BLACK_RESPONSE.md)
addresses the full-black limitation below. The numbers here describe the earlier
batched-reader implementation.

## Measured problem

The short GPU adoption sample did not describe every desktop scene. A later
120-second run used 74.52% of one CPU core across the app/capture child. Capture
took about 23.35 ms at the snapshot median, despite colour processing taking
about 0.011 ms. Fresh capture attribution isolated the cost: median image analysis
20.80 ms, sampling 0.43 ms, with a 99.1% imported-image cache hit rate.

Border detection copied four outer edges, then requested individual scanlines.
After only four additional sparse reads, it downloaded the entire image to avoid
further round trips. A dark title bar or ordinary cinema bars could therefore
trigger a full 3840×2160 readback on every frame: about 25 MB of CPU RGB analysis
data, from a roughly 33 MB full-frame RGBA GPU copy. No HDR or colour transform
was responsible for that cost. The standalone generated 4K histogram sampler
measured about 0.15–0.26 ms with 2,016 exact zone comparisons, so changing its
colour calculation was not justified.

## Implemented change

The original ordered CPU detector and float32 luma sums are unchanged. Its outer
edges remain one batch. On further requests, the reader prefetches up to 32 exact
scanlines in the detector's eight-pixel search order. It returns the same encoded
RGB bytes for each requested row/column, without downscaling, skipping requested
pixels, moving thresholds or doing approximate GPU floating-point reductions.

Horizontal scanlines share one transfer. Vertical candidates use a contiguous
band, then extract the requested columns in their original top-to-bottom order.
Copying many one-pixel columns separately would pad every GPU row to 256 bytes;
the first candidate regressed the side-border benchmark from about 11 to 21 ms.
The band implementation fixes that measured regression before adoption.

Caches are confined to one dequeued frame, bounded to one batch per axis, keyed
by exact coordinates, and reset on direction/range changes. The full-frame
fallback remains for pathological searches: after two missed row batches in one
direction or three column batches. It clears the partial caches. Import lifetime,
GPU completion, foreign ownership release and explicit timeline signaling are
unchanged. No extra capture/FPS/priority setting was added.

Typed numeric capture-stage diagnostics now reach the read-only probe, status
and Advanced UI. They separate producer wait, import, analysis, zone update,
sampling and release; they also count RGB analysis bytes and transfer batches.
They contain no pixels or configuration and keep the existing bounded IPC checks.

## Generated before/after results

RTX 4080 SUPER / NVIDIA 615.78.08; identical generated RGBA8 textures, same release
compiler and sampling implementation. Three alternating AB/BA executable pairs,
two warm-ups and five timed runs per case/executable. Upload, startup and the CPU
oracle are outside the timed window. Each pooled median has 15 timed samples:

| 4K detector case | Before | Batched reader |
| --- | ---: | ---: |
| Bright full frame | 0.13 ms | 0.13 ms |
| Thin horizontal bars | 9.75 ms | 0.53 ms |
| Cinema bars | 10.00 ms | 1.10 ms |
| Side borders | 10.80 ms | 4.45 ms |
| Completely black | 19.75 ms | 19.97 ms |
| Near the detection threshold | 10.24 ms | 0.50 ms |
| Transparent border with hidden RGB | 11.12 ms | 0.50 ms |

These are detector timings, not capture-to-light latency. The full black case
retains its costly fallback; no speedup is claimed there. Min/max samples and
exact pooled medians are in the evidence. RGB analysis data falls from 24,965,280
to 773,280 bytes for thin bars, to 1,510,560 for cinema bars, and from 24,945,120
to 9,717,120 for side borders. Those counters describe CPU RGB bytes, not padded
RGBA transfer traffic or USB bytes.

All **588** bounds comparisons matched the ordered CPU detector, across odd-size
641×359 and 4K input, bright/black, thin/cinema/side borders, threshold-adjacent
colours and zero-alpha pixels with hidden RGB. The final hardware reader oracle
also passed 144 arbitrary row/column/range byte comparisons, plus the existing
zone/updated-zone/region/batched-region comparisons, with Vulkan validation and
no validation stderr. This covers direction reversal and changed column ranges.

The final packaged worker passed **667 exact complete calibrated CPU/GPU frame
comparisons** (385 implicit, 282 explicit), both with Vulkan validation and no
validation stderr. Both modes passed Stop/tray persistence, exclusive preview,
restart, terminated/frozen-worker stop/reap and explicit recovery, plus controller,
configuration and fallback preservation. Local app/stream/interop gates and the
relocated package checks pass. Daily capture remains implicit; explicit sync
is experimental. Config bytes, calibration profiles, mapping, monitor, manual
48-zone count, FPS and priority are unchanged; older native/Python fallbacks remain.

## Running application check

A 120-second desktop window with the installed optimized pair stayed active:
5,746 ACKs between first/last snapshots, approximately 48.1 updates/s, 3.49% of
one CPU core across parent/child, 204.08 MiB summed RSS and 171.55 MiB summed PSS.
Capture/colour/USB snapshot medians were 1.34/0.017/21.00 ms; work-to-ACK was
30.83 ms. No additional reconnect occurred; two source-reuse ACKs and 688 bounded
latest-frame overwrites were recorded. Those overwrites are not an accumulating
queue, and ACK cadence is not fresh captured FPS.

This scene needed only the four outer edges (36,000 RGB analysis bytes at the
snapshot median), unlike the earlier full-readback scene. The two desktop windows
are not a controlled CPU/latency comparison: content changed and USB replies
changed from about 5.7 to 21 ms. Total work-to-ACK did **not** improve in those
windows (29.22 versus 30.83 ms). Do not turn the independently verified detector
speedup into a claim about optical latency or a universal resource reduction.
The generated identical-input comparisons establish the border-path improvement;
the running check establishes current operation and its remaining USB cost.
No resident-memory saving is claimed.

## Reproduction and limits

`texture-oracle --sampling-benchmark` isolates the existing colour sampler.
`texture-oracle --content-benchmark` exercises the actual reader and CPU detector
on generated textures, with an independent CPU pixel oracle. The normal hardware
oracle also covers arbitrary reader access. These use no capture permission or
USB output; stop competing capture before an uncontended run. Standard headless
CI runs the pure scanline boundary and IPC diagnostic validation tests; GPU tests
are hardware evidence, not claimed as hosted GPU execution.

See [`perf/gpu-border-capture-2026-10-15`](../perf/gpu-border-capture-2026-10-15).
Live desktop resource windows vary with content and USB timing. They do not
establish optical response, power or sustained gaming performance. Capture is
still display-referred SDR; no raw HDR, new physical reconnect/revocation,
suspend or additional NL82K1 verification is claimed.
