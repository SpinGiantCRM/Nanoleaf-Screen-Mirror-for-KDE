# GPU streaming adoption and explicit synchronization

15 October 2026. Priority: recreation time, colour reproduction, FPS, resources.

## Daily capture on the tested host

The user compared ten seconds of KWin screenshots with twenty seconds of the
existing implicit-sync portal/Vulkan stream, at bounded low brightness. Their
assessment was **“As responsive or faster; colours stable.”** Both phases restored
and read back the original controller power and brightness. This is a subjective
response/colour check, not an optical latency measurement.

The tested Rust GUI/capture package is installed locally. The transactional
backend selector changed exactly `capture_backend` to `xdg-portal`. A full parsed
TOML comparison preserved every other value, including both calibration profiles,
manual 48-zone mapping, fast-response settings, selected monitor, FPS and priority.
An exact old configuration backup, older native versions, Python launchers and
autostart preferences remain intact. The live stream uses the previously selected
DP-1 through KDE's existing permission flow, without privileged capture access.
The repository-wide `auto` backend policy remains KWin.

Two sequential 20-second desktop samples, with 2 Hz external status polling:

| Measurement | KWin screenshots | Implicit GPU stream |
| --- | ---: | ---: |
| Client CPU, percent of one core | 62.67% | 2.15% |
| Summed client RSS | 79.77 MiB | 144.00 MiB |
| Summed client PSS | 77.07 MiB | 126.49 MiB |
| ACK count between first/last snapshots | 890 | 786 |
| Approximate ACK cadence | 45.6/s | 40.3/s |
| USB transaction snapshot median | 22.00 ms | 21.99 ms |
| Reused-source ACK counter increase | 0 | 120 |
| Prepared-frame overwrite counter increase | 133 | 67 |
| Additional reconnects | 0 | 0 |

CPU includes the tray/service and its stable capture child, across all their
threads. It excludes the compositor, GPU, status sampler and separate settings UI.
Process CPU uses `/proc` tick deltas over the measured elapsed time; RSS/PSS are
end-of-window `smaps_rollup` readings. Main application/capture threads ran at
normal nice 0. NVIDIA's two background disk threads retain their own nice 19.
No real-time scheduling was added. These are different, uncontrolled desktop
windows: the observed client CPU reduction is substantial, with a memory cost,
but it is not a controlled system power or sustained video/game comparison.

The GPU window included source reuse; ACK cadence is not fresh captured FPS.
It does not establish an FPS improvement. KWin response timestamps begin at the
screenshot request, while streaming uses producer PTS and marks reuse separately.
Their snapshot response medians (49.83 and 56.04 ms) cannot establish a winner in
visible response time. The positive user comparison is the current usability
evidence. Exact optical response and sustained game cadence remain open.

## Implemented explicit-sync experiment

KWin's pinned screencast implementation supports producer/consumer DRM syncobj
timelines. Its non-explicit NVIDIA path calls `glFinish()` in the compositor's
GL context. This makes explicit synchronization a plausible way to reduce capture
interference under load; it does not prove a benefit on this machine.
[KWin source](https://github.com/KDE/kwin/blob/ab7df7ccb7c6af20f4b279cd6220f7cd3d2267d7/src/plugins/screencast/screencaststream.cpp).

The new opt-in capture path negotiates one image plane plus two syncobj FDs and
required SyncTimeline metadata. The isolated worker waits for actual acquire
completion with a bounded deadline, performs the existing Vulkan sampling and
foreign-ownership release, then signals the granted release point. Unused frames
are acquired/released too. If an accessed buffer cannot be safely released, the
worker exits before it can requeue that buffer. Ordinary worker supervision then
stops mirroring and requires an explicit Start.

This implementation uses host-waited DRM timeline ioctls and waits for Vulkan
completion before signaling release. It is **not** a fully asynchronous Vulkan
semaphore pipeline. It opens only the render node identified by the selected
Vulkan physical device, validates its character-device identity, and imports only
the producer-granted syncobjs. It adds no KMS, primary-node, root or capability
requirement. Stable local SPA/UAPI layouts retain older build-header compatibility;
unsupported flags, point order, layouts or negotiation fail explicitly.
[Linux synchronization contracts](https://docs.kernel.org/gpu/drm-mm.html#drm-sync-objects).

The default implicit path stays unchanged. Explicit sync is enabled only by the
operator environment variable `NANOLEAF_EXPLICIT_SYNC=1`; even a value of `0`
enables this presence-based experimental flag. Do not set it for daily use yet.
No new normal Settings, FPS or scheduling control was introduced.

Read-only eight-second phases, ordered implicit/explicit/explicit/implicit:

| Mode | Frames | Normal callback median | Producer-PTS age median |
| --- | ---: | ---: | ---: |
| Implicit | 235 | 0.623 ms | 14.55 ms |
| Explicit | 239 | 1.395 ms | 20.48 ms |
| Explicit | 238 | 1.349 ms | 16.20 ms |
| Implicit | 234 | 1.001 ms | 13.20 ms |

All 946 frames used the requested synchronization mode without errors; the
diagnostic frames made 1,536 zone comparisons. Normal callback medians exclude
diagnostic full-readback frames. Existing mirroring was stopped during the suite.
This short idle run does **not** show an explicit-sync latency benefit, so daily
capture remains implicit. A controlled GPU-load comparison is required before
considering a change. Coalesced/corrupt explicit buffer release has defensive
handling and unit coverage for descriptor/metadata rejection, but these suite
windows did not encounter discarded buffers; no live discard-path claim is made.

## Colour and recovery gates

The final packaged helper passed 291 implicit and 290 explicit full calibrated
CPU/GPU frame comparisons, all exact, with Vulkan validation enabled. Neither
run produced an error or validation stderr. This checks the saved reference-mode
colour pipeline and manual mapping. Format was 3840×2160 packed SDR BGRA on the
RTX 4080 SUPER, NVIDIA 615.78.08, KDE 6.7.5. HDR desktop mode does not make these
frames raw HDR; the application still receives display-referred SDR.

Both packaged variants passed live Stop/tray persistence, exclusive zone preview,
Start/restart, capture-worker termination, frozen-worker watchdog stop/reap, and
explicit recovery. Watchdog stop took about 2.07/2.03 seconds. Both bounded probes
verified power/brightness restoration and configuration/fallback preservation.
These are software recovery checks on NL82K2, not a new physical unplug or KDE
permission-revocation test. Earlier physical/revocation evidence remains separate.

The final gates pass 79 application tests (one ordinary-CI ignored operator pipe
benchmark), 11 streaming tests and 3 Linux interop tests, with warnings-denied
Clippy and formatting. CI now runs interop tests directly as well as the stream
crate. Isolated relocated package install/upgrade/rollback/autostart/service
exclusion/uninstall preservation passes. Colour algorithms and USB ACK handling
were not changed for this backend adoption.

No new NL82K1, suspend, raw HDR, colourimeter, optical latency, power or sustained
game-load verification is claimed. Evidence contains numerical timings and checks,
without user configuration, portal tokens, screenshots or screen colour samples:
[`perf/streaming-adoption-2026-10-15`](../perf/streaming-adoption-2026-10-15).

## Operator reproduction and rollback

Use only one output owner. Read-only capture probes still add capture/GPU load;
stop mirroring before an uncontended comparison. The bundled capture helper accepts
`--sync-self-test` (private render-node objects, no capture/USB), `--dma-buf`,
`--dma-buf-explicit` and `--sync-suite` (four bounded phases). Full-pipeline parity
uses `NANOLEAF_STREAM_PARITY=1` with the app's `--stream-capture-probe CONFIG 8`;
add `NANOLEAF_VULKAN_VALIDATE=1` when validation layers are installed. Include the
helper environment flag only when explicitly testing timeline mode.

`scripts/profile_native_lifecycle.py --stream --binary BUNDLE/bin/nanoleaf-native
--config PRIVATE_COPY --output PRIVATE_RESULT` exercises the owned-worker recovery
paths at limited brightness. Quit the original output owner first and restore its
running state afterwards. The harness never edits the real configuration.

`nanoleaf-native --capture-backend EXISTING_CONFIG xdg-portal` stores only the
backend choice through the stale-checked transactional writer and retains an
exact backup. It does not start or reload mirroring. For backend-only rollback,
select `kwin-dbus`, then reload/restart. Managed `--rollback-native` changes the
binary, not the saved backend or timing fields. Restore an exact old config only
after checking for subsequent calibration edits; never overwrite newer settings.
