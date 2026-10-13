# Native application completion and recovery evidence — 2026-10-13

The application runtime is now Rust: service, capture supervision, processing,
HID transport, KDE tray and on-demand settings/calibration UI. Prediction and
independent native packaging are implemented. The Python application remains
installed as the working fallback and regression reference. This is a locally
validated native build, not a published release or a claim of universal hardware
support.

## Colour comes first

Reference/natural and explicit accuracy mode bypass prediction and optional
appearance policies. Complete pixel coverage, linear-light reduction, manual
physical mapping, measured calibration, dark/neutral guards and acknowledged
output remain authoritative. Neither capture FPS nor LED count is inferred from
prediction or controller diagnostics.

Temporal accumulation now stores linear-light values, then encodes its output.
Blending encoded sRGB loses energy: the first 5% red-to-green step should be
approximately `[249,63,0]`, whereas the old encoded blend is `[242,13,0]`.
A deterministic test asserts the linear-energy result, separately from the old
oracle. The user’s accumulation setting is retained; no filter is forced on.

A cut to a completely black source zone now resets its accumulation and bypasses
smoothing before output quantization. That prevents the old transition glow. The
previous Python arithmetic, including encoded-space accumulation, is retained in an explicitly named **offline oracle**
constructor/manifest option. It is not selected by the service or capture worker.
Twelve-frame Python parity uses that oracle explicitly; independent production
black-transition tests assert immediate off. Production spatial/colour comparisons
disable accumulation equally on both sides so intentional temporal corrections
are not misreported as regressions. This distinction is recorded
in the benchmark JSON, rather than hiding intentional colour corrections.

Temporal dithering now chooses its phase in the USB actor from successful ACK
count, using the final unquantized colour vector. Coalesced prepared frames can
therefore neither skip nor repeat the strip’s fractional duty-cycle phases.
The bounded helper protocol validates that vector’s size, range and finiteness.
An eight-ACK test with seven intervening prepared-frame drops per packet retains
128.25 exactly on all neutral channels and keeps black off.

The SDR profile's saved dark-stabilization thresholds are now applied instead of
hard-coded defaults. Existing calibration remains stored at float64 precision;
no gains, matrix, anchors or HDR profile were reset. Source colour semantics remain
explicit: KWin screenshots and the validated KWin 6.7 portal path provide SDR,
display-referred sRGB even on the HDR desktop. Applying PQ decoding or a second
panel gamut conversion would be incorrect. Raw PQ/HLG/FP16 and unverified portal
colour metadata still fail explicitly.

## Remaining policies

| Policy | Native behavior and evidence |
|---|---|
| Multi-moment | Selects a dominant coarse bin when appropriate, then computes the linear mean of **actual pixels in that bin**. The old bin-centre output could invent channels: a dominant `[255,10,2]` patch becomes `[240,16,16]`. The corrected sampler preserves the original dominant pixel colour. Neutral mixtures use a linear mean. |
| Wavelet compatibility setting | Replaces the old channel-range-as-colour formula with a bounded, linear-light detail-weighted mean. It is not advertised as a genuine wavelet transform. Uniform grey/primary patches and black remain exact. |
| Virtual oversampling | Retains the saved setting but requests full pixel coverage of existing configured zones. The old encoded-space virtual perimeter interpolation is retired. Native full-pixel sampling already covers the region; no virtual LED count, new mapping or privacy bypass is introduced. |
| Scene adaptation | Adjusts temporal responsiveness for changing scenes. It cannot override calibration, colour style, physical mapping or target FPS. |
| Reference/accuracy | Bypasses appearance policies; remains eligible for exact direct GPU histograms when its other pixel-policy conditions permit. |

Tests cover every uniform grey code and primary intensity for the new samplers,
actual-bin colour correctness, reference bypass, privacy before sampling, and
unchanged manual output count. These corrected policies deliberately do not
claim parity with the old inaccurate formulas. Existing palette, peak and vivid
policy fixtures and exact-cache tests remain in the suite.

## Conservative 4D prediction

4D now provides opt-in cadence polish rather than claiming additional captured
frames. It requires three steady observations, stable cadence and modest motion.
It emits at most one additional packet per observed frame, within one encoded
colour code of the last observed output. It preserves zero channels and encoded
neutrals, skips low light/dimming, and suppresses cuts, reversals, jitter and
stale input. Stop, preview, reload, capture failures and USB recovery reset it.

Reference/accuracy, natural style, zero strength and temporal dithering disable
prediction. Dither duty cycles are therefore not disturbed. The existing target
FPS and prediction-strength setting are reused; there is no additional FPS or
priority control. A rolling maximum of the last 32 successful USB transaction
times supplies a conservative headroom check: an inferred write must leave time
for the next real source packet. Busy/unknown USB suppresses it.

Only captured output enters prediction's observation history. Integer output
hold is bypassed when prediction is eligible so inferred ACKs cannot steer later
captured colours through quantization hysteresis. Actual ACK history still
records what the device received. A complete pipeline test verifies identical
future source outputs with and without intervening inferred ACK colours.
`predicted_frames` is separate from the total acknowledged packet count; their
difference is the observed packet count. Reported output FPS includes inferred
packets when present and must not be described as captured FPS.

Synthetic evidence in `final-prediction-benchmark.json` uses 100,000 independent
48-zone ramps: three observations plus one prediction took about 0.572 µs per
iteration in that build. At a 33 ms source cadence, the analytical colour after
17 ms is 106.06; holding 104 has a 2.06-code error, while predicting 105 has a
1.06-code error. This is an analytical example with no USB timing or optical
measurement. The one-code bound is relative to the last measured output, **not
a guarantee about unseen future content**. A sudden unseen reversal can still
make a prediction wrong. No gaming or perceived-FPS improvement is claimed from
that example; the default reference configuration produces zero inferred packets.

## Recovery and hardware checks

| Check | Result and limit |
|---|---|
| Real NL82K2 USB unplug/replug | USB loss detected, two successful strip opens, 936 acknowledged frames in the bounded test, controller power/brightness restoration verified. The user confirmed “Reconnected; colours resumed.” This is one physical reconnect, not a suspend or multi-model stress test. |
| Probe reconnect limit | Low test brightness is reapplied after every strip reopen. Original controller settings are captured once and restored with readback verification. |
| Owned streaming worker termination | Mirroring stops, child is reaped, tray remains alive, and explicit Start recovers. Tested again from installed binaries. |
| Owned worker stall (`SIGSTOP`) | Silence watchdog stopped sharing in 2.019 seconds, reaped the child, retained the tray and recovered after explicit Start. Restoration passed. No automatic permission reacquisition or switch to KWin follows a portal failure. |
| Capture silence | First permission acquisition has a bounded 120-second allowance. After output begins, silence expires after two seconds or three target periods. Inferred packets cannot refresh the watchdog. |
| Stop/preview/restart | Stop keeps the tray alive and releases capture/USB. Preview owns output exclusively; restart resumes. Installed lifecycle tests pass. |
| Crash/installation race | The maintenance lease refuses upgrades while a live tray exists and safely removes a stale socket after a crash. Unexpected socket files are preserved and refused. |
| Shutdown/reporting | Capture and strip ownership end before large profile reports are printed. The initial physical-test collector exposed stdout backpressure; its full report was recovered and the reporting order corrected. The replacement collector uses file-backed output. |
| HID faults | Fragmentation, report IDs, wrong/late ACKs, firmware failure and uncertain short writes remain tested. Manual count is authoritative. No blind write retry or new privilege is introduced. |

Additional installed live tests verified **216 exact complete CPU/GPU colour
comparisons** before the final colour refinements and **117 more exact comparisons**
after them, including unquantized colour vectors. These are in addition to the
earlier 602 comparisons (935 across the recorded versions). The earlier installed
diagnostic discarded no prepared frames. The diagnostic full readback is
separate from performance profiling.

Physical suspend/resume, actual external KDE permission revocation, NL82K1 emitted
light, colourimeter ΔE, optical latency, sustained game load and power draw remain
unverified. Session-close/denial and bounded protocol paths have software checks;
owned-child termination/stall is not falsely presented as a user revoking sharing.

## Measured runtime cost and stopping point

`final-installed-stream-lifecycle.json` records a five-second active window at
ordinary scheduling (configured normal, inherited `nice=4`), with 20 Hz status instrumentation, the user's
unchanged reference configuration, the real strip and the installed binary pair.

| Metric | Observed value |
|---|---:|
| Service + capture worker CPU | 4.58% of one core |
| Service + worker RSS sum | 146,648 KiB, about 143.2 MiB |
| Service + worker PSS sum | 132,557 KiB, about 129.5 MiB |
| GPU/capture callback field, median | 5.583 ms |
| Shared colour/output processing, median | 0.042 ms |
| USB transaction/ACK, median | 20.994 ms |
| Compositor timestamp to software ACK, median | 39.694 ms |
| Final rolling output rate | 47.81 FPS at a 60 FPS target |
| Acknowledged count increase across status samples | 237 |
| Coalesced prepared frames at end of window | 44 |
| Inferred packets | 0 |
| First acknowledged frame after Start | 292 ms |

These are short changing-desktop client measurements, excluding compositor/GPU
power and optical response. The capture field measures worker processing of an
available frame, not the entire acquisition interval. PSS/RSS sums are recorded
separately; RSS double-counts shared libraries. An earlier installed window at `nice=0` showed 4.18% client CPU, USB near
17 ms and output near 58 FPS. The desktop content and inherited scheduling
changed between runs. Do not infer a fixed speedup or guaranteed throughput.

The on-demand settings process separately retained 123,920 KiB RSS and 81,046 KiB
PSS in isolated KWin. No additional CPU tick was observed during its two-second
idle window (10 ms accounting resolution); this is not proof of zero energy use.
Closing Settings removes that process. Earlier paired capture evidence remains
in `RUST_STREAM_VULKAN.md`; it supports lower client CPU for streaming, not a
universal memory or power reduction.

The colour field excludes the final actor dither-phase choice, which is included
in client CPU/response measurements.

The shared colour stage is now far smaller than capture and USB costs. Removing
calibration, colour guards, synchronization or ACKs to inflate FPS would violate
the priority order. Further speculative micro-optimization is therefore stopped.
Prediction is restricted by available bus time, and streaming remains an explicit
advanced choice. The automatic KWin backend and Python fallback remain available.

## Packaging and preservation

The native archive contains the Rust app, adjacent supervised capture binary,
project licence, published dependency notice inventory, installation guide,
existing narrow USB rules and checksums. It installs without Python/Qt runtime
dependencies or elevated privileges. Python is used by development/oracle tools
and the build-time notice collector only. The installer does not apply USB rules,
set DRM capabilities, start mirroring, enable login startup or change user config.

Immutable version directories, a managed command and a normal KDE desktop entry
support explicit upgrade, rollback and recoverable uninstall. The older five-file
bundle format remains accepted for rollback; the newer notice file is also
checksum-verified. External edits/corruption refuse publication of a changed
command. The real binaries passed relocation into paths with spaces, helper
discovery, install/upgrade/two-way rollback, startup enable/disable, running-service
upgrade refusal and uninstall retaining versions, in isolated HOME/XDG directories.
A changed readme intentionally supplies the second smoke-test version; it is not
misrepresented as testing different application behavior.

Actual user-prefix upgrade and two-way rollback between distinct native binary
versions also passed; the final version is selected.

The user installation now has a separate **Nanoleaf Screen Mirror (Rust)** KDE
entry and `~/.local/bin/nanoleaf-native`. Normal KWin authorization was verified
from the installed path. The original Python launcher, Python autostart and
configuration remain byte-for-byte unchanged. Native login startup was not enabled.
The original configuration SHA-256 is
`b470ea82ac1568cf99f4762f6914e4aa295bd3422527e9eb3ca046b52272d1a4`.
Copied-config GUI Save/Apply kept the window open, retained the entire calibration
table and both measured profiles exactly, and created an exact private backup.

A manual native-bundle CI workflow builds artifacts and runs native contracts and
linkability checks. Full KDE cache/launcher integration is local evidence;
hosted CI and publishing have not been run. The existing PyPI release workflow
is unchanged. [Installation and rollback instructions](NATIVE_INSTALL.md).

## Validation artifacts

The raw records are under `perf/rust-native-completion-2026-10-13/`. Native app,
core and capture tests, minimum-compiler formatting/Clippy checks, full preserved
Python tests with coverage, Ruff and mypy pass. The Python run reports 1,613 passes,
23 optional bridge skips and coverage above 75%. The native application suite passes 62 tests and covers
new policies, prediction/ACK boundaries, packaging and recovery as well as the
existing colour/protocol fixtures. The records identify binary/source fingerprints
and deliberately separate old-oracle timing, production replay and live hardware
measurements.
