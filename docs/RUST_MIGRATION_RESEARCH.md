# Recovery, performance and Rust migration research

Date: 2026-10-12 (Australia/Adelaide). Reference revision: `43fcf13381b5d842f9a5f495b226f8b8626d8121`, version 1.9.3. Working branch: `codex/recovery-rust-audit`.

## Decision

Recover the existing application before replacing it. A Rust runtime is worth prototyping, especially native zone sampling and event-driven capture. An entire Python-free application is a valid destination, but replacing the UI first is poorly supported by the evidence. Keep the Python implementation and installed PyPI application as the reference and fallback while comparing native components independently.

The first live run **failed to mirror**, despite successful capture and USB commands. It captured and processed frames, discarded every processed frame as too old, and timed out before sending its first frame. This is a performance/startup interaction, not evidence that capture authorization or USB permissions are broken on this host. The first implementation computes the complete linear-light mean and variance from shared pixel histograms. A bounded live run then started in 235 ms, sent 288 frames and had no stale-output drops. This establishes an initial recovery, not long-term daily reliability.

At the end of the initial recovery audit, no Rust speedup, power saving, physical colour accuracy or optical response had been measured. The [subsequent offline Rust core prototype](RUST_CORE_PROTOTYPE.md) now supplies CPU sampling and protocol parity evidence. It is not integrated into the app. The broader Rust architecture below remains a proposal with explicit adoption gates.

## Evidence and scope

The initial working tree was clean, and `git ls-remote origin HEAD` matched local HEAD. No remote changes were required. The branch preserves the original commit. Existing configuration is schema 2, calibration schema 1, with a manual count of 48 and completed corner calibration. Initial live settings used 60 FPS, 4D sync, HDR preset, high sampling quality and explicit `kmsgrab`.

Reviewed: `AGENTS.md`; current-state and repo-map handoffs; activeContext, decisionLog and progress; the July production audit; README, performance/backend/diagnostics/security/hardware/4D/troubleshooting/feature/RC documentation; CI and release gates; relevant runtime, colour, capture, C helper, HID, config and tray code; and regression tests. The local PR metadata index supplies historical context, including risky priority/FPS changes and subsequent lifecycle recovery; it is not proof of present behaviour. Old local worklogs describe Start doing nothing and Stop/benchmark crashes, without sufficient contemporary tracebacks to establish today's cause.

Documentation discrepancies: `.agents/skills/` and the referenced production-hardening plan do not exist here. The old decision log and CONTRIBUTING prefer KWin while the supplied durable rules and live factory prefer ready DRM capture. Handoff coverage/type-check counts differ from the current tree. Tests and this report supersede historical verification claims; existing records are preserved.

Upstream inspection found an existing [Weekly CI failure on 2026-10-05](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/actions/runs/37320549443) at the reference commit: Python 3.11 failed the **pip audit (runtime deps)** step; the 3.12 and 3.13 jobs succeeded. Failure logs were unavailable (GitHub returned HTTP 403), so the package/advisory or infrastructure cause is unknown. Do not describe this as a confirmed vulnerability or a fixed gate. The latest inspected CodeQL run succeeded. The issue endpoint returned five open items, all pull requests, and no open standalone issues. The local source audit findings remain actionable even without corresponding open issue tickets.

Open upstream PR metadata: [#354](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/354) updates the packaging dependency bound; [#355](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/355) updates github-script; [#357](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/357) updates setup-python; [#358](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/358) updates codeql-action; [#359](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/359) updates the PyPI publish action. None was merged or changed here. These were metadata checks, not full PR reviews, and do not explain the failed runtime audit without its logs.

Host measurements: CachyOS-style Linux 7.2.9, Ryzen 7 7800X3D, RTX 4080 SUPER, NVIDIA 615.78.08, Plasma 6.7.5, Wayland; repository venv Python 3.14.7, NumPy 2.5.1, PyQt6 6.11.0, hidapi 0.15.0. The connected strip is NL82K2. NL82K1 remains a protocol/test requirement, but was not physically available. Monitor: DP-1, 3840×2160 at approximately 240 Hz, scale 1.5; HDR and wide colour gamut enabled, SDR reference white 203 nits. Capture returned 2560×1440 RGB bytes. Display mode and captured pixel coordinates must not be conflated.

## Baseline measurements

Raw evidence and the bounded measurement harness are under `perf/recovery-2026-10-12/`. The harness records timings and process memory, not screen images, USB serials, portal tokens or user configuration. Live mode requires exclusive use of the strip; it temporarily lowers controller brightness, sends black/grey/primary test colours, then restores brightness and power state. It finishes with black, since the protocol cannot read back the previous per-zone image. It does not persist the FPS override used for A/B testing.

For controlled transport attribution, service-window tests inject a real driver using the conservative initial 64-byte report path, with no initial large-report/write-only probe or mailbox mode. They use the existing runtime config for capture, mapping and processing. The headed tray test separately exercises the normal production driver construction. Neither the injected service window nor a software ACK verifies emitted colour.

### Before optimisation

| Measurement | Observation | Meaning / limit |
|---|---|---|
| Automated baseline | 1,574 tests passed in 48.89 s | Headless regression evidence; not a physical usability verdict |
| Doctor, capture and device probes | 0 failures, 2 warnings; NL82K2, 48 zones; KWin capture succeeds | Enumeration, initialization and one frame work |
| Capture policy | Configured kmsgrab falls back to KWin | DRM readiness and runtime success differ |
| USB initialization | About 62 ms | Real model/length/state/brightness transactions |
| Service startup call | About 5,000 ms; later lifecycle state failed | `start()` returning true does not prove a first frame was sent |
| Live frames sent | 0 | Mirroring did not start |
| Stale drops / capture queue drops | 66 / 8 in initial startup evidence | Every outgoing processed frame was rejected |
| Capture call median / p95 | 17.74 / 19.40 ms | Rolling runtime probe; samples can repeat the latest capture measurement |
| Processed frame age median / p95 | 83.78 / 95.89 ms | Measured from capture completion, not screen presentation |
| In-memory 30 FPS retry | Also failed, 0 frames sent | Lowering Target FPS alone did not repair this configuration |
| Instrumented 30 FPS processing median | 70.19 ms | Direct wrapper around the production processing call |
| CPU during 30 FPS startup call | 8,093 ms in 5,000 ms wall time | About 162% of one core; multithreaded native work can exceed 100% |
| Original post-start window CPU | 3.68% of one core | Mostly already failed/stopped; **not active mirroring CPU** |
| Original post-failure RSS / PSS | 158.7 / 142.3 MiB | Retained allocations after failure; not a successful steady-state baseline |
| Stop after failed start | Succeeded; not running afterward | Does not verify headed tray survival |
| Optical response and emitted colour | Unmeasured | USB completion/ACK does not measure LED light |
| Power | Unmeasured | No isolated whole-system or compositor/GPU power comparison |

The synthetic production preset is 640×360, 48 zones, 120 samples after 10 warmups. One initial run measured zone sampling median/p95 4.27/4.32 ms, full colour pipeline 23.10/26.86 ms, and HID frame construction 0.0117/0.0151 ms. Three subsequent raw repetitions are included separately. The preset's full pipeline includes sampling; do not add its time to the standalone sampler time. It is not the user's native-resolution 4D pipeline. The current CI limits (80, 120 and 5 ms respectively) are loose regression ceilings, not a 60 FPS acceptance bar: a 60 FPS frame interval is 16.67 ms.

### Memory and startup attribution

Fresh subprocess import probes measured approximately:

| Workload | RSS MiB | PSS MiB | Module import ms |
|---|---:|---:|---:|
| Interpreter + measurement support | 12.1 | 5.7 | N/A |
| NumPy import | 28.8 | 17.3 | 46.8 |
| Service import, no running service | 50.9 | 34.3 | 142.1 |
| Tray module import, no tray constructed | 72.0 | 53.0 | 140.7 |
| Offscreen QApplication only | 38.1 | 26.9 | 14.5 |

These are isolated import probes, not GUI-ready startup time or real tray idle memory. RSS counts shared libraries; PSS apportions them. The NumPy sleep-only probe consumed about 10.4% of one core during its first two seconds, consistent with native library startup activity; its cause and repeatability were not isolated. Do not extrapolate it to tray idle CPU. Other sleep-only probes were near zero. Process creation/import/exit times including interpreter overhead are retained in JSON.

### First averaging experiment

A 240×180 controlled RGB patch took approximately 0.624 ms per full linear-light mean versus 0.161 ms using per-channel value counts. Both produced the same RGB result. This was a local micro-experiment, not a Rust implementation.

The first live histogram-only prototype started in about 1,002 ms, processed frames in a median 48.22 ms and sent 50 frames, but also discarded 150 stale frames. This exploratory run briefly overlapped a separate profiling command and used changing desktop content. It is not a controlled resource comparison. Its successful-frame capture-completion-to-USB-completion median/p95 was 58.07/63.33 ms; this excludes display presentation, capture acquisition and LED optical response. Further implementation results belong in the validation section below.

## Architecture audit

Current flow: PyQt tray → service/lifecycle → capture, process and HID workers with bounded queues → sampler/colour/calibration → Nanoleaf TLV transport. The capture queue holds up to four frames, processed queue eight; processing and sending consume the latest queued frame. Capture currently drops new frames on queue overflow, which can retain older work. A Rust port should use a bounded latest-frame mailbox with explicit lifetime ownership, not an unbounded stream.

| Component | Decision | Reason / migration boundary |
|---|---|---|
| TLV protocol and device IDs | Port early, retain Python oracle | Small deterministic surface; preserve NL82K1/2 and command/status semantics |
| HID transport and reconnect | Port after wire fixtures | Single owning worker; retain report-size probing, fragmentation, ACK/drain, errors and reconnect pacing |
| Zone averaging and variance | Optimise now; native Rust CPU prototype first | Largest measured processing cost; retain complete pixel coverage and locality |
| Colour/HDR/calibration math | Port only with explicit data-domain contracts | Correct existing mistakes; avoid reproducing byte casts and guessed metadata |
| Runtime scheduling and lifecycle | Port as a state machine after baseline | Start/Stop/output ownership must survive faults and restart; no realtime scheduling |
| KWin screenshot backend | Retain as fallback, prototype zbus implementation | Reliable capture here; screenshot IPC cost survives a language port |
| Portal/PipeWire | Redesign as persistent event-driven Rust stream prototype | Existing Python/GStreamer path converts/scales/copies; negotiate actual buffers instead |
| C DRM helper | Retain temporarily as isolated optional helper | Rust does not remove DRM privilege needs; audit FD transfer before changing it |
| Python ctypes DRM sampler | Replace incrementally with checked Rust layout handling | Pixel loops, manual struct layouts and modifier heuristics are fragile |
| Current Vulkan adapter | Treat as CPU code; replace its claims and prototype separately | Loading libvulkan is not GPU import, dispatch or reduction |
| PyQt settings/setup/calibration UI | Retain during runtime experiments | Large parity surface, not the measured processing bottleneck |
| Native Qt/QML UI | Strong candidate, on demand | Remove Python while preserving KDE integration; Qt/C++ remains |
| Rust-native UI/tray | Evaluate against Qt/QML, not excluded | Useful if it wins measured idle/PSS/usability and accessibility tests |
| Config/doctor/export/autostart | Port late, preserve existing data and entry points | User recovery/config safety matters more than avoiding a small Python dependency immediately |
| Experimental predictors/palettes/virtual oversampling | Preserve reference; feature-gate in native prototype | No blanket removal; require measured value and feature parity before retirement |

### Diagnosed risks

1. **Startup starvation:** before the initial optimisation, processed frame ages exceeded 60 ms and all output was dropped. The FPS governor learns from sent frames; it receives no useful successful-frame feedback when nothing can be sent. Startup then misleadingly says capture produced no frame. Recovery should expose processing/stale-drop timing even when output fails, and distinguish capture failure from output starvation. Do not fix this by blindly disabling stale protection.
2. **Full-patch duplicate work:** the box sampler decodes every pixel for the mean, then converts the same patch to floats for variance. Count each byte value once and derive both statistics from those counts. This retains full coverage and the existing linear-light average.
3. **False GPU attribution:** `_vulkan_import_dma_buf_image` stores a dictionary; `_vulkan_dispatch_zone_sampler` calls `sample_zone_rects_from_dma_buf`; there is no VkDevice, shader, command buffer or compute dispatch. KMS can label this `vulkan-zone-rects` nevertheless. Process-global sampler state also complicates concurrent probes.
4. **HDR truncation:** the shared DMA-BUF sampler casts delegated CPU results to uint8. A controlled `[0.5, 1.0, 2.0]` float sample becomes `[0, 1, 2]`. Normalised HDR data can become entirely zero and trigger the adapter's `zero_zone_sample` exception. This was reproduced offline, not on real scanout.
5. **Read-only mapping failure:** the standalone DMA-BUF sampling path opens `PROT_READ`, then uses writable `ctypes.from_buffer`. A real read-only mapped test file raises `TypeError: underlying buffer is not writable`. Fix with a read-only view and bounds/synchronisation tests, not writable privileges.
6. **Black conflated with failure:** the Vulkan-named adapter rejects valid all-black uint8 samples. Transport/capture errors must be distinct from black content; black must reach LED off. Validate geometry and success separately before removing this guard.
7. **Scanout metadata guesses:** 10-bit format is labelled gamma22/BT.2020, FP16 linear/BT.2020; then `display_referred=True` can override transfer/primaries to sRGB/BT.709. Buffer format does not prove transfer or gamut. P3 is currently folded into BT.709 and display chromaticities use heuristics. Treat these as correctness debt.
8. **Modifiers and memory safety:** Intel CCS and AMD tiled paths currently use pitch-linear offsets; NVIDIA layouts are special-cased. Unsupported modifiers must fail closed, not be interpreted as linear. Validate plane sizes, offset/stride arithmetic, FP16 sign/nonfinite handling, mapping lifetime and DMA-BUF synchronisation before native adoption.
9. **Privilege/readiness mismatch:** doctor exempts helper development/non-system paths from capability checking, although the helper cannot thereby acquire DRM master or ptrace permissions. This host has AMD card0 and NVIDIA card1; hardcoded card0 is not proof of the selected monitor's GPU. No capabilities were added in this audit.
10. **Launcher environment:** `runtime_exec_command` resolves the venv Python symlink to the system interpreter. A migration must retain the intended executable environment and desktop identity. This host's system Python also imports the source tree, so a launcher failure was not established here; isolated venv tests are needed.

## Capture research

### KWin D-Bus in Rust

Use `zbus` for typed session-bus calls and Unix FD transfer; drain the raw pipe concurrently/boundedly, validate dimensions/stride/QImage format and preserve selected-output identity across owner changes. Cache connection/introspection, not screenshots. Known little-endian RGB32/ARGB32 layouts can be decoded without Qt. Unknown/high-depth formats require an explicit decoder or fallback, not silent reinterpretation.

KWin's current upstream screenshot writer sends raw QImage bytes with format, dimensions, stride and scale metadata. Its native-resolution option changes capture geometry. This is screenshot IPC, not a streaming DMA-BUF API. The examined upstream file may differ from installed KWin; retain version/capability checks and authorization handling. Rust will reduce client allocations and scheduling overhead, but cannot remove compositor readback or the pipe copy. [KWin source](https://raw.githubusercontent.com/KDE/kwin/master/src/plugins/screenshot/screenshotdbusinterface2.cpp), [zbus](https://docs.rs/zbus/latest/zbus/).

### Portal + PipeWire in Rust

Use `ashpd` to request one monitor, hidden cursor, persistent session where granted, and open the restricted PipeWire remote FD; use the Rust `pipewire` bindings for stream negotiation/dequeue/queue. Keep portal consent and desktop identity. A restored session supplies a replacement single-use token; persist it atomically. Version 6 stream serials should be preferred over reusable node IDs, with version-aware compatibility fallback. Handle Closed, revocation, KWin/PipeWire restart, monitor removal and suspend/resume explicitly. [ScreenCast specification](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html), [ashpd](https://docs.rs/ashpd/latest/ashpd/desktop/screencast/), [pipewire](https://docs.rs/crate/pipewire/latest).

Prototype memory-mapped CPU buffers first, keeping the callback minimal and queueing newest work. Negotiate format, colourimetry, range, plane offsets, stride and modifier rather than forcing RGB/BT.709. Release/requeue buffers only after readers/GPU work finish; never retain a borrowed PipeWire memory slice after queueing it. ScreenCast source geometry is not necessarily pixel geometry. Permission mediation does not guarantee an HDR-preserving stream.

### DMA-BUF and DRM/KMS

DMA-BUF is a buffer-sharing mechanism, not a source of capture permission or colour metadata. CPU reads may require cache synchronisation and fence waits. Multi-plane formats, modifiers and buffer ownership must be represented explicitly. A read-only mapping is insufficient proof that a buffer is ready to read. [Kernel DMA-BUF documentation](https://kernel.org/doc/html/next/driver-api/dma-buf.html), [PipeWire DMA-BUF design](https://raw.githubusercontent.com/PipeWire/pipewire/master/doc/dox/internals/dma-buf.dox).

Rust's `drm` crate can wrap relevant ioctls, but KMS framebuffer handles remain restricted to DRM master/CAP_SYS_ADMIN. Render-node access does not grant arbitrary scanout capture. The present helper's KWin FD cloning uses ptrace-related privilege and has a wider authority surface than portal capture. Retain existing optional DRM behaviour temporarily; do not put capabilities on the daemon/UI, take compositor mastership or add privilege to make a prototype succeed. Select the existing chosen monitor's connector/GPU, not the first DRM card. [DRM crate](https://docs.rs/drm/latest/drm/), [kernel GETFB2 contract](https://origin.kernel.org/doc/html/v6.14/gpu/drm-uapi.html).

Before extending the helper, review its UNIX socket, private directory, peer identity, expected payload size, ancillary message truncation, FD cleanup on every failure, GEM handle lifetime and the minimal required capabilities. Rewriting it in Rust can reduce memory bugs but does not make its permissions less powerful.

### Genuine Vulkan compute

Use `ash` for explicit Vulkan rather than assuming a high-level renderer exposes Linux modifier import. Query the actual GPU and importable external-memory formats/modifiers. A viable prototype needs DMA-BUF import, DRM format modifiers, external memory FD support, appropriate image usage, plane layouts and the matching source GPU. Add only supported synchronization mechanisms. [ash](https://docs.rs/ash/latest/ash/), [DMA-BUF extension](https://docs.vulkan.org/refpages/latest/refpages/source/VK_EXT_external_memory_dma_buf.html), [modifier extension](https://docs.vulkan.org/refpages/latest/refpages/source/VK_EXT_image_drm_format_modifier.html).

Build a real compute pipeline: import image → wait/acquire → decode transfer per pixel → reduce each existing calibrated source zone → small result buffer → read back zone floats → CPU colour/calibration/HID. Do not download the whole image. Handle foreign queue ownership, completion fences and host-visible readback correctly; never block PipeWire's callback on GPU completion. Cache pipelines and resources by layout generation; invalidate on size/modifier/device changes. Keep a checked CPU fallback. [External memory/sync guide](https://docs.vulkan.org/guide/latest/extensions/external.html), [synchronization examples](https://docs.vulkan.org/guide/latest/synchronization_examples.html).

For 48 RGB float zones, the ideal readback is 576 bytes before alignment, compared with 31.6 MiB for one 3840×2160 RGBA8 image. This is a calculated payload comparison, not a measured bandwidth saving: import, compositor copies, fences and discrete-GPU clocks still cost time/power. Never call the existing CPU adapter a Vulkan benchmark. Promotion requires a captured GPU dispatch trace, reference-image agreement and native-resolution latency/power measurements under desktop and game load.

Direct wlr/ext capture protocols are not substitutes for portal consent or guaranteed KDE availability. Probe advertised globals and permission policy; keep KDE/portal-supported paths as the contract. [wlr screencopy](https://wayland.app/protocols/wlr-screencopy-unstable-v1), [image copy capture](https://wayland.app/protocols/ext-image-copy-capture-v1).

## USB and runtime research

The [bundled manufacturer protocol](reference/NOAD1-Nanoleaf%20USB%20Lightstrip%20Communication%20Protocol-170426-150729.pdf) specifies VID 37FA, PIDs 8201/8202, one-byte type, big-endian two-byte payload length, response type request+80h and a status byte. Zone payloads are three bytes per zone; output requires power on and nonzero device brightness. The document has an inconsistent maximum-payload description, so preserve tested limits rather than infer a new transport size. The existing driver configures GRB despite the document's RGB wording; preserve the driver/model/config mapping and validate both models physically before replacement. Firmware response time and report-size behaviour are measured contracts, not language properties.

Rust `hidapi` offers hidraw and a Linux-native backend; begin with explicit hidraw compatibility and compare the native backend after report-level tests. Open the matched path/interface, not an arbitrary VID/PID match. Keep one HID owner, bounded reads, status/unsolicited-event parsing, reconnect backoff, manual zone count authority and no unsafe resend after uncertain partial writes. A synchronous USB write can block in Rust too; investigate pollable hidraw or an isolated transport worker/process if cancellation is required. [hidapi backend documentation](https://docs.rs/hidapi/latest/hidapi/).

At 48 zones, the live frame is 147 TLV bytes; the measured initial 64-byte data path used three reports (64/64/19). Packet-building cost is around hundredths of a millisecond, while real write/ACK work is milliseconds. Porting framing alone cannot produce a major end-to-end win. The original 30-pattern sequence's driver counters included one missed ACK; command/write completion is not proof that every acknowledgement was correctly attributed or that the expected physical colour appeared. Keep response-required mode as a safe baseline; compare bounded-drain, write-only and mailbox policies separately, including late/stale ACK and partial report failure. Do not assume a large report size or skipped ACK is compatible just because synthetic tests accept it.

For the Rust runtime, use an event loop for D-Bus/control and explicit capture/processing/HID ownership. Normal Linux scheduling, absolute monotonic deadlines and blocking notifications are enough to prototype. Avoid 1–2 ms polling loops and per-report thread creation. Reuse existing Target capture/output FPS and `performance_priority`; no FIFO/RR and no new user priority controls. Priority failures must be visible and nonfatal. Measure wakeups, context switches and CPU/GPU load before adding thread pools. `zbus` runtime features can avoid hidden extra executor threads when configured deliberately; do not assume async means fewer threads. [zbus runtime guidance](https://docs.rs/zbus/latest/zbus/).

## Colour contract and hardware limits

Represent captured samples with explicit pixel format, bit depth, transfer, primaries, range, alpha convention, reference white/max luminance, display/scene-referred status, conversion history and confidence. None can be inferred safely from an ndarray's peak value or a 10-bit FOURCC alone. Preserve FP16/10-bit precision until the defined conversion; quantize exactly once before HID.

For SDR, decode sRGB before averaging. Half black plus half white should yield approximately code 188, not 128. For PQ, use the absolute luminance EOTF and explicit reference/target white; HLG needs its own transfer/system-gamma interpretation. Do gamut adaptation and LED calibration in the documented linear domain, then encode according to measured LED/controller response. Do not apply HDR tone mapping to an already tone-mapped screenshot. Do not treat P3 as BT.709 or override observed transfer simply because a buffer is display-referred. [ITU BT.2100](https://www.itu.int/rec/R-REC-BT.2100).

KWin fallback ran on a real HDR desktop, but that alone does not verify HDR conversion correctness. The screen was not switched to SDR during this audit. Real SDR/HDR A/B, reference patch presentation/capture, neutral-grey/white/black LED observation, gamut clipping and colour-meter calibration remain required. A screenshot/sample comparison proves captured RGB, not emitted colour. No colourimeter or high-speed camera was used.

Retain imported SDR/HDR matrices, channel gains/gamma, dark-sample settings, corner anchors, direction, manual counts and per-preset profiles. Use physical black/off and neutral fixtures as hard guards. Test edge-local saturated objects beside grey, checkerboards/remainder pixels, low-light ramps, scene cuts, metadata transitions, alpha/stride/endianness and NaN/negative/over-range HDR samples. RGB LED emission, strip diffuser, mounting and wall reflectance limit exact display matching; measure those effects rather than compensate with global desaturation or flattening.

## UI and architecture alternatives

| Option | Benefits | Costs / adoption gate |
|---|---|---|
| Python UI + native Rust kernel | Fastest low-risk native experiment; current calibration/setup UI intact | Python/Qt stay resident; FFI data/lifetime discipline; cannot remove compositor IPC cost |
| Rust daemon + on-demand Python UI | Active runtime avoids Python/Qt UI residency | Versioned IPC and cross-process output ownership; preserve permissions/desktop launch; temporary Python dependency |
| Rust daemon + Qt/QML through CXX-Qt | Python-free application logic with KDE-compatible Qt integration | C++/Qt build/runtime remain; QML settings/calibration parity and accessibility tests |
| Rust daemon + ksni + Slint/iced/egui GUI | Rust application/tray; GUI can be unloaded when closed | KDE styling, dialogs, monitor geometry, accessibility, tray restart and renderer power must be proven |
| Single persistent Rust GUI/runtime process | Simpler control boundary and ownership | GUI renderer/runtime may remain resident unnecessarily; GUI faults affect capture unless isolated |

`ksni` implements KDE/freedesktop StatusNotifierItem and can keep a small tray/control surface without a full GUI. Qt's QSystemTrayIcon also supports StatusNotifierItem on Linux. CXX-Qt bridges Rust QObjects to Qt/QML; it removes the Python requirement, not Qt or C++. Rust-native Slint, iced and egui/eframe are legitimate comparison candidates; toolkit choice alone gives no memory/power guarantee. Slint licensing must be checked against this repository's source-available noncommercial license before adoption. [ksni](https://docs.rs/ksni/latest/ksni/), [Qt tray](https://doc.qt.io/qt-6/qsystemtrayicon.html), [CXX-Qt](https://kdab.github.io/cxx-qt/book/), [Slint docs](https://docs.slint.dev/latest/docs/slint/), [Slint licensing](https://slint.dev/pricing), [iced](https://docs.rs/iced/latest/iced/), [eframe](https://docs.rs/eframe/latest/eframe/).

Recommendation: compare a Rust CPU kernel first, then a Rust daemon with an on-demand GUI. Evaluate Qt/QML and one Rust-native UI using the same settings/setup flows. Keep a native tray in the daemon or separate lightweight control process. The preferred UI is whichever proves reliable on KDE and reduces idle memory/power without sacrificing calibration usability; neither Python nor Qt is mandatory.

## Proposed modular Rust design

Start with a small workspace, not a plugin platform:

```text
core       fixed strip mapping, config model/migrations, colour domains, zone kernel
transport  Nanoleaf TLV, hidraw/hidapi owner, reconnect and ACK state
capture    explicit KWin / portal / optional DRM implementations
runtime    lifecycle, generation-based ownership, latest-frame queues, timings
app        CLI/doctor + session daemon + tray
gui        on-demand settings/setup/calibration client, chosen after comparison
```

Use interfaces only where independent backends/tests require them. No multiple-strip routing, generic mapping engine, plugins or automatic zone-count promotion. In a daemon design, the daemon alone writes USB. GUI previews acquire an exclusive output lease, pause mirroring, invalidate queued generations and release only after cleanup. Start/Stop/preview/reconnect are serialized state transitions. Stop blacks the strip, releases capture/stream work and keeps tray/control alive; Quit terminates the app. GUI crashes or stale clients cannot keep/reuse a preview lease indefinitely.

Control IPC can be a versioned user-session D-Bus service with bounded messages and explicit errors. It carries settings, preview commands and status, not full frames. Use same-user identity checks where appropriate; no network listener. Do not spawn a privileged daemon. Lifecycle and USB errors must not make Settings/diagnostics inaccessible.

## Config migration and fallback

Initially, native prototypes read an exported/copied config and never overwrite the user's file. Port schema 2 and calibration schema 1 using typed TOML/serde models, but retain unknown keys losslessly for round-trip/backward compatibility. Maintain manual count and profile precedence exactly; malformed/future schemas are refused with actionable guidance and no destructive write.

Before a future format change: back up original bytes, validate the full migrated representation, write to a same-directory temporary file with private permissions, flush/fsync, atomically rename and preserve a rollback copy. Preserve advisory locking and add directory durability checks. Test legacy schemas, duplicate anchors, mismatched counts, imported colour matrices, both display profiles, interrupted writes and concurrent save. Python must still load the unchanged schema during hybrid stages. Native-only additions should use a sidecar until downgrade behaviour is verified. Never replace the installed fallback until configuration downgrade and UI/hardware parity pass.

## Expected benefits: calculations and estimates

| Change | Quantification | Confidence |
|---|---|---|
| Rust TLV construction | Existing median roughly 0.012 ms | Measured Python cost; even removing all of it is a negligible frame win |
| Full-zone CPU optimisation | Original native-resolution processing about 70 ms; first histogram prototype about 48 ms | Measured exploratory Python improvement; final controlled evidence still required |
| Native CPU zone kernel | Compare against the now-optimised Python path; aim for <=5 ms p95 total processing on the same native-resolution workload | Acceptance target, **not a Rust benchmark or guaranteed speedup** |
| GPU-only zone readback | 576 bytes of RGB float output for 48 zones vs 33,177,600 bytes RGBA8 at 4K | Payload calculation only; import/readback/fence overhead unmeasured |
| Eliminate full-frame float temporaries | 94.9 MiB for 4K RGB float32; 189.8 MiB for float64 RGB | Array-size calculation; actual current ROI path does not allocate all of these simultaneously |
| Remove persistent Python UI | Service/tray import PSS differed by about 18.7 MiB here | Separate import snapshots, not additive allocations or guaranteed daemon savings |
| Rust daemon memory | Initial engineering target <=40 MiB PSS for CPU capture path, GUI closed | Unvalidated target; Vulkan/driver mappings may exceed it |
| Polling → notifications | Potentially fewer wakeups and lower idle CPU | No watt or battery claim without controlled measurement |
| Streaming capture | Potentially lower repeated screenshot IPC/copies and smoother arrival | Requires portal/PipeWire benchmark; language alone cannot establish it |

Active CPU must be measured during successful sustained mirroring, summed across daemon/helper/GUI and compositor costs. A failed service's near-zero CPU is not a successful optimisation. Compare same desktop frames, manual zones, colour settings, effective output rate, display mode and power profile. Measure RSS/PSS separately; report GPU/device memory too. Include warmup, multiple runs, p50/p95/p99 and maxima. Do not add component percentile values to invent end-to-end percentiles.

## Reproducible validation and migration sequence

1. **Recover and measure:** retain the reference revision; reproduce startup starvation; implement the exact full-pixel sampling optimisation and behavioural tests. Collect successful steady-state CPU/memory/stage timings, then verify actual tray Start/Stop/Settings and capture fallback. Improve stale/startup diagnostics before further tuning.
2. **Freeze reference fixtures:** reuse existing colour golden/neutral/zone locality/calibration/4D tests. Add deterministic native-resolution SDR and PQ/HLG/FP16 frames with transfer metadata and expected linear means; use reproducible seeds and exact wire bytes. Keep fixtures synthetic and free of screen content. Compare numeric results with explicit tolerances, including expected bug corrections.
3. **Rust core prototype:** port TLV and fixed strip/zone data types first; no hardware writes. Add Rust unit tests and a shared Python/Rust fixture harness. Then implement allocation-bounded scalar CPU sampling; compare with current exact linear means. Benchmark release builds on the same frames before SIMD or parallelism.
4. **Transport integration:** add hidraw/hidapi ownership, read/write/ACK/reconnect with mock faults and protocol vectors. Verify both NL82K1 and NL82K2, channel order, report sizes and unplug/replug on hardware before default use. Keep Python transport selectable as fallback.
5. **Capture prototypes:** Rust KWin parity first; portal/PipeWire streaming second; DMA-BUF/Vulkan third. Negotiate formats and retain checked CPU readback. Never make streaming/GPU default from a library-availability probe. Prove permission restoration, monitor selection, HDR/SDR metadata and recovery.
6. **Daemon and GUI comparison:** run identical scenarios using Python UI, Qt/QML and a Rust-native GUI. Measure GUI closed idle, Settings open, calibration preview and daemon-only mirroring. Test output lease/generation invalidation, Stop keeps tray alive, Save stays open, sleep/resume, portal revocation and KWin/USB reconnect.
7. **Adopt or retain:** replace each stage only when fixtures, regression suite, sustained hardware runs and matched performance comparisons pass. Remove Python packaging/runtime only after native config migration/downgrade, tools, install/doctor/autostart, diagnostics and complete UI parity pass. Keep a documented reinstall/rollback path to the PyPI reference.

Required baseline experiments include static desktop/solid edges, seeded checkerboard/ramp/reference colours, changing edge patches and real video/game load. Report capture request-to-completion, processing, queue residence, USB write/ACK and capture-completion-to-USB-completion separately. Count capture errors, buffer overflow, coalescing, stale drops and intentional duplicate skips separately. Physical screen-to-light response requires a timestamped display transition plus high-speed camera/photodiode; no software timer can substitute for that evidence.

Power tests need matched idle/load runs with and without the app, repeated long enough for GPU clock settling. Report package/GPU estimates separately from a wall-meter reading; include compositor CPU/GPU work. Successful sustained output, rather than a stopped or failed runtime, is the comparison condition. Test clean launch and reconnect without changing privileges.

## Initial implementation validation

The unmodified baseline is preserved above and in raw evidence. Scope is full-pixel mean/variance computation; capture defaults, stale-age limits, HID protocol, calibration/config and UI are unchanged. No Rust module or GUI replacement has been adopted.

For each uint8 channel, count all codes 0–255 once. The linear mean is `sum(count[k] * srgb_decode(k)) / N`. Encoded variance is `sum(count[k] * k*k) / N - mean_encoded**2`. This avoids repeated float-sized patch conversions and reductions. No decimation, screen downscaling, cross-zone averaging, desaturation or extra smoothing is introduced. Float inputs retain the previous decoding path. Empty/clipped zones return black/zero variance. Multi-moment colour selection retains its existing path.

On identical seeded frames and 48 tight edge zones, 20 timed samples after three warmups measured:

| Frame | Previous mean + variance median | Shared histogram median | Maximum RGB code difference |
|---|---:|---:|---:|
| 640×360 | 3.61 ms | 1.61 ms | 0 |
| 2560×1440 | 40.23 ms | 4.88 ms | 0 |
| 3840×2160 | 91.91 ms | 9.49 ms | 1 |

The 4K one-code difference is a rounding change from the old float32 accumulation, not pixel omission. Histogram counts use higher precision for reduction; tests compare against a complete float64 pixel reference. Maximum variance differences from the old float32 reduction were 0.018, 0.119 and 0.279 code-squared respectively. This small numerical change can affect a variance threshold at its exact boundary; existing adaptive sampling, locality, privacy and colour regression tests passed. These sampler timings are a matched comparison; they are not complete capture/runtime/Rust timings.

First final-patch live window (ten seconds, original 60 FPS config/4D/HDR): startup 234.53 ms; 288 frames sent; zero stale-output drops; effective output approximately 28 FPS, not the configured 60 FPS. Processing call median 8.61 ms; accepted-frame processing median/p95 8.39/9.46 ms; zone sampling 7.40/8.50 ms; HID send 2.87/3.35 ms; capture-completion-to-USB-completion 15.79/17.29 ms. The existing governor and pacing still limit throughput. Active process CPU was 87.70% of one core; RSS/PSS 160.1/143.6 MiB. This is successful mirroring; do not compare its CPU directly with the failed-before post-start window to claim a percentage saving. Desktop content varied; there is no matched live memory/power improvement claim.

An independent repeat sent 292 frames with zero stale-output drops: startup 231.44 ms, direct processing median 8.22 ms, capture median/p95 17.87/19.14 ms, and capture-completion-to-USB-completion 15.22/16.77 ms. CPU was 85.95% of one core, RSS/PSS 147.4/130.9 MiB. Both successful windows stopped and released runtime work. This is repeatability over short windows, not a long-session soak.

The standalone production sampler median across three before/after runs improved from 4.33–4.46 ms to 1.69–1.76 ms. The full production pipeline stayed roughly 22–23 ms because its default adaptive palette path does not use this box-filter optimisation throughout; claiming the whole app became eight times faster from the matched zone benchmark would be incorrect. All three after-patch runs pass the existing CI timing budgets. With native-resolution box sampling now much cheaper, the measured ~18 ms screenshot call is a stronger reason to prioritise event-driven streaming capture experiments before a UI rewrite.

A real KDE tray/QApplication run auto-started from the existing config, sent output, stopped without hiding the tray or quitting its event loop, started again, stopped again, and opened/closed Settings without saving. Config and launcher bytes were unchanged. After that sequence, stopped-tray idle CPU was 0.0062% of one core over two seconds, with RSS/PSS 254.3/226.8 MiB after Settings had been opened. That is retained GUI/runtime memory, not a cold idle baseline. The optional background update checker was disabled for this bounded test. Tray visibility was checked through Qt and event-loop survival, not a pixel-level visual inspection or a manually clicked menu.

Validation: 49 focused sampling/colour tests passed; full suite **1,588 passed**, coverage **77.55%** (75% minimum); ruff source/tests/scripts lint and formatting passed; mypy passed across 110 source files; version alignment passed. Commit hooks also passed ruff, mypy, Bandit and Gitleaks. No new hosted CI run, runtime dependency audit, Semgrep or packaging/release gate was executed, and the published installation was not changed. The PyPI installation remains the fallback. Raw runtime/USB samples, import probes, matched comparison and headed lifecycle results accompany this report.

Remaining hardware acceptance items: manual visual tray/Settings review and Save/preview interactions, physical neutral/black/primary inspection, real SDR/HDR transition comparisons, unplug/replug and suspend/resume, NL82K1, controlled content/optical latency, power and sustained load soak. Successful short service runs cannot close those items. Capture and colour/HDR correctness debt identified above is still open; a sampling optimisation does not fix it.
