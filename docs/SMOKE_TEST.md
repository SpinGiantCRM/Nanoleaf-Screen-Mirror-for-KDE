# Smoke Test Guide

## Purpose

`nanoleaf-kde-sync-smoke-test` is a quick validation tool for:

- capture backend selection
- one-frame capture success
- USB device initialization
- optional LED output sanity frame

It is safe to run before starting long service sessions.

## Basic checks

```bash
nanoleaf-kde-sync-doctor
nanoleaf-kde-sync-smoke-test
```

## Deep checks

```bash
nanoleaf-kde-sync-doctor --capture
nanoleaf-kde-sync-doctor --device
```

## Optional device frame test

```bash
nanoleaf-kde-sync-smoke-test --send-test-frame
```

This sends a low-brightness RGB pattern to verify device output.

## Reading smoke-test output

Key lines:

- `probe config:`
  - `enabled`: effective probe enable state from config/env
  - `policy`: `first-run`, `each-boot`, or `on-change`
  - `cached_winner`: cached auto backend if present
  - `signature`: environment signature hash used by `on-change`
  - `timestamp`: last persisted auto decision timestamp
- `backend decision:`
  - `requested`: configured `prefer_backend`
  - `effective`: backend used for this run
  - `selection_reason`: one of:
    - `explicit`: non-`auto` backend configured
    - `cached-probe`: reused cached auto winner
    - `fresh-probe`: new probe result used
    - `fallback`: probe unavailable/failed/no qualified candidate

## Fast diagnosis matrix

- `capture failed`: run `nanoleaf-kde-sync-doctor --capture` and fix reported guidance.
- `device init failed`: run `nanoleaf-kde-sync-doctor --device`, then verify udev permissions and VID/PID.
- `selection_reason=fallback` while `requested=auto`:
  - inspect probe policy and cache in config
  - verify env kill switches are not forcing probe off
  - optionally force explicit backend for A/B testing

## Related references

- Auto backend policies and examples: `docs/AUTO_BACKEND.md`
- Probe/reset troubleshooting workflow: `docs/TROUBLESHOOTING.md`
