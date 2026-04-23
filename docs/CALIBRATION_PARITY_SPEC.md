# Calibration Parity Specification

## Goal

Define parity expectations between calibration behavior across supported environments so release candidates can be validated consistently.

## Scope

- Supported sessions: Wayland and X11.
- Supported run modes: `full-mock`, `capture-real`, and `full-real` (when hardware is available).
- Validation targets: calibration prompts, completion flow, persisted state, and startup behavior after calibration.

## Parity Requirements

1. **Flow parity**: users complete the same ordered calibration steps regardless of compositor/session.
2. **State parity**: saved calibration artifacts are loaded and applied equivalently on next startup.
3. **Error parity**: recoverable errors show equivalent remediation guidance and allow retry.
4. **Exit parity**: canceled flows leave config in a known-safe state (no partial-apply behavior).

## Acceptance Criteria

- Required matrix rows pass for at least one Wayland and one X11 run.
- No blocker-severity differences in calibration UX between environments.
- Known differences are documented in release notes and linked evidence.

## Evidence

Capture evidence in:

- `docs/CALIBRATION_PARITY_TEST_CHECKLIST.md`
- `docs/PHYSICAL_CALIBRATION_VALIDATION_LOG.md`
- RC PR artifact table in `.github/PULL_REQUEST_TEMPLATE/release.md`
