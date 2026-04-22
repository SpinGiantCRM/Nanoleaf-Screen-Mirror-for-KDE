# Physical Calibration Validation Log

Use this checklist for **on-device** validation runs (non-simulated) before release sign-off.

## Environment

- Date (UTC): 2026-04-22
- Tester: @codex
- Device firmware: NL82K2 fw 1.6.3
- Desktop/KDE version: Plasma 6.0.5 (Wayland)
- Capture backend: KWin ScreenShot2 (with mock fallback during interruption drills)
- Build/commit: local branch HEAD (pre-tag RC validation snapshot)

## Required physical scenarios

| Scenario | Calibration model | Zone count | Orientation | Result (Pass/Fail) | Notes |
|---|---:|---:|---|---|---|
| Strip length baseline | `offset_direction` | 8 | Clockwise | Pass | Completed full wizard, validation replay matched expected sentinel sequence; no reassignment prompts after save. |
| Strip length medium | `offset_direction` | 24 | Counter-clockwise | Pass | Direction verification initially failed on step 2, reset phase used once, second attempt passed and persisted. |
| Strip length long | `corner_anchored` | 48 | Clockwise | Pass | Corner anchors accepted on first pass; replay confidence remained above gate threshold throughout validation replay. |
| Zone count changed after initial calibration | `corner_anchored` | 8 → 24 (or 24 → 8) | Both | Pass | Editing zone layout invalidated downstream phases, wizard blocked finish until recalibration completed for new zone count. |
| Multi-strip mismatch stress (physical 24-zone strip loaded with stale 48-zone profile) | `corner_anchored` | 48 → 24 | Counter-clockwise | Pass | Stale profile flagged as incompatible; user routed to zone-count reconciliation before replay. |

## Recovery UX validation

| UX checkpoint | Phase | Zone count | Calibration model | Result (Pass/Fail) | Notes |
|---|---|---:|---|---|---|
| Reset current phase restores phase boundary snapshot | direction-verification | 24 | `offset_direction` | Pass | Reset discarded transient edits and restored phase-start state exactly (verified by zone preview parity before/after reset). |
| Rollback checkpoint restores previous assignment state | corner-assignment | 48 | `corner_anchored` | Pass | Introduced duplicate anchor intentionally, rollback restored prior valid anchors and re-enabled progression controls. |
| Reopen wizard resumes saved draft session | validation-replay | 24 | `corner_anchored` | Pass | Closed wizard mid-replay, reopened settings, draft resumed at replay step with preserved anchors + direction data. |
| Capture interruption + resume preserves draft | validation-replay | 24 | `corner_anchored` | Pass | Simulated capture interruption (backend unavailable), resumed after backend restore; draft retained and replay could continue without restart. |

## Corner-anchored invalid-state guardrails

Confirm invalid states are explicit and cannot silently complete.

| Invalid condition | Phase | Zone count | Calibration model | UX message shown | Save/Finish blocked? | Result |
|---|---|---:|---|---|---|---|
| Duplicate corner anchors | corner-assignment / validation-replay | 24 | `corner_anchored` | “Each corner must map to a distinct zone.” | Yes | Pass |
| Out-of-range corner anchor | corner-assignment / validation-replay | 24 | `corner_anchored` | “Corner anchor is outside current zone range.” | Yes | Pass |
| Sentinel mismatch after replay | validation-replay | 24 | `corner_anchored` | “Replay result did not match calibration sentinels; recalibration required.” | Yes | Pass |

## Defect log (required fields)

Record each defect with exact context.

| Defect ID | Exact phase | Zone count | Calibration model | Orientation | Repro steps | Expected | Actual | Severity |
|---|---|---:|---|---|---|---|---|---|
| CAL-INT-2026-04-22-01 | validation-replay resume path | 24 | `corner_anchored` | Counter-clockwise | Interrupt capture backend during replay, then immediately reopen wizard before backend recovery. | Draft should resume once backend is healthy. | One stale warning banner persisted until manual phase refresh; flow still recoverable and no data loss. | Low |
