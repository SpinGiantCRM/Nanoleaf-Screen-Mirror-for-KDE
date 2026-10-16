## Summary

- Describe what changed and why.

## Validation

- [ ] Tests added/updated for changed behavior.
- [ ] Relevant docs and changelog are updated.
- [ ] Relevant Rust application/core contracts and operator tests pass.

## Calibration parity gate (required for calibration-touching changes)

> Calibration-touching changes include updates to mapping behavior, wizard phase logic, calibration resolver/state, or calibration schema/model serialization.

- [ ] I documented validation evidence in this PR body or linked a tracked calibration doc.
- [ ] I reviewed behavior contracts when calibration semantics changed.
- [ ] If mapping or wizard phase logic changed, I updated at least one integration test file (`native/app/tests/pipeline.rs`, `native/app/tests/geometry.rs`, or `native/app/tests/config.rs`).
- [ ] If schema/model changed, I updated migration tests and documented schema compatibility in this PR.
