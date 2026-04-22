# Physical Calibration Validation Log

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
| Zone count changed after initial calibration | `corner_anchored` | 8 → 24 (or 24 → 8) | Both |  | Verify invalidation + recalibration gating |

## Recovery UX validation

| UX checkpoint | Phase | Zone count | Calibration model | Result (Pass/Fail) | Notes |
|---|---|---:|---|---|---|
| Reset current phase restores phase boundary snapshot |  |  |  |  |  |
| Rollback checkpoint restores previous assignment state |  |  |  |  |  |
| Reopen wizard resumes saved draft session |  |  |  |  |  |

## Corner-anchored invalid-state guardrails

Confirm invalid states are explicit and cannot silently complete.

| Invalid condition | Phase | Zone count | Calibration model | UX message shown | Save/Finish blocked? | Result |
|---|---|---:|---|---|---|---|
| Duplicate corner anchors | corner-assignment / validation-replay |  | `corner_anchored` |  | Yes / No |  |
| Out-of-range corner anchor | corner-assignment / validation-replay |  | `corner_anchored` |  | Yes / No |  |
| Sentinel mismatch after replay | validation-replay |  | `corner_anchored` |  | Yes / No |  |

## Defect log (required fields)

Record each defect with exact context.

| Defect ID | Exact phase | Zone count | Calibration model | Orientation | Repro steps | Expected | Actual | Severity |
|---|---|---:|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |  |

