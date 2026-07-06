# Performance and benchmarking

## Benchmark command

```bash
nanoleaf-kde-sync-benchmark
```

Synthetic benchmark measuring zone sampling and full `process_frame` pipeline throughput. No KDE session or USB hardware required.

Options are defined in `src/nanoleaf_sync/tools/benchmark.py` (resolution, zone count, iterations).

## What it measures

- **Zone sampling:** `zone_colors_array` hot path on a synthetic frame
- **Full pipeline:** `process_frame` including smoothing, colour style, and LED calibration defaults

Results are printed as mean/median milliseconds per iteration.

## Regression gate

CI compares output against [`perf/baseline.json`](../perf/baseline.json). A regression fails the benchmark job when timings exceed baseline tolerances.

## Updating the baseline

After intentional performance changes:

1. Run `nanoleaf-kde-sync-benchmark` locally on a representative machine
2. Update `perf/baseline.json` with new reference values
3. Note the change in the PR description

## When reporting lag

1. Set **Target FPS** realistically (60 vs 120)
2. Run **Measure active backend latency** (Settings → Advanced)
3. Run `nanoleaf-kde-sync-benchmark` and attach JSON output
4. Note capture backend, 4D sync on/off, and smoothing settings
5. See [4D sync](4D_SYNC.md) for latency trade-offs

## Standard vs 4D sync

Compare mirroring with 4D sync disabled vs enabled using the same backend. Benchmark CLI uses default `AppConfig`; for 4D-specific pipeline timing, set `sync_mode=4d` in config and re-run integration tests (`tests/test_4d_speed_path.py`).
