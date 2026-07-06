# Diagnostics guide

Map symptoms to the right diagnostic action, expected output, and what is safe to attach to a GitHub issue.

## Quick reference

| Symptom | Action | Expected output | Attach to issue | Privacy risk |
|---------|--------|-----------------|-----------------|--------------|
| App won't start / tray missing | `nanoleaf-kde-sync-doctor` | Pass/fail checks for device, capture, config | Doctor text output | Low — no screen pixels |
| Strip not detected | Doctor + Settings → Advanced USB section | VID/PID, permission hints | Doctor output | Low |
| Wrong colours / HDR issues | Settings → Colour; live diagnostics HDR path | Display preset, compositor HDR, SDR white | Diagnostic bundle metadata (not raw frames) | Low |
| Wrong zone mapping | Settings → Strip setup; zone report export | Corner anchors, side counts | Zone report JSON | Low |
| Capture/backend failures | Advanced → Re-test backends; `AUTO_BACKEND.md` | Probe order, selected backend, errors | Backend probe log from diagnostics | Low |
| Lag / stutter | Advanced → Measure latency; benchmark CLI | Latency ms, pipeline timings | Benchmark JSON + latency report | Low |
| Flicker | Help & Diagnostics → Colour & flicker; flicker lab | Per-zone delta summaries | Flicker scenario output | Low |
| Sampling looks offset | Export live/synthetic sampling overlay | PNG/JSON overlay paths | Overlay images | **Medium** — shows screen layout |
| Full support bundle | Help & Diagnostics export | Zip with config redaction | Bundle after reviewing contents | **Review** — may include paths |

## Settings → Advanced actions

| Button | Use when | Output |
|--------|----------|--------|
| **Run self-check** | General health before reporting | Pass/fail summary in label |
| **Capture one diagnostic frame** | Verify capture works at all | Frame dimensions, backend name |
| **Export live sampling overlay** | Zones don't match screen edges | Overlay image + zone metadata |
| **Export synthetic sampling overlay** | Isolate mapping without live capture | Synthetic geometry overlay |
| **Export zone report** | Mapping/calibration disputes | JSON zone + anchor report |
| **Export latency report** | Lag complaints | Timing breakdown JSON |
| **Edge locality diagnostic** | Bleed vs accuracy tuning | Per-locality comparison |
| **Color accuracy diagnostic** | Neutral grey/white wrong | Accuracy metrics JSON |
| **Re-test backends** | Wrong or stale backend | Fresh probe results + recommended backend |
| **Test xdg-portal** | Portal permission issues | Portal session status |
| **Benchmark xdg-portal** | Portal performance | Portal timing summary |

## CLI commands

```bash
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync-benchmark
```

## Before attaching to GitHub

1. Run doctor and note KDE/Wayland version, strip model, capture backend.
2. Prefer diagnostic bundle **metadata** over raw screen captures when possible.
3. Redact home directory paths if sharing publicly.
4. See [Security](SECURITY.md) for the full threat model.

## Related docs

- [Troubleshooting](TROUBLESHOOTING.md) — symptom-first fixes
- [Performance](PERFORMANCE.md) — benchmark workflow
- [Feature matrix](FEATURE_MATRIX.md) — what is implemented vs experimental
