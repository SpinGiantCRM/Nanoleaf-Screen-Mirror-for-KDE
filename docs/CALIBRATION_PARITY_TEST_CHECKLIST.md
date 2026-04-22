# Calibration Parity Checklist Test Matrix

This artifact links each calibration parity requirement in `docs/CALIBRATION_PARITY_SPEC.md` to at least one automated test.

## Unit tests

| Requirement | Coverage tests |
|---|---|
| Mapping resolution determinism | `tests/test_calibration_flow.py::test_corner_anchor_derivation_is_deterministic_for_same_inputs`; `tests/test_zone_calibration.py::test_mapping_preview_corner_anchor_resolution_is_deterministic` |
| Anchor validation edge cases (missing/duplicate/out-of-range) | `tests/test_zone_calibration.py::test_corner_anchor_validation_summary_reports_missing_duplicate_and_out_of_range`; `tests/test_zone_calibration.py::test_mapping_preview_corner_anchor_validation_handles_all_missing`; `tests/test_calibration_flow.py::test_calibration_completion_blocks_out_of_range_corner_anchor_assignments` |
| Migration behavior from legacy aliases to nested calibration payload | `tests/test_pipeline_integration.py::test_migrated_legacy_calibration_config_keeps_preview_runtime_mapping_parity` |

## Integration tests

| Requirement | Coverage tests |
|---|---|
| Same config yields same mapping in preview/runtime | `tests/test_pipeline_integration.py::test_preview_and_runtime_share_identical_resolved_mapping_snapshot`; `tests/test_pipeline_integration.py::test_migrated_legacy_calibration_config_keeps_preview_runtime_mapping_parity` |
| Wizard completion gates enforce validation | `tests/test_display_configurator.py::test_display_configurator_blocks_next_until_calibration_phases_pass`; `tests/test_display_configurator.py::test_display_configurator_keeps_next_disabled_when_validation_fails` |

## UX / state tests

| Requirement | Coverage tests |
|---|---|
| Phase transitions | `tests/test_calibration_flow.py::test_calibration_step_prerequisites_gate_completion`; `tests/test_display_configurator.py::test_display_configurator_preserves_passed_phase_when_navigating_back` |
| Rollback / resume | `tests/test_calibration_state.py::test_state_checkpoint_restore_round_trips_phase_progress`; `tests/test_calibration_state.py::test_state_phase_boundary_restore_rewinds_only_from_saved_boundary`; `tests/test_display_configurator.py::test_display_configurator_persists_and_restores_in_progress_draft` |
| Disabled/enabled controls by validity | `tests/test_display_configurator.py::test_display_configurator_blocks_next_until_calibration_phases_pass`; `tests/test_display_configurator.py::test_display_configurator_keeps_next_disabled_when_validation_fails` |

## Spec acceptance parity map (P-01..P-10)

| Parity item (from spec §5) | Coverage |
|---|---|
| P-01 Phase order fixed + prerequisite gating | `tests/test_calibration_flow.py::test_calibration_sequence_contains_required_order`; `tests/test_calibration_flow.py::test_calibration_step_prerequisites_gate_completion` |
| P-02 Start-zone single active + progression block | `tests/test_zone_calibration.py::test_calibration_test_frame_only_lights_active_zone`; `tests/test_calibration_flow.py::test_phase_validation_tracks_failures_until_actions_pass` |
| P-03 Direction determinism + wrap-around | `tests/test_calibration_flow.py::test_corner_anchor_traversal_wraps_without_mutating_zone_offset_input`; `tests/test_zone_calibration.py::test_single_zone_step_reflects_offset_and_reverse` |
| P-04 Canonical corner order + uniqueness/in-range checks | `tests/test_zone_calibration.py::test_corner_anchor_steps_are_labeled`; `tests/test_zone_calibration.py::test_corner_anchor_validation_summary_reports_missing_duplicate_and_out_of_range` |
| P-05 Fine adjustment slots=4 + clamping | `tests/test_calibration_state.py::test_corner_refinement_active_offsets_pad_missing_values`; `tests/test_calibration_state.py::test_corner_refinement_clamps_to_supported_limit` |
| P-06 Final validation gate on confidence/sentinel/anchors | `tests/test_calibration_flow.py::test_calibration_completion_requires_validation_score_threshold`; `tests/test_calibration_state.py::test_validation_report_tracks_confidence_and_sentinel_consistency` |
| P-07 Offset+direction modulo + deterministic inversion | `tests/test_calibration_flow.py::test_derive_corner_anchor_device_indices_responds_to_offset_and_direction`; `tests/test_zone_calibration.py::test_mapping_preview_visual_reflects_reverse_and_offset` |
| P-08 Corner-anchored deterministic + safe invalid handling | `tests/test_zone_calibration.py::test_mapping_preview_corner_anchor_resolution_is_deterministic`; `tests/test_zone_calibration.py::test_mapping_preview_corner_anchor_validation_handles_all_missing` |
| P-09 Manual explicit map short-map fallback + no crash | `tests/test_zone_mapper.py::test_zone_mapper_explicit_map` |
| P-10 Changed zone count/canceled wizard cannot preserve invalid completion | `tests/test_display_configurator.py::test_display_configurator_zone_count_change_remaps_anchors_and_shows_notice`; `tests/test_display_configurator.py::test_display_configurator_blocks_next_until_calibration_phases_pass`; `tests/test_calibration_state.py::test_zone_count_change_invalidates_dependent_phase_progress`; `tests/test_display_configurator.py::test_display_configurator_persists_and_restores_in_progress_draft` |

## Batch delivery ledger (A-E)

Each batch below is releasable only when all targeted tests pass, calibration regression tests stay green, reviewer sign-off is recorded, and release notes are updated.

### Batch A — parity spec + schema + migration

* Checklist items: P-07, P-08, P-09.
* Targeted tests:
  * `tests/test_config.py::test_config_manual_explicit_map_model_sets_manual_mapping_enabled`
  * `tests/test_config.py::test_config_manual_map_alias_migrates_to_manual_explicit_map`
  * `tests/test_pipeline_integration.py::test_migrated_legacy_calibration_config_keeps_preview_runtime_mapping_parity`
* Reviewer sign-off: ☐ Pending / ☐ Approved
* Release notes: `CHANGELOG.md` Unreleased entry includes calibration schema/migration behavior updates.

### Batch B — unified resolver + mapping pipeline unification

* Checklist items: P-07, P-08, P-09.
* Targeted tests:
  * `tests/test_pipeline_integration.py::test_preview_and_runtime_share_identical_resolved_mapping_snapshot`
  * `tests/test_pipeline_integration.py::test_manual_explicit_model_forces_explicit_mapping_without_manual_flag`
* Reviewer sign-off: ☐ Pending / ☐ Approved
* Release notes: `CHANGELOG.md` Unreleased entry includes resolver + preview/runtime parity notes.

### Batch C — wizard state machine + truthful corner UX

* Checklist items: P-01, P-02, P-03, P-04, P-05.
* Targeted tests:
  * `tests/test_display_configurator.py::test_display_configurator_blocks_next_until_calibration_phases_pass`
  * `tests/test_display_configurator.py::test_display_configurator_preserves_passed_phase_when_navigating_back`
  * `tests/test_zone_calibration.py::test_corner_anchor_validation_summary_reports_missing_duplicate_and_out_of_range`
* Reviewer sign-off: ☐ Pending / ☐ Approved
* Release notes: `CHANGELOG.md` Unreleased entry includes wizard phase-gating + corner-validation UX updates.

### Batch D — verification phase + recovery features

* Checklist items: P-06, P-10.
* Targeted tests:
  * `tests/test_calibration_state.py::test_validation_report_tracks_confidence_and_sentinel_consistency`
  * `tests/test_display_configurator.py::test_display_configurator_recovery_controls_restore_checkpoint`
  * `tests/test_display_configurator.py::test_display_configurator_reset_current_phase_restores_boundary_snapshot`
* Reviewer sign-off: ☐ Pending / ☐ Approved
* Release notes: `CHANGELOG.md` Unreleased entry includes verification gating + rollback/recovery behavior notes.

### Batch E — test expansion + docs finalization

* Checklist items: P-01..P-10 (full pass).
* Targeted tests:
  * `pytest tests/test_config.py tests/test_pipeline_integration.py tests/test_calibration_flow.py tests/test_calibration_state.py tests/test_display_configurator.py`
* Reviewer sign-off: ☐ Pending / ☐ Approved
* Release notes: `CHANGELOG.md` Unreleased summarizes completed parity batches and behavior changes.
