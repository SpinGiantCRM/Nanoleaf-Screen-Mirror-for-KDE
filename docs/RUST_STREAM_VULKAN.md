# Rust streaming and Vulkan DMA-BUF experiment

Date: 2026-10-13. Branch: `codex/full-rust-rewrite`.

15 October update: GPU streaming is now enabled on the tested host after the
user's response/colour comparison, full calibrated parity and recovery checks.
An opt-in explicit timeline prototype is implemented but remains experimental;
the initial idle benchmark did not show a latency benefit. See
[current adoption, measurements and limits](STREAMING_ADOPTION.md). The text below
records the original prototype checkpoint.

## Implemented and tested

The capture prototype now receives a single monitor through the standard
xdg-desktop-portal ScreenCast permission flow and a restricted PipeWire remote.
It negotiates full-resolution packed 8-bit frames and either shared CPU memory
or genuine Vulkan-importable DMA-BUF modifiers. The RTX 4080 SUPER / NVIDIA
615.78.08 host delivered 3840 × 2160 BGRA with NVIDIA modifier
`216172782120099860`. The portal's 2560 × 1440 logical-size metadata did **not**
reduce the captured image resolution.

`native/stream-probe` owns permission and frame consumption. `native/linux-gpu`
contains the small, documented unsafe Linux/Vulkan boundary. `native/gpu-probe`
contains the safe texture compute shader and the existing upload experiment.
Normal application/core code still forbids unsafe code. This boundary is
experimental and runs in a supervised capture child for the optional app backend: a GPU completion failure terminates that probe rather than returning
a buffer that the GPU may still be reading. It is not linked into the normal
tray process.

The import path checks the actual packing, dimensions, plane count, modifier,
stride and offset. It queries Vulkan importability and sampled/transfer format
support; it never treats a tiled DMA-BUF as a linear CPU mapping. The prototype
supports one packed BGRA/RGBA plane with implicit synchronization. It exports
and waits for the producer's DMA-BUF read fence, acquires foreign queue ownership,
executes compute, waits for completion and returns foreign ownership before
PipeWire can reuse the buffer. Submission goes through wgpu's synchronized
queue. Explicit SyncTimeline and extra planes are rejected; those are future
support, not silently ignored metadata.

Imported images are reused in a bounded cache of four compositor buffers,
identified by DMA-BUF inode/device plus the complete format/layout. A retained
Vulkan allocation keeps the inode alive, avoiding numeric-FD reuse collisions.
New layouts get new imports; closing the stream releases the cache. Corrupt,
gap and empty startup buffers are counted and discarded before colour sampling.

No privileged device access, compositor permission bypass, KWin private
screencast protocol or global driver/settings modification was introduced.
The native probe's permission token lives privately in its own configuration
directory, separate from the Python fallback's token and application config.
Submitted tokens are invalidated before reuse and replaced only by a successful
portal response. Real restoration was tested: the second session opened in
16.51 ms without another monitor picker. The token is not included in evidence.

## Colour contract and parity

KWin's monitor source selects ARGB8888, and its screencast layer retains the
sRGB colour description. The observed PipeWire format supplies unspecified
colour metadata (zero primaries/transfer/range/matrix), so an 8-bit frame alone
must **not** be generalized into a raw-HDR contract. This experiment verifies
encoded values and the KWin sRGB path; it does not claim PQ, FP16, wide-gamut
capture, a better HDR tone mapper, or measured emitted-light accuracy.

The shader reads a non-sRGB UNORM texture, reconstructs exact RGB8 codes and
builds integer per-channel histograms for every configured zone pixel. It does
not downscale or decimate. The same CPU float64 histogram reduction/LUT computes
linear RGB, encoded means and variance. Alpha-zero pixels map to black;
premultiplied input and undefined-alpha RGBx/BGRx import are rejected until
explicitly supported. Black, grey and white remain neutral.

Evidence:

- 40 synthetic texture comparisons cover BGRA/RGBA, all 256 channel codes,
  mixed colours, black/grey/white, clipping and empty rectangles. All fields
  exactly matched the CPU sampler.
- The initial live upload stream checked 32,784 zone results exactly.
- The final three-phase run checked 9,264 upload-zone results and 384 imported
  DMA-BUF zone results exactly. DMA diagnostics periodically read back a full
  frame as a CPU oracle; ordinary sampling reads back only 147,456 histogram
  bytes for 48 zones and uploads **zero** full-frame bytes.
- A validation-layer import run delivered 236 frames and 384 exact zone
  comparisons with no Vulkan validation errors. Logs contained the loader's
  expected notice that the validation layer was explicitly enabled.
- The app's new `direct_plan` / `process_sdr_samples` interface shares the
  existing calibration, physical mapping, smoothing, temporal accumulation,
  quantization and actual-ACK history implementation. 240 evolving-frame tests
  produced exactly equal sampled and final LED codes through both entry points,
  including calibrated matrices, brightness, dither and skipped-output history.

The optional native app backend now supervises this capture child. Only small
prepared colour records cross into the tray/HID actor; GPU ownership and full
screen buffers stay in the child. The child receives a validated configuration
snapshot, and actual USB acknowledgements feed its temporal/quantization history.
Only the latest prepared frame is retained. Stop kills/releases the owned capture
child while keeping the tray alive; sharing denial, revocation or child failure
stops mirroring and requires an explicit Start rather than switching interfaces.

Exact letterbox detection shares the CPU detector's ordered float32 luminance
calculation and threshold. It reads only the necessary texture rows/columns,
remaps the configured zones, then computes complete integer zone histograms.
After eight sparse copies, broad bars or black screens use one full readback for
the same detector, bounding GPU round trips without reducing pixel coverage.
Privacy masks, weighted kernels and adaptive palette analysis keep the full-pixel
CPU path inside the child; their configured policies are never silently disabled.

The real user's reference/high/letterbox configuration passed 360 live complete
CPU/GPU pipeline comparisons: sampled colours, final calibrated LED codes and
sampling modes were exactly equal on every delivered frame. Validation mode
reads back reference pixels and is excluded from performance measurements.
Another 30 synthetic letterbox/threshold cases, 40 exact row/column extraction
comparisons and 40 changed-zone hardware comparisons passed. Real configuration
and both profiles remain unchanged. KWin is still the default; `xdg-portal` is
explicitly selectable in Advanced / Troubleshooting.

## Measurements and limitations

Final source/binary checksums, raw records and summary are in
`perf/rust-stream-vulkan-2026-10-13`. The release run used three successive
8-second phases on the same portal monitor session, with a negotiated maximum
of 30 capture FPS. First-frame startup is excluded from steady callback medians;
DMA diagnostic full readbacks and cold cache imports are also excluded there.
Process CPU counters include all probe threads and initialization during each
phase. They exclude KWin, GPU activity, USB, UI and whole-system power.

| Capture/sample phase | Valid frames | Callback median / p95 | Process CPU, one core | Active RSS |
| --- | ---: | ---: | ---: | ---: |
| PipeWire MemFd + CPU sampler | 211 | 8.674 / 9.668 ms | 22.80% | 133,968 KiB |
| MemFd + CPU oracle + uploaded-frame Vulkan | 193 | 10.589 / 13.030 ms | 24.74% | 217,340 KiB |
| Cached DMA-BUF + Vulkan | 239 | 0.525 / 1.247 ms | 2.25% | 122,444 KiB |

These are live desktop experiments, not controlled identical-content whole-app
benchmarks. Content, scheduling and GPU clocks can change between phases/runs.
A preceding corrected run measured CPU 9.430 ms / 25.08% and DMA 1.643 ms / 2.37%.
A separately restored DMA session measured 1.357 ms on warm non-diagnostic frames.
Keep that observed variability visible; do not promise a fixed speedup or FPS.

The first uncached DMA run measured 4.135 ms versus the later cached runs. That
first CPU harness rebuilt a LUT per zone, so its CPU timing is retained as
historical raw evidence but is **not** the corrected reference. The complete
source upload benchmark already showed why upload alone is a poor adoption
choice. Both corrected live suites are preserved.

The final release run had no gaps or corrupt frames in its DMA phase; an earlier
run counted four skipped startup buffers/gaps. These counts are not proof of
zero dropped display frames: KWin's content-driven stream can be below its
negotiated maximum when content is unchanged. Header PTS age is compositor
presentation-to-callback age, not optical screen-change-to-LED latency. Final
PTS-age medians were 19.25 / 24.05 / 9.06 ms, with variable tails, respectively.

Each final phase returned to 36 open descriptors after close (active DMA: 49).
The restored run also released its capture descriptors. Retained allocator and
Vulkan runtime memory explain why RSS need not return to a cold-process baseline.
A roughly 120 MiB GPU probe is **larger** than the previously measured roughly
79 MiB Rust service, and these are different processes/workloads. No app-wide
memory saving, system power reduction or USB/optical latency improvement is
claimed. The real calibration/config hash stayed
`b470ea82ac1568cf99f4762f6914e4aa295bd3422527e9eb3ca046b52272d1a4`.

## Integrated app measurements and lifecycle (2026-10-13)

Raw records and source/binary hashes are in `perf/rust-stream-app-2026-10-13`.
These sequential five-second active windows use the same unchanged manual-48,
reference/high/letterbox configuration and actual NL82K2 USB acknowledgements.
The changing desktop is not controlled identical content. CPU includes all
threads and 20 Hz status requests; GPU/compositor/settings processes are excluded.
The final streaming window overlapped an isolated settings UI validation; its
shared graphics libraries affect PSS apportionment. RSS sums double-count shared
pages. No whole-system power reduction is claimed.

| Native backend | Parent + capture-child CPU, one core | Summed RSS | Capture / colour median | USB ACK median | Rolling ACK FPS median |
| --- | ---: | ---: | ---: | ---: | ---: |
| KWin Screenshot2 | 59.68% | 80,224 KiB | 23.595 / 4.237 ms | 7.851 ms | 35.36 |
| Portal + Vulkan DMA-BUF | 4.18% | 144,768 KiB | 1.629 / 0.038 ms | 20.996 ms | 47.81 |

The initial integrated full-readback run produced 300 acknowledged frames and
measured 21.674 ms capture / 3.912 ms colour medians. Sparse letterbox analysis
substantially reduces that avoidable readback. Earlier sparse runs measured
4.298 ms capture with USB active and 11.147 ms in a read-only worker test;
retain variability rather than promise a fixed capture speed. The read-only
worker delivered 455 frames in eight seconds, no prepared drops. The final USB
window deliberately coalesced 50 excess prepared frames while acknowledging 238
new frames, avoiding a backlog. These are separate workload windows, not dropped
display-frame counts or claimed 60 FPS physical output.

Streaming response is compositor presentation PTS-to-USB ACK (median 34.780 ms);
KWin response starts at the screenshot request (36.366 ms). The origins differ,
so subtracting those columns is invalid. Neither measures optical end-to-end
latency. USB acknowledgements are currently the dominant streaming stage; further
colour-math micro-optimization has little measured benefit and must not remove
ACKs, calibration or accuracy guards.

Real checks passed Stop with no capture child, exclusive zone preview, restart,
SIGTERM of only the owned capture child, continued tray availability, no automatic
capture reacquisition after failure, explicit restart and final controller
power/brightness restoration with readback. No physical unplug/suspend or NL82K1
hardware check was performed. A private D-Bus fixture verifies Session.Closed and
connection loss even without a PipeWire error. Fatal restricted-remote PipeWire
errors also stop the worker. Actual isolated KDE settings Save/Apply selected
`xdg-portal`, kept the window open and preserved the complete calibration table,
both measured profiles and an exact copied-config backup.

Local gates passed: 38 native app tests, four capture/permission tests, Rust 1.95.0
Clippy/format, complete Python/native colour/protocol replay, 1,613 Python tests
(23 optional-bridge skips), 77.83% coverage, Ruff/format, mypy and diff checks.
A hardware-independent streaming CI job was added; hosted CI has not been run.
This completes the integrated Vulkan checkpoint, not all feature/adoption gates.

## Reproduce

```sh
cargo build --release --features gui --locked --manifest-path native/app/Cargo.toml
cargo build --release --bins --locked --manifest-path native/stream-probe/Cargo.toml
# Read-only eight seconds AFTER capture permission/first frame:
NANOLEAF_STREAM_PARITY=1 native/app/target/release/nanoleaf-native \
  --stream-capture-probe /path/to/config.toml 8
native/app/target/release/nanoleaf-native --stream-capture-probe /path/to/config.toml 8
# Bounded actual strip output, brightness limit + restoration/readback:
native/app/target/release/nanoleaf-native --stream-live-probe /path/to/config.toml 8
.venv/bin/python scripts/profile_native_lifecycle.py --stream --output /tmp/stream-lifecycle.json
```


Build requirements include PipeWire development headers, pkg-config/Clang,
Rust 1.95+, and a hardware Vulkan driver for live GPU tests.

```sh
cargo build --release --locked --manifest-path native/stream-probe/Cargo.toml --bins
native/stream-probe/target/release/texture-oracle
native/stream-probe/target/release/nanoleaf-stream-probe --suite
# Subsequent permissions can restore; no strip output in these commands.
native/stream-probe/target/release/nanoleaf-stream-probe --dma-buf
NANOLEAF_VULKAN_VALIDATE=1 VK_INSTANCE_LAYERS=VK_LAYER_KHRONOS_validation \
  native/stream-probe/target/release/nanoleaf-stream-probe --dma-buf
cargo +1.95.0 clippy --manifest-path native/stream-probe/Cargo.toml --all-targets --locked -- -D warnings
cargo +1.95.0 test --manifest-path native/stream-probe/Cargo.toml --locked
```

The GUI/USB fallback, desktop launcher, autostart, helper capabilities and saved
calibration were not replaced. Remaining app work includes optional sampling/
analysis parity, prediction after core refinement, standalone packaging/rollback,
and sustained/physical recovery tests. Raw HDR and DRM remain gated.

## Primary contracts researched

- [PipeWire DMA-BUF negotiation and synchronization](https://raw.githubusercontent.com/PipeWire/pipewire/master/doc/dox/internals/dma-buf.dox).
- [PipeWire Rust bindings and examples](https://pipewire.pages.freedesktop.org/pipewire-rs/pipewire/).
- [KWin monitor source](https://raw.githubusercontent.com/KDE/kwin/Plasma/6.7/src/plugins/screencast/outputscreencastsource.cpp),
  [format/sync negotiation](https://raw.githubusercontent.com/KDE/kwin/Plasma/6.7/src/plugins/screencast/screencaststream.cpp),
  [default sRGB output layer](https://raw.githubusercontent.com/KDE/kwin/Plasma/6.7/src/core/outputlayer.h).
- [Portal session closure contract](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Session.html).
- [Vulkan external-memory interoperability](https://docs.vulkan.org/guide/latest/extensions/external.html).

KWin's private Wayland screencast protocol explicitly discourages regular-client
use. This prototype uses the standard portal and does not register additional
restricted compositor interfaces.
