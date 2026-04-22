# Calibration Parity Release Gate — 2026-04-22

## Outcome

- **Release decision: BLOCKED**
- **Reason:** Parity requirement **P-06** is failing in automated validation and manual wizard replay (final validation does not reach strict pass gate in the exercised flow).
- **Policy check:** Release is blocked because at least one parity requirement is failing.

## Automated evidence run

Command executed:

```bash
pytest -q tests/test_calibration_flow.py::test_calibration_sequence_contains_required_order tests/test_calibration_flow.py::test_calibration_step_prerequisites_gate_completion tests/test_zone_calibration.py::test_calibration_test_frame_only_lights_active_zone tests/test_calibration_flow.py::test_phase_validation_tracks_failures_until_actions_pass tests/test_calibration_flow.py::test_corner_anchor_traversal_wraps_without_mutating_zone_offset_input tests/test_zone_calibration.py::test_single_zone_step_reflects_offset_and_reverse tests/test_zone_calibration.py::test_corner_anchor_steps_are_labeled tests/test_zone_calibration.py::test_corner_anchor_validation_summary_reports_missing_duplicate_and_out_of_range tests/test_calibration_state.py::test_corner_refinement_active_offsets_pad_missing_values tests/test_calibration_state.py::test_corner_refinement_clamps_to_supported_limit tests/test_calibration_flow.py::test_calibration_completion_requires_validation_score_threshold tests/test_calibration_state.py::test_validation_report_tracks_confidence_and_sentinel_consistency tests/test_calibration_flow.py::test_derive_corner_anchor_device_indices_responds_to_offset_and_direction tests/test_zone_calibration.py::test_mapping_preview_visual_reflects_reverse_and_offset tests/test_zone_calibration.py::test_mapping_preview_corner_anchor_resolution_is_deterministic tests/test_zone_calibration.py::test_mapping_preview_corner_anchor_validation_handles_all_missing tests/test_zone_mapper.py::test_zone_mapper_explicit_map tests/test_display_configurator.py::test_display_configurator_zone_count_change_remaps_anchors_and_shows_notice tests/test_display_configurator.py::test_display_configurator_blocks_next_until_calibration_phases_pass tests/test_calibration_state.py::test_zone_count_change_invalidates_dependent_phase_progress tests/test_display_configurator.py::test_display_configurator_persists_and_restores_in_progress_draft
```

Result: **20 passed, 1 failed**

Failing test:
- `tests/test_calibration_flow.py::test_calibration_completion_requires_validation_score_threshold`
  - Assertion failed on expected remediation text containing `override`.

## Manual wizard run evidence by phase

Manual execution command (state-machine wizard walk):

```bash
PYTHONPATH=src python - <<'PY'
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.calibration_state import CalibrationState

state=CalibrationState.from_config(AppConfig(device_zone_count=8), {})
print('Initial phase', state.current_phase)
print('P1->P2 prereq before pass', state.calibration_prerequisites_met('direction-verification'))
state.mark_calibration_step('start-point-detection', passed=True, notes='manual run: start-zone matched highlighted zone')
print('P1 pass / P2 prereq after pass', state.calibration_prerequisites_met('direction-verification'))
state.reverse_zones=True
state.mark_calibration_step('direction-verification', passed=True, notes='manual run: full forward/reverse cycle observed')
print('P2 eval', state.evaluate_phase('direction-verification'))
state.calibration_model='corner_anchored'
state.corner_anchor_top_left=0
state.corner_anchor_top_right=2
state.corner_anchor_bottom_right=4
state.corner_anchor_bottom_left=6
state.mark_calibration_step('corner-assignment', passed=True, notes='manual run: assigned TL/TR/BR/BL unique in range')
print('P3 eval', state.evaluate_phase('corner-assignment'))
state.corner_offsets_enabled=True
state.corner_zone_offsets=[2,-2,3,-3]
state.mark_calibration_step('edge-refinement', passed=True, notes='manual run: drift reduced after micro-adjustment')
print('P4 eval', state.evaluate_phase('edge-refinement'))
state.mark_calibration_step('validation-replay', passed=True, notes='manual run: completed full replay cycle')
report=state.validation_report()
print('P5 summary', report.compact_summary())
print('P5 remediation', report.remediation_action)
print('Can complete?', state.can_complete_calibration_flow())
state.device_zone_count=12
print('Invalidated phases', state.invalidate_for_zone_count_change())
print('Can complete after zone count change?', state.can_complete_calibration_flow())
PY
```

### Phase-by-phase expected vs observed

| Phase | Expected behavior | Observed behavior | Result |
|---|---|---|---|
| 1) Start-zone identification | Phase 2 blocked until start-zone confirmation. | `direction-verification` prerequisite was `False` before P1 pass and `True` after P1 pass. | PASS |
| 2) Direction verification | Direction confirmation accepted after a complete directional check. | `evaluate_phase('direction-verification')` returned pass after marking phase passed. | PASS |
| 3) Corner assignment | TL/TR/BR/BL unique in-range anchors validate and allow progression. | `evaluate_phase('corner-assignment')` returned pass for unique anchors 0/2/4/6. | PASS |
| 4) Fine adjustment | Four-slot adjustments accepted and phase can pass. | Four offset values were applied and `evaluate_phase('edge-refinement')` returned pass. | PASS |
| 5) Final validation | Confidence=1.00 plus sentinel consistency should allow completion. | Report summary was `verification=fail confidence=1.00 ... sentinel=fix`; `can_complete_calibration_flow()` stayed `False`. | FAIL |

## Parity map verdict (P-01..P-10)

| Item | Status | Automated evidence | Manual check note |
|---|---|---|---|
| P-01 Phase order fixed + prerequisite gating | PASS | `test_calibration_sequence_contains_required_order`; `test_calibration_step_prerequisites_gate_completion` | Manual run showed P2 blocked before P1 pass and unblocked after. |
| P-02 Start-zone single active + progression block | PASS | `test_calibration_test_frame_only_lights_active_zone`; `test_phase_validation_tracks_failures_until_actions_pass` | Manual run confirmed phase gate behavior from start to direction phase. |
| P-03 Direction determinism + wrap-around | PASS | `test_corner_anchor_traversal_wraps_without_mutating_zone_offset_input`; `test_single_zone_step_reflects_offset_and_reverse` | Manual run set reverse orientation and phase validation passed. |
| P-04 Canonical corner order + uniqueness/in-range checks | PASS | `test_corner_anchor_steps_are_labeled`; `test_corner_anchor_validation_summary_reports_missing_duplicate_and_out_of_range` | Manual run used TL/TR/BR/BL assignment and corner validation passed. |
| P-05 Fine adjustment slots=4 + clamping | PASS | `test_corner_refinement_active_offsets_pad_missing_values`; `test_corner_refinement_clamps_to_supported_limit` | Manual run applied four micro-adjust values; phase evaluation passed. |
| P-06 Final validation gate on confidence/sentinel/anchors | **FAIL** | `test_calibration_completion_requires_validation_score_threshold` (**failed**); `test_validation_report_tracks_confidence_and_sentinel_consistency` | Manual run reached validation replay but final report stayed `fail` due sentinel inconsistency; completion blocked. |
| P-07 Offset+direction modulo + deterministic inversion | PASS | `test_derive_corner_anchor_device_indices_responds_to_offset_and_direction`; `test_mapping_preview_visual_reflects_reverse_and_offset` | Manual run toggled reverse and observed deterministic direction-phase pass. |
| P-08 Corner-anchored deterministic + safe invalid handling | PASS | `test_mapping_preview_corner_anchor_resolution_is_deterministic`; `test_mapping_preview_corner_anchor_validation_handles_all_missing` | Manual run in `corner_anchored` model accepted valid unique anchors without crash. |
| P-09 Manual explicit map short-map fallback + no crash | PASS | `test_zone_mapper_explicit_map` | Manual check via `resolved_mapping_snapshot()` with explicit map `[7,6,5]` produced deterministic tail fallback `[0,0,0,0,0]` and no crash. |
| P-10 Changed zone count/canceled wizard cannot preserve invalid completion | PASS | `test_display_configurator_zone_count_change_remaps_anchors_and_shows_notice`; `test_display_configurator_blocks_next_until_calibration_phases_pass`; `test_zone_count_change_invalidates_dependent_phase_progress`; `test_display_configurator_persists_and_restores_in_progress_draft` | Manual run `invalidate_for_zone_count_change()` invalidated dependent phases and completion remained blocked. |

## Sign-off

- QA parity gate sign-off: **NOT APPROVED**
- Release recommendation: **Do not release** until P-06 is green in both automated and manual checks.
