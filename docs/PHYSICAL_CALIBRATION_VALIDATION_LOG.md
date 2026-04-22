# Physical Calibration Validation Log (Template)

Use this checklist for **on-device** validation runs (non-simulated) before release sign-off.

## Environment

- Date (UTC):
- Tester:
- Device firmware:
- Desktop/KDE version:
- Capture backend:
- Build/commit:

## Required physical scenarios

| Scenario | Calibration model | Zone count | Orientation | Result (Pass/Fail) | Notes |
|---|---:|---:|---|---|---|
| Strip length baseline | `offset_direction` | 8 | Clockwise |  |  |
| Strip length medium | `offset_direction` | 24 | Counter-clockwise |  |  |
| Strip length long | `corner_anchored` | 48 | Clockwise |  |  |
| Zone count changed after initial calibration | `corner_anchored` | 8 → 24 (or 24 → 8) | Both |  |  |
| Multi-strip mismatch stress (physical 24-zone strip loaded with stale 48-zone profile) | `corner_anchored` | 48 → 24 | Counter-clockwise |  |  |

## Recovery UX validation

| UX checkpoint | Phase | Zone count | Calibration model | Result (Pass/Fail) | Notes |
|---|---|---:|---|---|---|
| Reset current phase restores phase boundary snapshot | direction-verification | 24 | `offset_direction` |  |  |
| Rollback checkpoint restores previous assignment state | corner-assignment | 48 | `corner_anchored` |  |  |
| Reopen wizard resumes saved draft session | validation-replay | 24 | `corner_anchored` |  |  |
| Capture interruption + resume preserves draft | validation-replay | 24 | `corner_anchored` |  |  |

## Corner-anchored invalid-state guardrails

| Invalid condition | Phase | Zone count | Calibration model | UX message shown | Save/Finish blocked? | Result |
|---|---|---:|---|---|---|---|
| Duplicate corner anchors | corner-assignment / validation-replay | 24 | `corner_anchored` |  |  |  |
| Out-of-range corner anchor | corner-assignment / validation-replay | 24 | `corner_anchored` |  |  |  |
| Sentinel mismatch after replay | validation-replay | 24 | `corner_anchored` |  |  |  |

## Defect log (required fields)

| Defect ID | Exact phase | Zone count | Calibration model | Orientation | Repro steps | Expected | Actual | Severity |
|---|---|---:|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |  |
