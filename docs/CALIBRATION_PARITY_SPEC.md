# CALIBRATION_PARITY_SPEC

## Purpose

This document is the strict calibration behavior contract shared by Engineering and QA. Calibration changes are not releasable unless behavior remains compliant with this contract or the contract is updated in the same pull request.

## Contract scope

This contract governs calibration behavior in:

- Setup/onboarding calibration wizard.
- Settings calibration workflow.
- Runtime calibration mapping resolution and validation.

Primary owner modules:

- `src/nanoleaf_sync/ui/calibration_flow.py`
- `src/nanoleaf_sync/ui/calibration_state.py`
- `src/nanoleaf_sync/ui/zone_calibration.py`
- `src/nanoleaf_sync/runtime/calibration_resolver.py`
- `src/nanoleaf_sync/runtime/anchor_calibration.py`
- `src/nanoleaf_sync/color/zone_mapper.py`

---

## 1) Calibration phases (strict order)

Calibration MUST execute in this exact order:

1. **Start-zone identification**
2. **Direction verification**
3. **Corner assignment**
4. **Fine adjustment**
5. **Final validation**

Rules:

- A phase is not passable until all prior phases are passed.
- Final completion MUST remain blocked unless all phases pass.
- Regressing any previously passed phase MUST invalidate completion status.

---

## 2) Expected user interactions per phase

### Phase 1: Start-zone identification

**User does**

- Starts the calibration walk.
- Confirms whether highlighted active zone matches expected physical start (top-left logical origin).

**App must show**

- Exactly one active/highlighted zone at a time.
- Controls to confirm correct start or retry walk.
- Gated progression (Phase 2 disabled until pass).

**Pass condition**

- User confirms correct start-zone and state records phase as passed.

**Fail condition**

- User rejects start-zone or exits phase without confirmation.

### Phase 2: Direction verification

**User does**

- Runs forward/reverse zone traversal preview.
- Toggles direction when traversal appears mirrored.
- Confirms direction after a full cycle check.

**App must show**

- Current direction setting and live mapping preview changes.
- Stable wrap-around cycle behavior for full zone count.
- Phase 3 remains blocked until pass.

**Pass condition**

- User-confirmed traversal direction matches physical progression and full cycle wraps deterministically.

**Fail condition**

- Traversal is mirrored/incorrect or user does not confirm direction.

### Phase 3: Corner assignment

**User does**

- Assigns anchors for corners in canonical order: TL, TR, BR, BL.
- Corrects duplicates/out-of-range selections when prompted.

**App must show**

- Corner labels in immutable TL/TR/BR/BL order.
- Immediate validity feedback for duplicate and out-of-range anchors.
- Recovery guidance when anchors are invalid.

**Pass condition**

- All required anchors are unique, in-range, and accepted by validation.

**Fail condition**

- Any duplicate, missing, or out-of-range anchor.

### Phase 4: Fine adjustment

**User does**

- Applies per-corner micro-adjustments to alignment.
- Iterates until local edge drift is corrected.

**App must show**

- Four-slot adjustment model `[TL, TR, BR, BL]`.
- Clamped values and updated preview behavior after each adjustment.
- Deterministic mapping updates.

**Pass condition**

- Adjustment values validate and preview alignment is acceptable for user confirmation.

**Fail condition**

- Invalid adjustment data model (wrong shape/type) or unresolved severe drift.

### Phase 5: Final validation

**User does**

- Runs replay/validation over full mapping.
- Reviews confidence and mismatch diagnostics.
- Confirms completion only if all checks pass.

**App must show**

- Validation confidence and per-check status.
- Sentinel/anchor consistency diagnostics.
- Clear remediation hints when failed.

**Pass condition**

- Every prior phase passed.
- Validation confidence is exactly `1.00` (strict threshold).
- Sentinel/anchor assignment consistency check passes.
- Completion is blocked unless all strict checks pass (no warning-level completion path, no override path).

**Fail condition**

- Any failed prerequisite.
- Confidence below strict threshold.
- Any sentinel consistency mismatch (treated as hard fail).

---

## 3) Mapping semantics by calibration model

### A) Offset + direction model (`offset_direction`)

Contract:

- Mapping is rotational with modulo normalization.
- `zone_offset` MAY be positive or negative; resolved mapping MUST be modulo-normalized.
- Direction flag MUST deterministically invert traversal semantics without mutating stored offset.
- Full-cycle traversal MUST return to origin after exactly `N` steps for `N` zones.

### B) Corner-anchored model (`corner_anchored`)

Contract:

- Mapping is anchored by explicit TL/TR/BR/BL corner assignments.
- Anchor set MUST be unique and in-range.
- Invalid anchors MUST NOT crash mapping; system MUST report invalid state and block completion.
- Derived transitions between anchors MUST remain deterministic for a fixed zone count and direction.

### C) Manual explicit map model (`manual_explicit_map`)

Contract:

- Mapping uses user-provided explicit zone list as authoritative source.
- Explicit indices MUST be normalized/clamped to legal source range before runtime use.
- If explicit list is shorter than device zone count, unmapped tail MUST fall back deterministically (default source index `0` unless explicitly changed in future contract revision).
- Duplicate explicit indices are allowed unless additional product rules forbid them.

---

## 4) Error and recovery behavior

### Invalid anchors

- Behavior: Flag validation error with specific corner(s), block phase pass and final completion.
- Recovery: User reassigns invalid anchors; validation reruns immediately.

### Duplicate anchors

- Behavior: Duplicate detection MUST be explicit and treated as invalid configuration.
- Recovery: User must select unique anchors for all required corners.

### Changed zone count (device/source)

- Behavior: Any zone count change after calibration MUST invalidate prior pass state and force re-validation from impacted phase(s).
- Behavior: Non-positive zone count inputs MUST normalize to a deterministic minimum for preview/runtime safety.
- Recovery: App prompts user to rerun affected phases, then final validation.

### Canceled wizard

- Behavior: Cancel MUST NOT commit partial calibration as completed.
- Behavior: If draft state persistence exists, it MUST be clearly marked non-final and MUST NOT bypass validation gates.
- Recovery: Re-enter wizard at first incomplete/invalid phase; complete full validation before commit.

---

## 5) Acceptance checklist (Engineering + QA)

| Spec item | Test file(s) | Owner module |
|---|---|---|
| Phase order is fixed: start-zone → direction → corner assignment → fine adjustment → final validation, with prerequisite gating. | `tests/test_calibration_flow.py` | `src/nanoleaf_sync/ui/calibration_flow.py` |
| Start-zone phase shows one active zone and blocks progression until confirmation. | `tests/test_zone_calibration.py`, `tests/test_calibration_flow.py` | `src/nanoleaf_sync/ui/zone_calibration.py`, `src/nanoleaf_sync/ui/calibration_state.py` |
| Direction toggle changes mapping deterministically and preserves stable wrap-around behavior. | `tests/test_zone_calibration.py`, `tests/test_calibration_flow.py`, `tests/test_zone_mapper.py` | `src/nanoleaf_sync/color/zone_mapper.py`, `src/nanoleaf_sync/ui/zone_calibration.py` |
| Corner assignment enforces TL/TR/BR/BL canonical order and uniqueness/in-range validation. | `tests/test_corner_anchor_calibration.py`, `tests/test_calibration_flow.py`, `tests/test_zone_calibration.py` | `src/nanoleaf_sync/runtime/anchor_calibration.py`, `src/nanoleaf_sync/ui/calibration_flow.py` |
| Fine adjustment uses exactly 4 slots and clamps values to supported limits. | `tests/test_calibration_state.py`, `tests/test_zone_mapper.py` | `src/nanoleaf_sync/ui/calibration_state.py`, `src/nanoleaf_sync/color/zone_mapper.py` |
| Final validation gate blocks completion on confidence/sentinel/anchor failures with no warning override path. | `tests/test_calibration_state.py`, `tests/test_calibration_flow.py`, `tests/test_display_configurator.py` | `src/nanoleaf_sync/ui/calibration_state.py`, `src/nanoleaf_sync/ui/calibration_flow.py`, `src/nanoleaf_sync/ui/display_configurator.py` |
| Offset+direction model obeys modulo normalization and deterministic inversion semantics. | `tests/test_zone_mapper.py`, `tests/test_calibration_flow.py` | `src/nanoleaf_sync/color/zone_mapper.py`, `src/nanoleaf_sync/runtime/calibration_resolver.py` |
| Corner-anchored model remains deterministic and fails safely on invalid anchors. | `tests/test_corner_anchor_calibration.py`, `tests/test_zone_calibration.py` | `src/nanoleaf_sync/runtime/anchor_calibration.py`, `src/nanoleaf_sync/runtime/calibration_resolver.py` |
| Manual explicit map model handles short maps with deterministic fallback and no crash. | `tests/test_zone_mapper.py`, `tests/test_calibration_surface_consistency.py` | `src/nanoleaf_sync/color/zone_mapper.py`, `src/nanoleaf_sync/runtime/calibration_resolver.py` |
| Changed zone count and canceled wizard cannot silently preserve invalid “completed” state. | `tests/test_calibration_state.py`, `tests/test_calibration_flow.py`, `tests/test_wizard_and_settings_structure.py` | `src/nanoleaf_sync/ui/calibration_state.py`, `src/nanoleaf_sync/ui/calibration_flow.py`, `src/nanoleaf_sync/ui/settings_dialog.py` |

---

## Out of scope

The following are explicitly out of scope for this contract revision:

- Redesign of calibration UX visuals/theme/layout.
- New calibration models beyond the three listed above.
- Device-specific heuristics for non-standard strip geometries.
- Auto-calibration powered by external sensors/cameras.
- Performance benchmarking and latency target policy.

Any future change to out-of-scope items requires a separate spec update before release.
