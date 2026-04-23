# Calibration Parity Test Checklist

Use this checklist during RC validation to verify cross-environment calibration parity.

## Pre-flight

- [ ] `nanoleaf-kde-sync-doctor` passes baseline checks.
- [ ] Test environment + mode identified (`full-mock` / `capture-real` / `full-real`).
- [ ] Existing calibration state snapshot captured (if present).

## Flow checks

- [ ] Calibration wizard/flow starts successfully.
- [ ] Anchor/setup prompts match expected sequence.
- [ ] Cancel behavior returns to safe non-calibrated state.
- [ ] Retry from failure path works without restart.

## Persistence checks

- [ ] Successful calibration persists artifacts.
- [ ] Restart applies persisted calibration without repeating setup.
- [ ] Manual reset (if performed) clears calibration state cleanly.

## UX parity checks

- [ ] Prompt wording and guidance are materially equivalent across sessions.
- [ ] Error messaging includes actionable next steps.
- [ ] Completion signal/status is visible and unambiguous.

## Evidence links

- Logs/artifacts:
- Screenshots (optional):
- Related RC row(s):
- Notes on differences (if any):
