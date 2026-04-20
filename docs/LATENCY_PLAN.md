# Latency Measurement and Auto-Selection Plan

## Scope

This plan defines how we measure, compare, and gate capture backends for latency-sensitive operation in this project.

## Test Conditions

Measurements and pass/fail decisions should be made under the following baseline conditions:

- **Platform:** Typical KDE Plasma Wayland desktop session.
- **Load profiles:**
  - **Idle:** Desktop mostly static, no heavy background tasks.
  - **Moderate load:** Normal interactive usage (window movement, browser/video playback, light multitasking).
- **Resolution:** Use the project default resolution derived from the current capture dimension policy (do not override resolution specifically for this benchmark run).
- **Sampling window:** Collect enough frames to make percentile and success-rate values meaningful (recommended minimum: 300 successful capture attempts per backend per load profile).

## Metrics

At least the following metrics must be recorded for each candidate backend (`kmsgrab`, `kwin-dbus`, `xdg-portal`):

### 1) Capture call latency

- **Definition:** Time spent inside backend `capture()` only.
- **Measurement points:**
  - `t_capture_start`: immediately before entering backend `capture()`.
  - `t_capture_end`: immediately after `capture()` returns.
- **Formula:**
  - `capture_latency_ms = (t_capture_end - t_capture_start)` in milliseconds.
- **Aggregate outputs:** min, median (p50), p95, p99, max.

### 2) End-to-end pipeline latency proxy

- **Definition:** Proxy for pipeline delay from frame acquisition to outbound device send.
- **Measurement points:**
  - `t_capture_timestamp`: timestamp attached at capture completion for a frame.
  - `t_driver_send`: timestamp when the driver submit/send call is issued for that same frame.
- **Formula:**
  - `pipeline_proxy_latency_ms = (t_driver_send - t_capture_timestamp)` in milliseconds.
- **Aggregate outputs:** median (p50), p95, p99.

### 3) Stability metric (jitter)

- **Primary jitter indicator:** p95 and p99 of `capture_latency_ms`.
- **Optional secondary indicator:**
  - `jitter_spread_ms = p99(capture_latency_ms) - p50(capture_latency_ms)`.
- **Interpretation:** Lower p95/p99 and lower spread indicate a more stable backend.

## Pass/Fail Targets

Targets are evaluated per backend and per load profile.

### Mandatory thresholds

1. **Capture success rate:**
   - `success_rate = successful_captures / attempted_captures`.
   - **Pass target:** `success_rate >= 99.0%`.

2. **Capture latency target (median):**
   - **Pass target:** `median_capture_latency_ms <= 12 ms` (idle) and `<= 18 ms` (moderate load).

3. **Stability target (tail latency):**
   - **Pass target:** `p95_capture_latency_ms <= 25 ms` and `p99_capture_latency_ms <= 40 ms`.

4. **Pipeline proxy target (sanity ceiling):**
   - **Pass target:** `median_pipeline_proxy_latency_ms <= 20 ms`.

A backend failing any mandatory threshold is considered **not eligible** for automatic winner selection.

## Success Criteria for Auto Selection

Automatic backend selection must follow this logic:

1. **Eligibility filter:**
   - Keep only backends meeting all mandatory thresholds above, including minimum success rate.

2. **Primary winner rule:**
   - Choose backend with the **lowest median capture latency** (`p50 capture_latency_ms`) among eligible backends.

3. **Tie-break rule:**
   - If medians are effectively tied (difference `< 0.5 ms`), apply deterministic priority:
     - `kmsgrab` > `kwin-dbus` > `xdg-portal`.

4. **Fallback behavior:**
   - If no backend is eligible, keep existing configured backend and emit a warning/diagnostic indicating all candidates failed gating.

## Reporting Format

For each backend and load profile, report at minimum:

- Attempts, successes, success rate (%).
- Capture latency: p50, p95, p99, max (ms).
- Pipeline proxy latency: p50, p95, p99 (ms).
- Final pass/fail per threshold and overall eligibility.
- Final selected backend and reason (winner metric + tie-break if applied).

## Non-Goals

The following are explicitly out of scope for this project plan:

- Kernel-level graphics scheduler tuning.
- GPU driver source modifications or vendor-specific driver patching.
- Compositor internals rewrites beyond normal backend integration points.
- System-wide real-time kernel or CPU governor tuning as a hard project requirement.
- Hardware overclocking/undervolting experiments.

These may influence absolute performance, but they are not required for backend comparison or selection logic in this repository.
