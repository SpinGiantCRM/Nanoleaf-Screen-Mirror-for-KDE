# Nanoleaf improvement audit and research — 14 October 2026

Audited revision: `926668a66027169f86e4cc2cbe63abab145711f3` (merged PR #360).
Priority: **colour accuracy > latency / captured FPS > resource usage**.
Scope: one selected monitor, one manually configured NL82K1/NL82K2 strip.

## Assessment

The next useful work is improving the existing Rust application, rather than
replacing its architecture again. Its service, tray, on-demand UI, calibrated
processing, acknowledged HID transport and recoverable installer already exist.
The strongest remaining opportunities are:

1. Fix demonstrated portal response-type incompatibilities and test compatibility
   across Plasma upgrades.
2. Repair the demonstrated chroma-control transition defect, establish a physical
   colour and screen-to-light reference, then improve the
   precision, calibration and temporal parts of the colour pipeline.
3. Harden streaming for static desktops, lock/unlock, suspend, monitor changes and
   actual permission revocation before choosing it as the everyday backend.
4. Prototype explicit GPU synchronisation and batch letterbox analysis. These
   directly target work still present in the current reference-mode GPU path.
5. Measure the USB transaction stages and optimise source-to-output scheduling.
6. Extend GPU processing only for modes whose CPU pixel work remains material.
7. Investigate raw HDR in stages. The compositor-side source contract is the first
   obstacle; accepting more Rust pixel formats alone cannot solve it.

This report distinguishes defects demonstrated in software, benefits supported
by existing measurements, and experiments with uncertain outcomes. Engineering
estimates are approximate hands-on development and validation effort for someone
familiar with this code, **not delivery promises**. Hardware availability, upstream
work and long soak tests can extend calendar time. Estimates overlap where work
shares infrastructure; adding every row would overstate total effort.

## What was reviewed and verified

Reviewed the live repository rules and handoffs, prior migration/audit reports,
performance artifacts, native capture and interop boundaries, colour/sampling and
temporal code, configuration and calibration storage, service/output ownership,
USB framing/ACK handling, predictor, UI and native packaging/CI. GitHub returned
no open issues at the time of this review; that does not establish absence of bugs.

Fresh verification:

- Native application with GUI: **64 tests passed**.
- Independent core on Rust 1.77: **17 tests passed**.
- Streaming helper: **4 tests passed**.
- Offline Python/Rust replay: **18 cases × 4 frames × 3 repetitions = 216 exact
  sampled-colour, final-colour and GRB/TLV packet comparisons**.
- Two isolated `zvariant` conversion probes reproduced `IncorrectType` for
  standard portal response values consumed by the current parser.
- An isolated probe of the checked-in Rust colour function demonstrated inactive
  chroma compression on saturated primaries and the calibration clamp mismatch.
- Read-only USB descriptors show the connected NL82K2 is full-speed, with 64-byte
  interrupt IN/OUT endpoints and `bInterval=1`.
- The user's configuration hash remains
  `b470ea82ac1568cf99f4762f6914e4aa295bd3422527e9eb3ca046b52272d1a4`.

Fresh tests did not capture the desktop or drive the strip. Physical colour,
optical latency, power, sustained gaming and suspend verification were not added
in this review. Earlier physical reconnect and user colour-following confirmation
remain valuable, bounded evidence—not a substitute for those missing checks.

Evidence: [audit summary](../perf/benefit-audit-2026-10-14/summary.json),
[full replay](../perf/benefit-audit-2026-10-14/offline-replay.json),
[portal probe source](../perf/benefit-audit-2026-10-14/portal-value-probe.rs),
[portal probe results](../perf/benefit-audit-2026-10-14/portal-value-probe.txt),
[colour probe source](../perf/benefit-audit-2026-10-14/colour-contract-probe.rs),
[colour probe results](../perf/benefit-audit-2026-10-14/colour-contract-probe.txt).
The replay uses the same release executable as the final production spatial
replay. All native processing sources still match that checkpoint; only
`main.rs` and `package.rs` changed subsequently. Accumulation and dithering are
disabled equally for this comparison. Their intentionally corrected production
behaviour is covered separately by the fresh native tests. This is a warmed,
small synthetic corpus, not a gaming benchmark or broad HDR test.

## What the measurements actually say

The fresh table uses the median of three per-run medians. It excludes file loading,
capture, USB, GUI, compositor cost and emitted-light timing.

| Frame size / style | Rust colour pipeline across three sequences | Python reference across the same sequences |
|---|---:|---:|
| 2560×1440 / reference | 1.004–1.399 ms | 7.979–8.558 ms |
| 2560×1440 / ambient adaptive | 1.456–1.917 ms | 7.133–362.219 ms |
| 3840×2160 / reference | 1.938–2.573 ms | 12.019–13.020 ms |
| 3840×2160 / ambient adaptive | 2.919–4.332 ms | 12.222–982.175 ms |

These large adaptive-reference differences reflect particular synthetic scenes
and paths. They are not an advertised whole-application speedup. The current
saved reference style also bypasses adaptive appearance policies: optimising
those policies does not automatically improve this user's current mode.

Earlier installed reference-mode streaming evidence, 13 October, remains the
best complete application resource snapshot. In one 5.023-second window:

| Metric | Recorded result | Interpretation / limit |
|---|---:|---|
| Parent + capture-child CPU | 4.579% of one core | Excludes KWin, GPU and settings process; includes status instrumentation. |
| Summed RSS / PSS | 143.2 / 129.5 MiB | Process memory; not all driver/GPU allocations. RSS includes shared mappings. |
| Capture callback work | 5.583 ms median of polled status | Available-buffer interop/analysis/sampling, not entire compositor acquisition. |
| Shared colour finishing | 0.042 ms median of polled status | Already tiny; excludes final actor dithering and GPU sampling. |
| USB transaction | 20.994 ms median of polled status | Send-to-ACK duration, not LED presentation. |
| Source timestamp → software ACK | 39.694 ms median of polled status | PTS-based software response, not screen-to-light. |
| Last rolling output rate | 47.81 FPS at target 60 | 44 prepared-frame coalescings; inferred packets zero. |

Source: [final installed streaming lifecycle](../perf/rust-native-completion-2026-10-13/final-installed-stream-lifecycle.json).
These are snapshots sampled through status polling, not a dense distribution of
independent frames. Do not infer a trustworthy p99 from them. A different earlier
window recorded approximately 17 ms USB and 57.8 FPS; do not average unlike windows
or call either a fixed device maximum.

Serial transactions lasting 17–21 ms imply roughly **59–48 transactions/second**
if those durations remain steady. That is a conditional arithmetic ceiling for
this transport design, not a measured optical refresh limit. The 1 ms endpoint
interval shows that a blanket claim of a 17 ms USB polling interval would be
wrong. Firmware processing, report delivery and ACK timing must be separated.
Shaving 50% off the 0.042 ms colour-finishing stage saves only about 0.021 ms.

The older read-only GPU probe recorded approximately 0.525 ms cached DMA-BUF
sampling versus 8.674 ms CPU sampling in different windows. It establishes a
promising mechanism, but excludes USB and does not give a controlled whole-system
power or game-performance comparison.

## Prioritised opportunity register

“High” means potentially material to daily use or the stated priorities, not a
guaranteed numerical gain. Entries explicitly conditional on measurement should
not be implemented merely to increase the feature count.

| ID | Improvement | Actual benefit / confidence | Difficulty and estimated effort | Recommended position |
|---|---|---|---|---|
| A1 | Correct portal source-ID and serial parsing | Prevents demonstrated rejection of spec-compliant responses | Small, 0.5–1.5 days | First |
| A2 | KWin capability/colour-contract compatibility across upgrades | Prevents streaming being disabled by the current 6.7-only gate | Medium, 2–4 days initially; validation per supported family | First |
| A3 | Static-stream health distinct from capture activity | Prevents possible false stalls; enables correct idle reuse | Medium, 2–4 days plus soak | First investigation |
| A4 | Lock/suspend/hotplug/revocation lifecycle | Keeps daily use reliable and permissions correct | Medium, 4–8 days plus physical tests | Before default streaming |
| A5 | Complete frame-stage and tail-latency diagnostics | Makes later optimisation evidence-led | Medium, 2–4 days | First |
| C0 | Correct reversed chroma transition and add meaningful control tests | Restores a demonstrated ineffective calibration control | Small–medium, 1–3 days | First colour fix |
| C1 | Guided colour test and calibration workflow | Corrects real strip/wall response when measured | Medium, 3–6 days; instrument availability separate | Highest colour priority |
| C2 | Floating colour values until final output quantisation | Removes avoidable precision loss before calibration/dithering | Medium, 3–6 days | Early prototype |
| C3 | Measured transfer curves and validated profile ranges | Improves greys, low light and calibration fidelity | Medium–hard, 4–8 days | After C1 measurements |
| C4 | Hue-preserving mapping to measured LED gamut | Improves clipped saturated colours when a mismatch is demonstrated | Hard, 5–10 days | After device characterisation |
| C5 | Neutral/near-black handling grounded in measurements | Retains colour detail above the actual strip noise floor | Medium, 2–5 days | After C1; protect black-off |
| C6 | Linear-light final smoothing and neighbour blending | Corrects transition energy where encoded blending is used | Medium, 2–4 days | Early colour prototype |
| C7 | Time-based temporal response and dwell | Consistent colour lag at 30/60 FPS and dropped frames | Medium, 3–6 days | After C6 |
| C8 | More robust letterbox detection | Prevents false crop/remapping of genuinely dark scenes | Medium, 3–5 days | Early correctness test |
| H1 | Explicit source colour description | Prevents guessed HDR/gamut/range conversions | Medium, 3–6 days for supported SDR contract | Prerequisite to HDR |
| H2 | HDR source feasibility and capture prototype | Could retain highlights/gamut currently lost; source blocked today | Hard, 2–4 day feasibility gate; 3–8+ weeks if upstream capture work is needed | Separate research track |
| H3 | HDR → measured LED tone/gamut conversion | Correctly uses HDR source once available | Hard, 1–3 weeks after valid source and C1/C3 | After H1/H2 |
| L1 | USB transaction-stage profiling | Establishes whether 17–21 ms is host, transfer or firmware | Small–medium, 1–3 days; optional privileged bus trace separate | Early |
| L2 | Fresh-frame output pacing and backpressure | Reduces stale work/queue age without sacrificing source accuracy | Medium, 2–5 days | After A5/L1 |
| L3 | Keep service control responsive during ACK waits | Faster Stop/recovery during transport faults | Medium, 2–4 days | Reliability improvement |
| L4 | Exact unchanged-output suppression | Reduces idle USB/wakeups where temporal state has settled | Medium, 2–4 days | After A3/C7 |
| L5 | Optical latency and output-cadence validation | Exposes actual visible delay and device refresh floor | Small software, 1–3 days; external sensor/camera required | Before claiming latency gains |
| G1 | Explicit GPU acquire/release synchronisation | May remove NVIDIA compositor full waits and improve contention | Hard, 5–10 days plus driver stress tests | Highest-value Vulkan experiment |
| G2 | Batch exact letterbox readback/analysis | Removes repeated readback waits and full-frame fallback | Medium, 3–5 days | Early Vulkan optimisation |
| G3 | Damage-aware exact zone reuse | Saves work on static or locally changing content | Medium–hard, 4–7 days | After A3/G2 |
| G4 | GPU privacy and spatial weights | Keeps these configurations on GPU rather than full CPU readback | Medium–hard, 4–8 days | When those options are used |
| G5 | GPU adaptive statistics and palette candidates | Removes CPU work/full readback in expensive adaptive modes | Hard, 1–3 weeks per staged group | Benchmark current mode first |
| G6 | GPU peak/vivid/multi-moment reductions | Benefits these specific changing-image modes | Hard, 1–2 weeks per initial group | After simpler GPU paths |
| G7 | Batch ownership barriers, compute and bounded readback | Reduces CPU waits and driver overhead without adding frame queues | Hard, 4–8 days | After G1/A5 |
| G8 | Scratch/kernel allocation reuse and targeted CPU tuning | Lower memory churn/tail latency in CPU pixel policies | Small–medium, 1–3 days per measured hotspot | Low-risk targeted work |
| P1 | Paired whole-system power/game-load measurements | Avoids GPU offload increasing energy or game contention | Small tooling, 2–4 days; sustained tests separate | Gate GPU/default decisions |
| U1 | Explain active capture/profile/prediction state | Avoids misleading HDR/FPS settings and inactive controls | Small, 1–2 days | Early usability |
| U2 | Guided setup, mapping and permission recovery | Reduces manual mistakes and makes failure actionable | Medium, 3–6 days | Daily-use polish |
| U3 | Stable native release and upgrade path | Makes the improved app readily adoptable and recoverable | Medium, 2–4 days plus compatibility gates | After first reliability fixes |
| T1 | Sequence-based prediction quality evaluation | Determines whether inference actually improves visible motion | Medium, 3–6 days plus optical tests | After core latency/colour |
| T2 | Stronger prediction or interpolation | Conditional benefit; can worsen unseen cuts and USB latency | Hard, 1–3 weeks; may be rejected | Only if T1 proves need |
| Q1 | Native mutation/fuzz/recovery regression coverage | Catches malformed data and temporal/lifecycle regressions earlier | Medium, 3–6 days initially | Alongside changes |

## Confirmed compatibility issues and lifecycle risks

### A1 — portal response parsing

`native/stream-probe/src/portal.rs` uses the stream tuple's node initially, but
then attempts to assign the optional `id` property to that numeric node. It also
attempts to convert `pipewire-serial` directly into a `String`.
The current [ScreenCast specification](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html)
defines `id` as a stable **string** source identity and `pipewire-serial` as a
**uint64**. The isolated conversions both fail with `IncorrectType`.

Keep the tuple node as the older fallback, retain string identity separately,
parse the serial as `u64`, and stringify it only for PipeWire's `target.object`
property. Cover absent properties, standard types, malformed values and any
deliberately supported legacy backend representation. This is a demonstrated
interoperability defect, not evidence that the current host already emitted these
values or that all earlier successful capture tests were invalid.

### A2–A4 — daily streaming support

`application::run()` rejects every KWin version outside `6.7.*`. Removing this
check without establishing a colour contract would be unsafe. Replace it with a
tested capability/format contract, explicit metadata checks and narrowly
documented compatibility for untagged sources. Test at least the installed family
and the next target Plasma family. A version string alone is neither a permanent
support strategy nor complete proof of source colour semantics.

The source watchdog expires two seconds after the last acknowledged captured
frame. KWin's output source schedules work from repaint events. A healthy, static
desktop can therefore differ from a dead child. This is a **code-supported risk
requiring a host test**, not a reproduced daily-use failure. Add a static desktop
test with the cursor outside capture, no animated content, and no status redraw on
the captured output. Distinguish permission/connection/worker health from new
image activity; a separate health signal must not conceal a wedged GPU operation.

Lock/unlock, display power-off, resume, source geometry changes and permission
withdrawal need an explicit state policy. Never silently select a different
monitor, reacquire revoked permissions or fall back through another API after a
denial. Restore-token persistence, serial targeting and Closed handling already
exist; harden and test them rather than implementing another token store.
Allow automatic recovery only where the existing authorization and selected
source remain valid. Cover source rotation/scale/crop and reset cached geometry,
letterbox bounds, prediction and temporal state when their interpretation changes.

Acceptance: static and moving content, repeated Start/Stop, cancelled picker,
actual portal revocation, worker crash/stall, session-bus/PipeWire loss, physical
suspend/resume and monitor mode changes. Preserve the tray, manual strip count,
single output owner and calibration throughout.

## Colour work with a real accuracy benefit

### C0 — restore the intended chroma-control behaviour

`core/src/colour.rs` calls `smoothstep(0.03, 0.01, chroma)`, but the helper replaces
the negative transition width with a tiny positive denominator. For chroma above
approximately 0.03 the gate becomes 1, restoring the original Oklab `a`/`b` instead
of the compressed chroma. The same reversed-edge mistake exists in the retained
Python `_cofb_cartesian_gate()`.

The fresh isolated call to the actual Rust colour function produced identical
red, green and blue outputs with compression 0 and 0.6. A non-neutral mid-tone
also stayed unchanged. This is a demonstrated control defect. Existing Python
tests check non-increase or valid output ranges, allowing an ineffective control
to pass; copied arithmetic and parity naturally preserve it.

Implement an explicitly descending transition with a well-defined neutral
Cartesian limit. Independently test a strictly reduced chroma for suitable
saturated inputs, continuity around the transition, unaffected neutral/black,
and the intended style boosts. Keep the old arithmetic only as a named historical
oracle. This changes some configured colours intentionally, so validate existing
profile output and document the correction instead of silently claiming parity.

### C1/C3 — calibrate the device and optical path

The existing UI exposes gains, gamma, matrix and black controls and supports
profile import/export. It does not guide measurement of the strip's emitted
response. Add a bounded test sequence for neutrals, near-black, RGB primaries,
secondaries and saturated colours, with exclusive output ownership and a
cancel/restore path. Measure both direct strip output and the relevant reflected
wall light if the latter is the intended visual reference.

Separate chromaticity/white-point error, luminance response and viewing intent.
A monitor pixel and wall illumination are different optical stimuli: choose the
matching target explicitly. A camera photograph can help subjective comparison,
but is not an absolute colour calibration without characterisation. A suitable
spectrometer or corrected colorimeter is needed for defensible physical results.
[ArgyllCMS spotread](https://www.argyllcms.com/doc/spotread.html) provides emissive
measurements and reference comparisons; use it as optional measurement tooling,
not a new runtime dependency.

Keep current profiles intact. Fit a simple measured matrix and per-channel
monotonic response curves before considering a 3D LUT. Cross-validate on patches
not used in fitting and at several brightness settings. Add profile provenance,
device model/firmware, measurement method and validation error through a versioned
optional schema. Different LED phosphors, wall paint and controller brightness
can matter more than software arithmetic. No calibration can reproduce a colour
outside the physical strip's gamut or exceed its available luminance.

An additional review finding: configuration accepts finite calibration values
outside some runtime clamp ranges. The UI even tests preservation of gain 0.42
and gamma 0.7, whereas runtime applies at least 0.5 and 1.0 respectively. Storage
preservation is correct, but silently using different effective values needs a
clear validation/warning policy or a carefully extended measured model. Do not
silently rewrite old calibration to solve this discrepancy.

### C2 — quantise once, as late as practical

The sampler already computes `ZoneSample.linear_rgb`, but direct finishing
selects `sample.srgb`. Other samplers return bytes; accumulation re-encodes and
rounds; `apply_profile()` returns bytes before brightness, smoothing and final
acknowledged dithering. Fractions discarded at these stages cannot be recovered
by the final dither.

Prototype typed floating source-zone values through accumulation, calibration,
brightness and output finishing. Quantise at the HID boundary. Preserve the
current byte path as an oracle while deliberately improved production results
are evaluated against independent floating calculations. Test threshold
decisions separately: merely changing types can alter dark/palette hysteresis.
Uniform codes, black-off, neutral equality, matrix boundaries and acknowledged
dither averages must remain correct. This offers a mathematical precision gain;
the size of its **visible** benefit is unmeasured. It does not turn RGB8 capture
into raw HDR or the controller into a higher-bit device.

### C4/C5 — avoid incorrect colour loss

The colour path clamps matrix results and reconstructed RGB. For out-of-gamut
colours, independent channel clipping can alter hue. Prototype mapping against a
**measured LED gamut**, preserving feasible colours and reducing chroma only where
needed. [Oklab gamut-clipping research](https://bottosson.github.io/posts/gamutclipping/)
provides a practical starting point, not a measured model of this strip. Keep
calibrated neutral handling and compare saturated sweeps before adopting it.

The current pipeline also has dark-zone neutralisation and black/low-intensity
gates even in reference mode. Those guardrails protect usability, but can suppress
valid dim chroma. Use measurements to identify the physical noise floor and
separate necessary off behaviour from colour suppression. Do not globally weaken
the guards, add desaturation to hide errors, or optimise by discarding pixels.

### C6/C7 — make temporal processing accurate and cadence-independent

Accumulation was corrected to linear light during migration. Final smoothing and
neighbour mixing still contain encoded-space blending in `core/src/blending.rs`.
Evaluate linear-light blending there as well. The change intentionally need not
match the old Python arithmetic; compare against an independent energy reference
and measure perceived lag/flicker. Reference mode should not inherit an artistic
mixing effect simply because the old implementation did.

Accumulation alpha and several dwell/response rules are frame-based. For example,
a fixed alpha of 0.05 takes about 44.9 updates to reach 90% of a step: roughly
0.75 seconds at 60 updates/s or 1.50 seconds at 30. This is an illustrative
calculation for constant alpha, not the complete dynamic pipeline's measured
response. Use elapsed **source** time for a stable time constant, distinguish it
from ACK/prediction time, and reset on discontinuities. Reuse current settings;
do not introduce additional FPS controls. Colour-first behaviour must preserve
an immediate black cut and avoid inventing temporal detail.

### C8 — letterbox correctness

Current detection scans every eighth row/column, uses a mean encoded-luma threshold
of 4 and remaps zones when border proportions qualify. Low average brightness
does not prove a black bar: dark cinematography can create false positives.
Add labelled dark-scene/bar/subtitle fixtures, stable confidence and hysteresis,
then consider near-black occupancy and border continuity. Measure false crops
as well as speed. Changes must retain privacy handling and the existing physical
mapping rather than adding an unrelated mapping engine.

## Raw HDR: benefits, blockers and bounded investigation

The KWin D-Bus result's `type="raw"` means an **uncompressed image payload**.
It does not mean raw HDR. In the inspected KWin 6.7.5 implementation,
[screenshots](https://github.com/KDE/kwin/blob/ab7df7ccb7c6af20f4b279cd6220f7cd3d2267d7/src/plugins/screenshot/screenshot.cpp)
use an RGBA8 target; the
[monitor screencast source](https://github.com/KDE/kwin/blob/ab7df7ccb7c6af20f4b279cd6220f7cd3d2267d7/src/plugins/screencast/outputscreencastsource.cpp)
chooses ARGB8888. The colour description defaults to sRGB in
[OutputLayer](https://github.com/KDE/kwin/blob/ab7df7ccb7c6af20f4b279cd6220f7cd3d2267d7/src/core/outputlayer.h).
The fetched [development source](https://github.com/KDE/kwin/blob/db6e482628aacc4543bd6d6a78b455960cd90c5e/src/plugins/screencast/outputscreencastsource.cpp)
also chooses ARGB8888. This source inspection is narrower than a claim about all
future KWin releases or every third-party branch.

H1: represent primaries, transfer, range, matrix, alpha, reference white, luminance
intent and provenance explicitly. Reject contradictions; do not infer PQ from
10-bit packing, BT.2020 from FP16 or HDR semantics from DMA-BUF. PipeWire defines
[colour-description fields](https://docs.pipewire.org/color_8h_source.html), but
their existence does not prove that a producer supplies them correctly. Querying
the monitor's Wayland colour description also cannot establish the interpretation
of a separately produced capture buffer.

H2 feasibility sequence:

1. Enumerate actual available capture formats and metadata on the target compositor.
2. Use known SDR/HDR patterns to demonstrate that over-reference-white luminance
   and wide-gamut distinctions survive the exported source.
3. If only transformed RGB8 is exposed, stop the client-format prototype and
   document the source limitation. Do not guess or perform inverse tone mapping.
4. Investigate an upstream-compatible KWin HDR screencast extension, including
   high-precision target buffers, explicit colour metadata and mixed SDR/HDR
   composition. Keep a custom compositor build out of the everyday app dependency.
5. Only with a valid source, implement checked PQ/HLG/linear float input and a
   higher-precision zone reducer with an independent numerical reference.

| Possible source approach | Benefit and difficulty | Decision |
|---|---|---|
| Standard portal/PipeWire with HDR-capable KWin producer | Best permission model and composition visibility; may require upstream work | Preferred research direction |
| KWin screenshot extension | Potentially simpler source experiment; full-frame copies remain | Secondary prototype, not assumed available |
| Native DRM/KMS framebuffer sampling | Can access scanout buffers in some configurations; difficult authorization, overlays, modifiers, colour pipelines and NVIDIA support | Defer unless safer capture cannot meet a measured requirement |
| KWin render hook/export of zone data | Could avoid full-frame readback; tightly couples the app to compositor internals | Upstream research only after a demonstrated need |
| Per-game Vulkan/OpenGL injection | Sees application content but not necessarily final monitor composition; maintenance and integration burden | Poor fit for this one-monitor desktop app |

Reading a framebuffer is not automatically reading the final displayed picture:
overlays, cursor composition, direct scanout and display LUT/colour-pipeline
operations can differ. DRM render-node access is not permission to inspect another
application's scanout. The [DRM ownership model](https://docs.kernel.org/gpu/drm-uapi.html)
supports keeping this investigation separate from a privileged daily application.

H3: choose the intended appearance first—matching the displayed composition or
retaining scene-highlight relationships for ambient light. Decode a verified HDR
source, reduce in a defined linear domain, then map luminance and gamut to the
measured strip. HDR tone mapping and zone averaging are nonlinear operations and
their order changes the result; compare both against the stated intent.
[BT.2100](https://www.itu.int/rec/R-REC-BT.2100) and
[BT.2446](https://www.itu.int/pub/R-REP-BT.2446) provide signal and conversion
references, not a ready-made LED calibration. Use an HDR-aware metric such as
[BT.2124](https://www.itu.int/rec/R-REC-BT.2124) for HDR signal comparisons and
appropriate measured chromaticity/luminance comparisons for emitted light.

Potential benefit: more controlled handling of HDR highlights and colours that
are collapsed by SDR export. Not promised: monitor-level HDR brightness, matching
unreachable primaries, more physical LED bits, or lower latency. A custom source
may cost more than the present capture path. Keep SDR working until all gates pass.

## Vulkan and CPU optimisation: where it is best placed

### G1 — explicit synchronisation on NVIDIA

The native interop prototype explicitly accepts one-plane implicit-sync streams.
KWin 6.7.5
[screencast code](https://github.com/KDE/kwin/blob/ab7df7ccb7c6af20f4b279cd6220f7cd3d2267d7/src/plugins/screencast/screencaststream.cpp)
supports timeline sync and calls `glFinish()` on NVIDIA/software rendering when
the explicit path is unavailable. That is a concrete reason to prototype explicit
acquire/release on this host. It is not evidence of a particular number of saved
milliseconds or watts.

Negotiate PipeWire sync timeline metadata, import/wait producer fences and signal
release only after all image use completes. Handle buffer removal, renegotiation,
timeout, cancellation and GPU/device loss. Keep ownership confined to the isolated
capture child. [PipeWire buffer metadata](https://docs.pipewire.org/group__spa__buffer.html),
[sync timeline fields](https://docs.pipewire.org/structspa__meta__sync__timeline.html),
[kernel DMA-BUF rules](https://docs.kernel.org/driver-api/dma-buf.html) and
[Vulkan external semaphores](https://docs.vulkan.org/refpages/latest/refpages/source/VK_KHR_external_semaphore_fd.html)
are the relevant interfaces. A DRM syncobj timeline is not simply a Vulkan timeline
semaphore handle: the bridge and supported handle types must be proven.

Acceptance requires validation-layer runs, repeated producer buffer reuse, NVIDIA
load, no incomplete frames, CPU/GPU colour parity and paired compositor/game timing.
Do not return buffers early just to improve a benchmark.

### G2/G3 — stop paying for unchanged pixels and repeated analysis waits

`RegionReader` performs individual synchronous row/column reads for letterbox
analysis. After eight reads it falls back to a full image readback. Thus an
all-black frame or broad bars can pull the whole frame to the CPU even when GPU
box sampling is active. This is especially relevant with letterbox enabled.

First batch the required exact stripes into one transfer, then run the existing
ordered analysis on those pixels. A later GPU reduction needs threshold-boundary
tests or guarded exact fallback because changed float summation can change crop
decisions. Measure readback bytes, waits and p95 on full black, cinema bars and
dark non-bar scenes—not just colourful desktop frames.

Damage metadata can identify unchanged zones. Negotiate it and track changes
relative to the **last analysed source**, including skipped buffers; producer
buffer repair damage and changed-screen damage are not casually interchangeable.
Missing, discontinuous or invalid damage must force fresh sampling. Invalidate
for privacy/config/geometry/colour changes. Cache raw statistics or pure samples,
not final temporal output. Continue smoothing and ACK-driven dither correctly.
Static-content health (A3) is a dependency; packet suppression must not trip the
watchdog. There is no substantial benefit for a full-screen scene changing every
pixel, and no permission to approximate small colour changes.

### G4–G7 — extend GPU work incrementally

Privacy regions and non-box spatial kernels currently disqualify direct GPU
sampling. Support privacy masking in the shader before any sampling, and carry
the same exact configured geometry/weights. No thumbnail or full-image preview
should disclose masked source pixels. Batch fixed kernels or cache them by
geometry to avoid repeated CPU generation.

Adaptive classification/palette, peak/vivid, multi-moment and detail-dependent
policies still request full CPU pixels. Implement small stages in benefit order:
exact counts and mixed-content statistics; bounded candidate/bin statistics;
selected-colour linear sums; then costly percentiles/detail operations.
Independent per-channel histograms cannot reconstruct correlated RGB hue bins.
GPU float ordering, trig and quartile tie rules can alter decisions. Preserve
deterministic tie-breaking and provide an exact CPU path for ambiguous cases.
The acceptance target is the final calibrated/temporal/packet sequence, not only a
similar-looking zone mean. Corrected new colour math needs an independent oracle,
not blind byte parity with a known inaccurate formula.

The current shader uses one workgroup per zone and exact integer counts; some
large patches may benefit from tiled partial histograms and a reduction pass.
Benchmark dispatch occupancy and contention first. More GPU parallelism may hurt
an already busy game. Start by combining compatible ownership/compute/readback
submissions to reduce synchronous waits. Any asynchronous work must keep producer
buffers alive and bound outstanding work; extra frame queues can increase latency.

CPU policies still allocate patches, features, luma arrays and spatial weights.
Reuse bounded scratch, cache fixed kernels, fuse compatible passes and use
measured vectorisation where useful. Preserve reduction order where it governs
parity. Avoid spinning up a thread pool for 48 tiny colour transforms or removing
the capture-child crash boundary merely to save process overhead.

## USB, pacing and prediction

### L1–L4 — investigate the dominant live delay safely

`device::transact()` drains reports, writes the frame chunks, then waits for a
matching command ACK. For 48 zones the existing wire request takes three reports;
this review confirmed compatible 64-byte interrupt endpoints. First instrument
drain, each write, first returned report, response assembly and complete ACK.
Measure across stable, changing, black and recovery frames and different target
FPS. Read descriptors and firmware information without changing manual count.

The [hidraw API](https://docs.kernel.org/hid/hidraw.html) documents interrupt versus
control report delivery. If userspace timing cannot explain the delay, a bounded
[usbmon trace](https://docs.kernel.org/usb/usbmon.html) can distinguish submission
and completion timing. Treat privileged tracing as optional developer diagnosis;
do not add privileges to the app or log other devices' payloads.

Keep the latest-frame slot, but quantify prepared age, USB busy time and capture
work discarded before ACK. Consider target-FPS-respecting backpressure when USB
is slower. Reset/discontinuity semantics and time-based temporal processing must
be defined before deliberately reducing observed updates. Do not turn the target
setting into another queue-depth/FPS control surface.

The actor blocks during the transaction's up-to-250 ms failure window. Moving
report waiting into the existing sole-owner transport execution path, with
bounded command priority/cancellation, could make Stop/recovery more responsive.
It will not make healthy firmware answer faster. Never close or race a HID handle
from two independent writers.

For fully settled output, exact packet suppression may avoid redundant USB writes.
It must respect dither phases, evolving smoothing, preview, controller keepalive
requirements and capture health. No approximate colour epsilon should hide valid
changes. Capture/update counters must remain distinct from delivered packets.

Blindly dropping ACKs or pipelining same-command writes is not justified: responses
lack a demonstrated per-frame sequence identifier, so a late ACK can be associated
with the wrong frame. Do not trade acknowledged correctness for a headline FPS.
Changing report sizes, controller firmware or LED clock/PWM likewise needs protocol
and hardware evidence; those are not low-risk app optimisations.

### L5/T1/T2 — measure what is visible before relaxing prediction

Measure a known screen patch and corresponding LED using two optical sensors, or
a suitably controlled high-speed recording. Separate display scanout, capture,
processing, write/ACK and LED presentation. Camera rate gives a sampling interval
(240 FPS ≈ 4.17 ms); exposure, rolling shutter and timing alignment add uncertainty.
ACK may not coincide with LED update. This establishes the response floor and
whether reported output FPS corresponds to actual changes in light.

Prediction already exists, with stable-cadence and USB-headroom guards, a one-code
bound and a maximum of one inferred packet per observation. Reference/accuracy
and dithering disable it. The current configuration therefore does not gain
anything from enlarging the predictor immediately.

Evaluate coloured ramps, cuts, black transitions, flashes, reversals, variable
frame times and stalls against source ground truth. Compare time-weighted colour
error and measured source latency, not generated-packet count. Larger extrapolation
can be wrong even with an excellent fit to history; interpolation can add delay.
An extra packet can consume the time needed for the next real packet. Keep it
optional and reject stronger inference if it worsens colour or real-frame latency.
No neural frame generation or whole-screen motion estimation is warranted for
this 48-zone light-output problem without evidence.

## Usability, distribution, validation and power

U1: show “SDR capture on HDR desktop” and the active SDR calibration profile;
explain when a saved HDR profile is retained but inactive. Separate captured,
prepared, acknowledged and inferred rates. Show why prediction or direct GPU
sampling is bypassed. Report the supported capture route and relevant error,
with repair actions in Troubleshooting. Relabel the current response value as
software source/request-to-ACK, since origins differ between capture backends.

U2: add a guided four-anchor/manual-count flow using existing exclusive previews,
a mapping diagram and explicit Apply. Make unavailable monitors and permission
failures actionable. Keep saved calibration as the starting point and use a draft
for test adjustments. Main settings remain focused; diagnostics and experimental
capture belong in Advanced. Egui already supports accessibility through the
enabled integration: verify keyboard focus, labels and screen-reader operation
before considering a UI toolkit replacement.

U3: the native bundle and rollback installer exist, and CI can attach release
assets. A stable native release still needs a clear tested-support statement,
versioned release notes, the first compatibility fixes and final artifact smoke
tests. Reconcile stale migration descriptions: `native/app/README.md` still names
the already-merged development branch and describes some completed policies as
remaining work. Improve the doctor for active backend/format, udev access and recovery.
Consider an Arch package only if it solves a demonstrated installation burden;
keep one clear primary distribution route. An AArch64/Flatpak expansion is not a
priority for this target host. Checksums detect accidental alteration; signed
provenance would improve authenticity if automated upgrade is added. Reuse rollback
and verify downloaded binaries before installation.

A5/P1: add a bounded per-frame trace keyed by source sequence/timestamp and ACK
index. Record acquisition/fence/analysis/compute/readback, processing, IPC/queue age,
USB stages and output lateness, plus separate discard reasons. Add p50/p95/p99
over adequate windows, CPU attribution across all threads/children, PSS/RSS/peak
allocations and driver/GPU memory where available. Record mode, effective priority,
format, resolution, refresh and warm/cold state; exclude screen pixels and secrets.
Keep storage bounded and advanced diagnostics optional.

For power and game interference, compare the same repeatable content with mirror
off, KWin mirror and streaming mirror. Collect CPU-package/GPU energy or power
telemetry with defined limitations, wakeups and game/compositor frame-time tails.
Board telemetry is not wall-system power. A GPU context may keep the card in a
higher-power state; lower application CPU alone does not prove lower watts.
Do not start a game automatically for this review. User-selected gaming and media
sessions are later validation, with the same settings and matched runs.

Q1: retain existing Python parity where meaningful, while strengthening native
property tests, mutation tests and bounded fuzzing of HID replies, child records,
configuration migrations and capture geometry. Add process-level lifecycle tests
and native installer rollback tests from actual CI artifacts. Unit-test totals
are not feature completeness. HDR truth, calibration truth and changed temporal
math need independent references rather than circular fixtures generated from the
implementation under test. Repeat physical NL82K2 recovery; NL82K1 emitted-light
behaviour remains a separate hardware gate.

## Work to avoid unless new measurements justify it

- Another service/UI rewrite: the current design already removes Python/Qt from
  the active Rust runtime and closes the GUI when not needed.
- Moving the approximately 0.04 ms colour-finishing stage wholesale to GPU:
  interop/readback may cost more than the work removed.
- Full-frame CPU→GPU upload as the standard path: GPU-resident capture is the
  useful mechanism; copying screenshot pixels back to GPU adds work.
- Defaulting to raw DRM, broad capabilities, stolen compositor handles or a
  permanent custom KWin fork to chase an unmeasured speed target.
- Approximate low-resolution/strided sampling, global desaturation, unrestricted
  prediction or skipping valid pixels to improve CPU/FPS numbers.
- Multi-device expansion, automatic count promotion, plugin architecture and more
  FPS/priority sliders. None solves the verified one-monitor/one-strip problems.
- Assuming 240 Hz display refresh implies 240 distinct LED updates/s. Establish
  actual controller cadence first.
- Blindly applying a “better” HDR tone mapper to already transformed SDR capture.

## Recommended implementation sequence and stopping criteria

**First 4–8 engineering days:** A1, C0, the first A2 compatibility pass, A3 static
investigation, initial A5/L1 diagnostics and U1 clarity. Reproduce failures before
patching; add standard portal type tests. This removes small blockers and makes
the next decision credible.

**Next colour pass:** C1 test workflow and C2 precision prototype, then C6/C7
temporal correctness. Budget roughly 1–3 weeks depending on physical measurement
access and intentional colour changes. Gate profile/gamut/near-black adjustments
on actual device results. Preserve old profiles and code paths throughout.

**Capture/latency pass:** G2 and a G1 explicit-sync experiment, plus A4 recovery
tests and L2 pacing. Roughly 1–3 weeks for the initial validated pieces; hardware
soaks are additional. Compare whole response tails and game interference, not only
GPU dispatch time. Keep KWin available until streaming meets daily-use gates.

**Parallel in project order, not simultaneous output sessions:** H2's 2–4 day
feasibility investigation. Stop early if the accessible source lacks HDR content;
scope upstream work separately. H3 is useful only once source correctness and
measured LED characteristics exist.

**Later and conditional:** GPU adaptive/highlight ports for modes whose measured
pixel work remains expensive, damage/idle power work, stable release polish and
prediction perceptual evaluation. Do not enable several unproven changes together.

Accept a change only when it preserves manual mapping/configuration, passes
black/neutral/privacy and independent colour tests, and has evidence for its
specific benefit. Exact optimisations retain identical output sequences;
intentional accuracy corrections must improve an independent reference and have
documented bounded differences. Report sustained latency tails, adequate sample
counts, variability and resource attribution. Hardware-light claims require
hardware-light measurements.

Stop tuning a component when it is a small share of the measured cost, the gain is
within repeat-run variability, it adds complexity or power without improving the
stated priorities, or the next gain depends on changing inaccessible firmware or
compositor behaviour. Finish reliability and colour validation before pursuing
extra inferred frames. A reliable, calibrated 50–60 real updates/s can be a better
outcome than a larger reported rate with inaccurate colours or stale source frames.
