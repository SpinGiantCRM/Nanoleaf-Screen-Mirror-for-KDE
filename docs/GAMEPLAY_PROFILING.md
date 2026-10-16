# Gameplay profiling and Python retirement — 2026-10-16

The app was tested while the user played Minecraft on the real KDE/Wayland
session. Tests used the saved portal/PipeWire/Vulkan backend, manual 48 zones,
Target60, reference colour, measured calibration and acknowledged temporal
dithering. No foreground test window, synthetic pattern, game setting or saved
configuration was changed. Mirroring restarted between bounded comparison runs.

## Results and limits

Eight 60-second windows used the same installed reference binary: ABBA for the
GPU-wait experiment, then ABBA for complete versus qualified shorter USB frames.
These are real-workload observations, **not controlled causal benchmarks**.
Scenes changed, low-priority two-job builds/tests ran during part of collection,
and the first control in each family reported inherited nice -8 versus -4 in
later runs. Process nice was not collected in those comparisons; the observer
now records it. No experiment was promoted from these comparisons.

The table shows medians of one-second status snapshots; it does not represent a
complete per-frame trace. Work-to-write ends at the final host HID write; work-to-ACK
includes the receiver acknowledgement. Neither measures emitted-light response.

| Run | Completed capture ms | Queue ms | USB ms | Work-to-write ms | Work-to-ACK ms | Actual ACK/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Serial waits A1 | 6.21 | 7.76 | 19.99 | 17.49 | 33.70 | 51.12 |
| Batched waits B1 | 4.37 | 8.48 | 20.99 | 17.86 | 34.09 | 49.25 |
| Batched waits B2 | 4.37 | 7.13 | 19.00 | 16.49 | 31.63 | 52.77 |
| Serial waits A2 | 6.31 | 8.89 | 19.99 | 19.48 | 34.94 | 51.53 |
| Full USB A1 | 6.88 | 9.03 | 20.00 | 20.12 | 36.43 | 49.22 |
| Short USB B1 | 6.43 | 7.90 | 20.00 | 17.78 | 33.44 | 50.43 |
| Short USB B2 | 7.08 | 6.90 | 19.00 | 18.44 | 34.28 | 51.89 |
| Full USB A2 | 6.60 | 8.20 | 19.99 | 18.43 | 34.61 | 51.52 |

Batched waits reduced the capture-stage duration in both appearances, but the
first pair's snapshot work-to-write and work-to-ACK became slightly worse. Keep
`NANOLEAF_BATCH_GPU_WAITS` **off by default**. Moving a host wait is not itself a
whole-app response improvement; earlier repeatability limits still apply.

Short updates used shortened prefixes in 1,256 and 660 acknowledged updates
during the two short-policy windows, respectively. Full-policy windows omitted none. They
help when a suffix stays unchanged; whole-strip motion still needs complete
frames. The reversed short/full pair's work-to-write snapshots were effectively
identical. This does not reproduce the large controlled static-tail benefit
universally in gameplay, nor invalidate the exact protocol/retention tests.
Keep the existing qualified policy and `NANOLEAF_SHORT_UPDATES=0` fallback.

Colour finishing remained about 0.02–0.03 ms. In the GPU-wait windows, parent CPU
was about 0.74–0.76% of one logical core and helper CPU about 2.88–3.10%; combined
RSS was about 158 MiB. These exclude the compositor, graphics driver, GPU, game
and on-demand settings window. No app-attributed power claim is made.

## What this directs next

The meaningful remaining delay is USB transaction time plus waiting for a fresh
prepared frame, rather than colour arithmetic. The next scheduling experiment
would need equal-priority runs and timestamped source changes under matched
load; arbitrary gameplay snapshots cannot establish screen-event latency.
A demand/phase-coordinated sampler would also need to preserve the target ceiling,
source timestamps, compositor-buffer ownership, calibrated temporal feedback and
ACK-based dither phase. It is not enabled or asserted to be an improvement here.
Do not add packet overlap, skip ACKs, raise FPS blindly, weaken colour checks or
change firmware to manufacture a benchmark gain.

## Delivered changes

- Added `scripts/profile_gameplay.py`: bounded observation of an existing service,
  one status/process snapshot per second, no output commands or game focus changes.
  CPU ticks/RSS, actual nice and existing timing metadata are collected. Lost
  service snapshots remain errors rather than fabricated zero measurements.
- Retired the Python/PyQt app, C DRM helper, optional Python bridge, app-specific
  tests/generators, wheel/AUR packaging and obsolete release/CI jobs. Python
  operator/build scripts remain; native runtime still needs neither Python nor Qt.
- Preserved all nine original native fixture files byte-for-byte. Rust tests
  continue calibration, geometry, complete pipeline, colour and protocol reference
  comparisons without importing the deleted implementation. Git history retains
  pre-retirement source and generators at `85f59888d373667f48651f8cbb2333b8605bfbc5`.
- Updated active install, diagnostics, contribution, prediction and support docs,
  native error messages and package tests. Package tests still preserve arbitrary
  unrelated files and configuration through paired upgrade/rollback/uninstall.

Local pipx Python and obsolete user launchers/import hooks were removed; generated
legacy development files were moved out of the active checkout. A separate
Pacman-owned Python 1.9.1 package remains because noninteractive sudo requires an
administrator password. Its two elevated DRM helpers also belong to that package.
Its launcher is locally hidden. Removal is `sudo pacman -R nanoleaf-kde-sync`;
the existing unowned `/etc/udev/rules.d/60-nanoleaf-kde-sync.rules` remains for
native USB access. No dependencies, shared calibration directory or system Python
interpreter should be removed as part of that command.

## Validation and installed state

The serial native release gate passed 183 Rust tests, all-target Clippy and
formatting for core/application/capture workspaces, six trace-decoder tests and
two repository cleanup tests. The ignored private-D-Bus owner-loss/recovery test
passed separately. Package tests and isolated real-binary bundle smoke passed.
Cached cargo audit for the app reported no vulnerabilities; hosted fresh scans
are separate. No new physical reconnect, suspend or optical test is claimed.

Installed version `e77e42b22710b0b4cc41b60e7699d69809008cde9f1b168413f300380e4187bc`
contains the paired app/helper; previous versions remain for native rollback.
A final one-minute installed-build gameplay smoke produced 3,226 acknowledged
packets, including 468 shortened packets, between endpoint snapshots. Actual
nice was -8 for both processes throughout that smoke. Mirroring remains running
with experimental GPU waits off, saved selected backend and qualified short
updates on. Controller power/brightness read back identically as 1/16 around the
USB comparison; configuration SHA256 remains byte-exact:
`a5d9b604c8ff68adf8a9321cc9fb578d4c2468c00a279612d66312f800049933`.

Normalised evidence and binary/source-record hashes are in
[`perf/gameplay-2026-10-16`](../perf/gameplay-2026-10-16/README.md). Raw private
metadata and retired local developer files are retained outside the repository.
