# Fresher frames under serial USB backpressure

On the tested 3840×2160, approximately 240 Hz DP-1 setup, increasing the existing
Target FPS from 60 to 240 reduces the age of the frame waiting for the next USB
transaction. The strip still receives roughly 48 acknowledged updates/second
on this workload: **240 is a capture/output target, not delivered LED FPS**.
No new rate control, prediction mode or USB command overlap was added.

This addresses L2 in the [improvement report](IMPROVEMENT_RESEARCH_2026-10-14.md).
The single latest-frame slot already avoids an accumulating queue. Its retained
frame can nevertheless be nearly one capture period old when the preceding USB
transaction finishes. Sampling more frequently makes a newer frame available
without changing the serial, acknowledged transport or the colour transform.

## Measured comparisons

Two separate ABBA comparisons used the same repeating fullscreen neutral SDR
ramp, one selected monitor, manual 48-zone mapping, reference/high colour mode,
letterbox analysis, saved calibration and acknowledged dithering. Each probe ran
12 seconds at controller brightness 10 and restored original power/brightness.
The first 74 acknowledged updates were excluded; every subsequent fresh update
was included. Cached-work measurements were not mixed with fresh-frame clocks.

| Target FPS in each ABBA run | Samples | Queue p95 | Work-to-host-write p95 | Presentation-age-at-ACK p95 | App + helper CPU, one core |
| --- | ---: | ---: | ---: | ---: | ---: |
| 60 | 490 | 15.97 ms | 21.18 ms | 40.88 ms | 3.08% |
| 120 | 490 | 8.49 ms | 13.66 ms | 33.60 ms | 5.17% |
| 120 | 490 | 8.70 ms | 13.79 ms | 34.14 ms | 5.27% |
| 60 | 489 | 16.08 ms | 21.03 ms | 40.24 ms | 3.28% |
| 120 | 490 | 9.17 ms | 14.08 ms | 34.21 ms | 4.46% |
| 240 | 491 | 5.47 ms | 10.30 ms | 30.53 ms | 6.86% |
| 240 | 491 | 5.52 ms | 10.22 ms | 30.13 ms | 6.96% |
| 120 | 490 | 8.98 ms | 13.87 ms | 34.14 ms | 4.60% |

These are per-run nearest-rank percentiles, not pooled percentiles or an optical
latency claim. The roughly 21 ms USB transaction remains. Presentation metadata
age is a separate software clock and includes compositor/USB effects; percentile
columns must not be added together. Comparing the first and last rate groups
suggests approximately 11 ms less p95 work-to-write time on this synthetic
workload. The direct ABBA evidence is 60↔120 and 120↔240, not a randomized
60↔240 optical trial. CPU rose by roughly four percentage points of one core;
GPU, compositor CPU, scene rendering, whole-system power and gaming contention
were not measured. Memory differences between runs are not a claimed saving.

The scene verifies focus/fullscreen after warmup and rejects sustained paint
throttling (more than 5% of logical updates missing). It retains maximum paint
gaps rather than discarding occasional OS/compositor hitches. Successful runs
painted 1,797–1,801 logical updates in approximately 15 seconds; focus/fullscreen
checks were clean. This verifies the requested workload, not panel scanout.
An earlier exploratory comparison lacked these checks and suffered substantial
paint throttling. A preliminary stricter rule rejected a single approximately
30 ms paint gap despite over 99% tick coverage; it was replaced before the two
reported comparisons. Neither preliminary pass is used as clean ABBA evidence.
Other desktop/GPU activity remains uncontrolled, and these short runs do not
establish long-term tails or behaviour on another monitor or computer.

## Colour, configuration and delivery

The 240-target capture-only oracle verified **610 exact complete-colour outputs**
with Vulkan validation enabled and empty validation stderr. That separate,
slower correctness run is not throughput evidence. Existing neutral/black,
temporal, Python-reference and USB protocol regressions also pass. No colour
sampling, transfer curve, calibration, dither phase policy or HDR interpretation
was changed; capture remains display-referred SDR on the validated KDE contract.

The higher target is experimental. A temporary change of only the existing
`fps` field was reverted to the exact original config, including Target FPS 60,
while the static-to-change comparison is pending. The first traced static trial
lost foreground focus and was discarded; the user deferred another foreground
run. No higher target is promoted from moving-scene timings alone. Calibration,
unknown fields, comments, monitor/backend selection and global defaults remain
unchanged. Previous immutable native versions and Python launchers are retained.
The tested recovery build remains installed; the app is closed after cleanup.

Before the config rollback, the installed pair completed USB smoke and post-login mirroring
checks. The user reported the longer check was **“Lit and following correctly”**.
That is useful visible-function feedback, not a measured optical speedup or
photometric colour comparison. [Session recovery](SESSION_RECOVERY.md) records
the separate lock/unlock checks and their observation limits.

## Reproduce

Build the operator scene with existing GUI dependencies:

```bash
cargo +1.95.0 build --release --manifest-path native/app/Cargo.toml \
  --features gui --bin capture_scene --locked --offline
```

`capture_scene EXISTING_CONFIG SECONDS` requires a sole connected output matching
the configured monitor, runs for 1–180 seconds, and closes on Escape. It neither
captures images nor accesses USB/config writes. It draws requested encoded SDR
codes 64–192 with a small centre marker; these are not calibrated monitor nits.

`scripts/profile_controlled_response.py` defaults to a plan. Supply a native
bundle's app path, scene path, existing config and a fresh private evidence
directory. Explicit `--run` starts four bounded probes and temporary config
copies; `--rates 120 240` selects the second comparison. Quit the normal tray
first. Keep the scene focused, with no overlapping operator probes. The script
checks controller restoration and real-config byte identity for every run.

Numeric aggregates and hashes: [benchmark evidence](../perf/controlled-response-2026-10-16/README.md).

For a static-to-change comparison, use `--pattern steps --strace /path/to/strace
--hidraw /dev/hidrawN` with both options on the same command line. The parser
matches alternate grey payload states against recorded paint-request times,
requires complete HID writes plus cleanup, checks wall/monotonic clock drift,
and rejects lost focus or missing transitions. Trace only the main HID actor;
keep all raw payloads private. Ptrace adds overhead: compare identically traced
runs and do not combine their timings with the untraced table above. Paint
requests precede compositor presentation, and host writes precede emitted light.
Presentation timestamp resets alone do not establish changed image content.
