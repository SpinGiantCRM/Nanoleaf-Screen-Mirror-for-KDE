## Summary

- Describe what changed and why.

## Validation

- [ ] Tests added/updated for changed behavior.
- [ ] Relevant docs and changelog are updated.
- [ ] Coverage floor policy respected (>=70%).

## Calibration parity gate (required for calibration-touching changes)

> Calibration-touching changes include updates to mapping behavior, wizard phase logic, calibration resolver/state, or calibration schema/model serialization.

- [ ] I updated `docs/CALIBRATION_PARITY_TEST_CHECKLIST.md` with coverage for this change.
- [ ] I reviewed/updated `docs/CALIBRATION_PARITY_SPEC.md` when behavior contracts changed.
- [ ] If mapping or wizard phase logic changed, I updated at least one integration test file (`tests/test_pipeline_integration.py`, `tests/test_display_configurator.py`, or `tests/test_wizard_and_settings_structure.py`).
- [ ] If schema/model changed, I synced parity docs and bumped `VERSION` in this PR.
