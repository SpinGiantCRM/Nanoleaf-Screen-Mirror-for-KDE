# Latency Plan

This document explains practical latency validation for capture backends and how results should inform backend policy choices.

## Goals

- Keep capture latency low and predictable.
- Preserve reliability under normal desktop load.
- Make backend decisions observable via smoke-test/doctor output.

## Backend expectations

- `kmsgrab`: often fastest where DRM/KMS and bindings are available.
- `kwin-dbus`: compatibility baseline on KDE Plasma.
- `xdg-portal`: portability path for launch-context/compositor permission constraints.

## Measurement workflow

Use the same session and similar desktop activity when comparing backends.

1. Set explicit backend in config (`prefer_backend = "<backend>"`).
2. Restart service/tray.
3. Run:

```bash
nanoleaf-kde-sync-smoke-test
nanoleaf-kde-sync-doctor --capture
```

4. Repeat for all target backends.
5. Return to `prefer_backend = "auto"` after choosing policy.

## What to capture in test notes

For each backend and scenario (idle + moderate desktop activity):

- Capture success/failure outcome.
- Effective backend + selection reason from smoke-test.
- Subjective responsiveness (fast/acceptable/slow) while mirroring.
- Error class if failures occur (`backend-init`, `capture-failed`, `timeout`, etc.).

## Policy guidance from findings

Use `auto_probe_policy` as an operational control:

- `first-run`: stable systems where startup probe churn is undesirable.
- `each-boot`: dynamic systems where startup verification is preferred.
- `on-change`: default; best when hardware/session context can change.

If behavior regresses after updates, reset probe metadata and let auto policy re-evaluate (see `docs/TROUBLESHOOTING.md`).

## Practical tuning after backend choice

If capture backend is healthy but output still feels slow, tune pipeline parameters in order:

1. `zone_sampling_stride` (larger = less CPU, less precision)
2. `smoothing` / `smoothing_speed` (`smoothing_speed` lower means slower response; `0.0` is strongest smoothing)
3. `fps`

Only change one variable at a time and retest using the same content.
