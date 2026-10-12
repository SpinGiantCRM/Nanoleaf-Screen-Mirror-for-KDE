# Recovery measurement evidence

Reference commit: `43fcf13381b5d842f9a5f495b226f8b8626d8121` (1.9.3).
Environment/methodology, limitations and interpretation are in
[`docs/RUST_MIGRATION_RESEARCH.md`](../../docs/RUST_MIGRATION_RESEARCH.md).

Run from the repository root with the existing development venv:

```bash
.venv/bin/python perf/recovery-2026-10-12/measure_baseline.py --output /tmp/offline.json
.venv/bin/python perf/recovery-2026-10-12/compare_sampling.py
```

The offline harness runs three production benchmarks plus separate fresh-process
import/memory probes. The comparison script contains the previous full-pixel
mean/variance calculation alongside the current implementation and uses identical
seeded frames, 48 tight edge zones, three warmups and 20 timed samples per method.
It measures sampler work, not capture/USB or the entire colour pipeline.

Live capture/USB tests require an available KDE session and exclusive use of the
configured strip. They run a short low-brightness pattern sequence and a ten-second
service window. A live test temporarily changes device brightness and power, ends
with black, and restores the prior brightness/power state. It cannot restore the
prior LED image, because the protocol cannot read it back. The FPS override changes
only the in-memory copy of the existing Target FPS setting, never saved config:

Service-window tests inject a real driver using the conservative initial 64-byte
report path, without initial large-report/write-only probing or mailbox mode.
Capture/mapping/processing use the existing config. The headed tray test separately
exercised normal production driver construction.

```bash
.venv/bin/python perf/recovery-2026-10-12/measure_baseline.py --live --output /tmp/live.json
.venv/bin/python perf/recovery-2026-10-12/measure_baseline.py --live --fps-override 30 --output /tmp/live-30.json
```

Do not run timing experiments concurrently with tests or other benchmarks. Use
matched desktop content for live comparisons. Synthetic frames contain no screen
content. JSON contains stage timings and operational metadata, not screenshots.
The original uninstrumented live run predates the processing-call wrapper; direct
processing timings are available in the 30 FPS retry and subsequent runs. Some
runtime latency samples repeat the most recently measured stage value. Rolling
latency windows are not raw per-frame traces. `end_to_end_live_ms` starts at capture
completion, excludes acquisition/presentation and does not measure emitted light.

Files:

- `production-before.json`: original CI benchmark and baseline comparison passed.
- `offline-before.json`, `offline-after.json`: three synthetic benchmark runs and
  isolated import/PSS/RSS probes. These do not construct a real tray.
- `live-before.json`: original configured 60 FPS runtime, failed before first output.
- `live-before-30fps.json`: failed in-memory 30 FPS retry with processing instrumentation.
- `live-histogram-prototype.json`: exploratory mean-only prototype, not the final
  implementation; briefly overlapped another profiling command.
- `live-after.json`: final shared-histogram implementation, original settings.
- `live-after-repeat.json`: independent second successful window, original settings.
- `sampling-comparison.json`: matched old/new computation and numeric differences.
- `tray-lifecycle.json`: real KDE QApplication/tray Start/Stop/restart/Settings run;
  optional background update checker disabled, visibility checked through Qt.
- `validation.txt`: local test, coverage, lint/type/version results. Hosted CI and
  packaging/release/runtime dependency audit/Semgrep gates were not run. Commit
  hooks did pass Bandit and Gitleaks.

CPU percentages are relative to one core and can exceed 100%. Failed/stopped
service CPU is not a successful steady-state mirroring baseline. Memory probes
are snapshots; retained GUI allocations after Settings differ from cold idle.
There are no Rust, power or optical-colour measurements in this evidence set.
