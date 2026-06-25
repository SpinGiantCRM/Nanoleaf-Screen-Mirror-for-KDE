## Summary

- Describe what changed and why.

## Validation

- [ ] Tests added/updated for changed behavior.
- [ ] Relevant docs and changelog are updated.
- [ ] Coverage floor policy respected (>=75%).

## Calibration parity gate (required for calibration-touching changes)

> Calibration-touching changes include updates to mapping behavior, wizard phase logic, calibration resolver/state, or calibration schema/model serialization.

- [ ] I documented validation evidence in this PR body or linked a tracked calibration doc.
- [ ] I reviewed behavior contracts when calibration semantics changed.
- [ ] If mapping or wizard phase logic changed, I updated at least one integration test file (`tests/test_pipeline_integration.py`, `tests/test_display_configurator.py`, or `tests/test_wizard_and_settings_structure.py`).
- [ ] If schema/model changed, I synced parity docs and bumped `VERSION` in this PR.
