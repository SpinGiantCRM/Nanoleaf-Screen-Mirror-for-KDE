# Calibration Parity Specification

## Purpose

This document is the parity contract for calibration behavior across setup/onboarding, settings, and runtime validation surfaces. A change to calibration UX is **not releasable** unless it preserves (or intentionally updates) this contract and updates traceability links in the checklist.

## Scope

This contract applies to:

- `offset_direction` calibration mode (offset + reverse direction).
- `corner_anchored` calibration mode (explicit TL/TR/BR/BL anchors).
- Fine-tuning through per-corner local offsets.
- Step-gated completion in the calibration flow.

Primary implementation surfaces:

- `src/nanoleaf_sync/ui/calibration_flow.py`
- `src/nanoleaf_sync/ui/calibration_state.py`
- `src/nanoleaf_sync/runtime/calibration_resolver.py`
- `src/nanoleaf_sync/color/zone_mapper.py`
- `src/nanoleaf_sync/ui/zone_calibration.py`
- `src/nanoleaf_sync/config/model.py`
- `src/nanoleaf_sync/config/normalize.py`

---

## Contract: expected behavior (normative)

> Terms:
>
> - **source zone** = sampled screen zone index.
> - **device zone** = physical strip segment index.
> - **mapping** = `device_zone_index -> source_zone_index`.

### 1) Start zone detection

1. Calibration flow must begin with `start-point-detection` and no prerequisites.
2. User must be able to run a single active-zone walk that highlights exactly one physical zone at a time.
3. Start-point detection is considered passable only when user confirms the active zone corresponds to physical top-left start position.
4. If strip zone count is unknown/non-positive, effective count must normalize to at least 1 for deterministic preview/testing.

**Observable evidence**

- Sequence includes `start-point-detection` at position 1.
- Active frame contains exactly one non-black zone for single-zone step in walk mode.
- Progress gating keeps step 2 blocked until step 1 is marked passed.

### 2) Direction handling

1. Direction verification must be gated on successful start-point detection.
2. Direction semantics:
   - `reverse_zones = False` => clockwise progression semantics.
   - `reverse_zones = True` => mirrored/counter-clockwise semantics.
3. Toggling `reverse_zones` must change mapping output deterministically for same zone count + offset.
4. A full cycle wraps modulo strip length with no index overflow or mutation of user-entered offset.

**Observable evidence**

- Mapping visual/text changes after reverse toggle.
- Corner-anchor derivation changes when direction flips.
- Walk cycle wraps to same device index after `N` steps.

### 3) Corner assignment semantics

1. Corner assignment step must follow direction verification.
2. Corner order is canonical and immutable: **TL, TR, BR, BL**.
3. In `corner_anchored` model:
   - Four anchors must be unique and in-range to be valid.
   - Invalid anchors must yield validation errors and fallback behavior (no crash).
4. Derived sentinel corners from current mapping must be deterministic and unique up to available strip zones (`min(4, device_zone_count)`).
5. If explicit assignments are missing, validation compares against derived sentinels by using expected defaults.

**Observable evidence**

- Preview text prints anchors in TL/TR/BR/BL order.
- Validation report marks `anchors_unique_valid` false for duplicates/out-of-range.
- Sentinel mismatch blocks completion even if steps were marked passed.

### 4) Offset normalization

1. `zone_offset` must be treated as integer rotational offset and normalized modulo source zone count in mapping output.
2. Large positive and negative offsets must be equivalent to modulo-normalized values.
3. `device_zone_count <= 0` must normalize to 1 in resolver/state where needed for deterministic behavior.
4. Mapping with explicit manual map uses modulo-normalized explicit indices and falls back to source zone `0` if explicit map is shorter than device zone count.

**Observable evidence**

- Offset `10` on 3 zones behaves like `+1`.
- Mapping output never contains out-of-range source indices.
- Calibration previews and cycle helpers remain stable for non-positive configured counts.

### 5) Fine tuning limits

1. Per-corner fine-tune offsets are exactly 4 values `[TL, TR, BR, BL]`; missing values are padded with `0`.
2. Fine-tune values are clamped to `[-24, +24]`.
3. If corner offsets are disabled, effective offsets are `[0, 0, 0, 0]`.
4. Local-corner refinement must keep influence mostly local; tuning one corner must not significantly drag opposite corner mapping.

**Observable evidence**

- Inputs like `[99, -99, 30, -30]` resolve to `[24, -24, 24, -24]`.
- Single-corner tuning changes near-corner mapping while opposite corner remains stable.

### 5b) Canonical calibration payload + migration

1. Persisted config must include `calibration_schema_version` and `[calibration]`.
2. Runtime and wizard surfaces must resolve mapping from canonical nested calibration payload.
3. Top-level legacy calibration keys remain compatibility aliases only; normalization must mirror canonical values back to top-level fields.
4. Invalid or missing schema/version values must coerce safely to a supported version (currently `1`).

**Observable evidence**

- Loading legacy top-level-only config produces populated `[calibration]` on save.
- Resolver chooses nested `calibration_model`/anchors when present.
- Setup wizard save writes consistent top-level + nested calibration fields.

### 6) Final validation flow

1. Calibration sequence order is fixed:
   1. `start-point-detection`
   2. `direction-verification`
   3. `corner-assignment`
   4. `edge-refinement`
   5. `validation-replay`
2. Completion gate requires:
   - every step marked `passed = True`, and
   - validation confidence score `>= 1.0`, and
   - sentinel consistency true, and
   - corner validation true.
3. Failed validation replay or any failed prerequisite keeps completion gate closed.
4. Remediation hints must be present when confidence < 1.0 or sentinel/anchor checks fail.

**Observable evidence**

- `can_complete_calibration_flow()` returns `False` when any step fails.
- Forced sentinel mismatch keeps completion blocked even with all steps marked passed.

---

## Canonical user journeys

### Journey A: Happy path (offset + direction model)

1. User starts calibration; step 1 highlights one zone and confirms top-left start point.
2. User runs direction walk; motion is backwards, toggles reverse, reruns full cycle.
3. User checks corner assignment equivalence in walk and verifies corners.
4. User applies small offset tweaks until edge drift disappears.
5. User runs validation replay across full cycle; all checks pass; completion enabled.

**Pass condition:** completion gate opens and preview/mapping remains consistent after save/reopen.

### Journey B: Happy path (corner-anchored model)

1. User enables corner-anchored mode and assigns TL/TR/BR/BL while active zones are visible.
2. System validates uniqueness/range of all anchors.
3. User runs edge refinement with optional corner offsets.
4. Validation replay passes with sentinel consistency and confidence 1.0.

**Pass condition:** mapping preview shows `Calibration model: corner anchored` and lists anchors in TL/TR/BR/BL order.

### Journey C: Recovery from wrong direction

1. Start-point detection passed.
2. Direction walk appears mirrored.
3. User toggles reverse and repeats direction walk.
4. Direction verification passes; downstream steps become available.

**Recovery rule:** direction failure never crashes flow; it blocks progression until corrected.

### Journey D: Recovery from invalid corner anchors

1. User enters duplicate or out-of-range anchors.
2. Validation shows anchor errors; confidence remains below threshold.
3. User reassigns unique in-range TL/TR/BR/BL anchors.
4. Sentinel replay and final validation pass.

**Recovery rule:** invalid anchors must degrade to actionable errors/hints, not undefined mapping behavior.

### Journey E: Recovery from over-tuned corner offsets

1. User inputs extreme corner offsets.
2. System clamps to supported range automatically.
3. User iterates with smaller values to eliminate drift.

**Recovery rule:** no overflow/no out-of-range indexing; tuning remains deterministic.

---

## Failure and recovery scenarios (release-significant)

- **Unknown strip size (`device_zone_count <= 0`)**
  - Expected: normalized deterministic behavior with effective count >= 1.
  - Recovery: detect real zone count or keep configured fallback; no crash.
- **Step prerequisite violation**
  - Expected: blocked progression for dependent steps.
  - Recovery: pass prerequisite step first.
- **Validation replay fails after prior passes**
  - Expected: completion disabled until replay passes.
  - Recovery: rerun failing phase + replay.
- **Sentinel mismatch with otherwise passed steps**
  - Expected: completion disabled; remediation hints emitted.
  - Recovery: reassign anchors and rerun replay.
- **Manual mapping shorter than strip zone count**
  - Expected: unmapped tail defaults to source zone 0.
  - Recovery: provide full explicit map if desired.

---

## Parity checklist (QA + release gate)

Use this checklist for every UX/calibration change PR. A release candidate must have all required checks passing or an explicit signed waiver.

| ID | Checklist item (must hold) | Verification type | Owning tests (automated) | Owning files (implementation) |
|---|---|---|---|---|
| P-01 | Sequence order is fixed and includes 5 required steps with prerequisite gating. | Automated + manual sanity | `tests/test_calibration_flow.py::test_calibration_sequence_contains_required_order`; `tests/test_calibration_flow.py::test_calibration_step_prerequisites_gate_completion` | `src/nanoleaf_sync/ui/calibration_flow.py`; `src/nanoleaf_sync/ui/calibration_state.py` |
| P-02 | Start-point detection uses single active zone semantics and blocks step 2 until passed. | Automated + manual visual | `tests/test_calibration_flow.py::test_calibration_step_prerequisites_gate_completion`; `tests/test_zone_calibration.py::test_calibration_test_frame_only_lights_active_zone` | `src/nanoleaf_sync/ui/calibration_flow.py`; `src/nanoleaf_sync/ui/calibration_preview.py`; `src/nanoleaf_sync/ui/calibration_state.py` |
| P-03 | Direction toggle changes mapping deterministically and wrap-around remains stable. | Automated | `tests/test_zone_calibration.py::test_mapping_preview_visual_reflects_reverse_and_offset`; `tests/test_calibration_flow.py::test_derive_corner_anchor_device_indices_responds_to_offset_and_direction`; `tests/test_calibration_flow.py::test_corner_anchor_traversal_wraps_without_mutating_zone_offset_input` | `src/nanoleaf_sync/color/zone_mapper.py`; `src/nanoleaf_sync/ui/zone_calibration.py`; `src/nanoleaf_sync/ui/calibration_flow.py` |
| P-04 | Corner assignment is TL/TR/BR/BL canonical and corner-anchored mode is deterministic. | Automated | `tests/test_corner_anchor_calibration.py::test_corner_anchored_model_uses_assigned_anchors_deterministically`; `tests/test_zone_calibration.py::test_corner_anchor_steps_are_labeled`; `tests/test_calibration_flow.py::test_derive_corner_anchor_device_indices_stays_unique_with_more_device_zones` | `src/nanoleaf_sync/runtime/anchor_calibration.py`; `src/nanoleaf_sync/ui/calibration_flow.py`; `src/nanoleaf_sync/ui/zone_calibration.py` |
| P-05 | Offset normalization is modulo-safe for large values and keeps indices in range. | Automated | `tests/test_zone_mapper.py::test_zone_mapper_wraps_large_positive_offset`; `tests/test_zone_mapper.py::test_zone_mapper_offset_rotation` | `src/nanoleaf_sync/color/zone_mapper.py`; `src/nanoleaf_sync/runtime/calibration_resolver.py` |
| P-06 | Fine-tuning enforces 4-slot shape, pads missing values, and clamps to ±24. | Automated | `tests/test_calibration_state.py::test_corner_refinement_clamps_to_supported_limit`; `tests/test_calibration_state.py::test_corner_refinement_active_offsets_pad_missing_values`; `tests/test_zone_mapper.py::test_zone_mapper_corner_adjustments_stay_local_to_each_corner` | `src/nanoleaf_sync/ui/calibration_state.py`; `src/nanoleaf_sync/color/zone_mapper.py` |
| P-07 | Final completion gate requires all steps passed and confidence >= 1.0 with sentinel consistency. | Automated | `tests/test_calibration_flow.py::test_calibration_step_fail_keeps_completion_gate_closed`; `tests/test_calibration_flow.py::test_calibration_completion_requires_validation_score_threshold`; `tests/test_calibration_state.py::test_validation_report_tracks_confidence_and_sentinel_consistency` | `src/nanoleaf_sync/ui/calibration_state.py`; `src/nanoleaf_sync/ui/calibration_flow.py` |
| P-08 | Failure paths provide remediation hints (direction, anchors, replay, sentinel mismatch). | Automated + manual review | `tests/test_calibration_flow.py::test_calibration_completion_requires_validation_score_threshold`; `tests/test_calibration_state.py::test_validation_report_tracks_confidence_and_sentinel_consistency` | `src/nanoleaf_sync/ui/calibration_state.py`; `src/nanoleaf_sync/ui/calibration_flow.py` |
| P-09 | Canonical nested calibration payload is migration-safe and used as mapping source across runtime/UI. | Automated | `tests/test_config.py::test_resolver_reads_nested_calibration_model_and_anchors`; `tests/test_zone_calibration.py::test_mapping_snapshot_from_config_uses_nested_calibration_payload`; `tests/test_display_configurator.py::test_display_configurator_uses_corner_anchor_model` | `src/nanoleaf_sync/config/model.py`; `src/nanoleaf_sync/config/normalize.py`; `src/nanoleaf_sync/runtime/calibration_resolver.py`; `src/nanoleaf_sync/ui/display_configurator.py` |

### Release gate usage

- **Required:** P-01 through P-08 green in CI (or documented waiver).
- **Required:** at least one manual walkthrough for Journey A or B and one recovery journey (C/D/E).
- **Required:** if any checklist item’s owning tests/files change, update this spec in the same PR.
