# RC Test Matrix

Use this matrix as an optional historical archive of completed release evidence.
The release PR body (`.github/PULL_REQUEST_TEMPLATE/release.md`) is the source of truth before tagging.

## CLI helper (row generator)

Use `nanoleaf-kde-sync-rc-runner` to produce a status summary and copy/paste-ready row:

```bash
nanoleaf-kde-sync-rc-runner --mode diagnostic --env-id A1 --rc-version vX.Y.Z-rcN --tester @handle
```

For real hardware validation on required environments:

```bash
nanoleaf-kde-sync-rc-runner --mode full-real --env-id C1 --rc-version vX.Y.Z-rcN --tester @handle
```

## Required evidence

- Record the exact package/app version under test.
- Capture outputs for `nanoleaf-kde-sync-doctor` and `nanoleaf-kde-sync-smoke-test`.
- Note whether testing used real hardware or mock mode.
- For calibration changes, include pass/fail evidence for `docs/CALIBRATION_PARITY_SPEC.md` items P-01..P-08.

## Calibration release criteria (required when calibration code changes)

1. Run focused checks for config migration + resolver consistency:
   - `pytest -q tests/test_config.py tests/test_corner_anchor_calibration.py`
2. Run focused checks for setup/settings/wizard surfaces:
   - `pytest -q tests/test_calibration_state.py tests/test_zone_calibration.py tests/test_display_configurator.py`
3. Confirm no static issues in modified calibration/config/ui modules:
   - `ruff check src/nanoleaf_sync/config src/nanoleaf_sync/runtime src/nanoleaf_sync/ui`
4. Manual recovery walkthrough (record one):
   - Direction rollback (wrong direction -> rollback -> confirm restored state), or
   - Corner assignment rollback (invalid anchors -> rollback -> confirm previous checkpoint).

Attach command output snippets (or CI links) in the release PR for traceability.

## Staged rollout safety plan (calibration-sensitive releases)

Use phased rollout to catch edge-case calibration regressions before broad exposure.

### 1) Gate rollout and collect focused feedback

- **Alpha (internal + power users, 5-10% of active install base, Days 1-2):**
  - Enable release only for opt-in testers.
  - Ask for feedback on calibration reliability with a short template:
    - "Did calibration finish end-to-end?"
    - "Were repeated re-calibrations needed within 24h?"
    - "Was anchor validation messaging clear/confusing?"
- **Beta (25-40% of active install base, Days 3-5):**
  - Expand only if alpha rollback criteria are not triggered.
  - Continue collecting the same calibration-focused feedback fields.
- **Canary broad (60-80%, Days 6-7):**
  - Expand if beta remains healthy.
  - Monitor telemetry markers and user reports daily.

### 2) Rollback criteria (trigger immediate pause + patch triage)

Rollback to previous stable build (or halt further rollout) if any of the following occur during any phase:

- Calibration completion failure rate rises above **3%** of calibration attempts.
- Repeated re-calibration reports exceed **10%** of feedback responses.
- Anchor validation confusion reports exceed **5%** of feedback responses.
- Any hard regression causes blocked completion in required phases (`direction-verification`, `corner-assignment`, `validation-replay`) across multiple environments.

### 3) Lightweight telemetry/log markers (no sensitive payloads)

Track only phase IDs and generic failure causes; never log user-entered free-text or display content.

- `telemetry.calibration.phase_complete`:
  - `phase=<step_id>`, `passed=<true|false>`, `failure_cause=<enum>`
- `telemetry.calibration.flow_blocked`:
  - `phase=<step_id>`, `failure_cause=<enum>`
- `telemetry.calibration.flow_evaluated`:
  - `allowed=<true|false>`, `outcome=<pass|fail>`, `confidence=<0.00-1.00>`, `sentinel_consistency=<true|false>`
- `telemetry.calibration.phase_invalidation`:
  - `trigger=zone_count_change`, `invalidated_count=<n>`, `next_phase=<step_id>`

Failure-cause enums should remain low-cardinality (e.g., `prerequisites`, `not_marked_passed`, `anchor_validation`, `confidence`, `sentinel_mismatch`, `validation_failed`, `unknown`).

### 4) End-of-window release decision

At the close of the rollout window (recommended: 7 days):

- **Full release** if rollback criteria were never met and telemetry remains stable through canary.
- **Patch cycle** if any rollback criterion triggered, or if qualitative feedback indicates persistent anchor-validation confusion despite acceptable quantitative rates.

Record the decision and rationale in the release PR body and changelog notes.

## Executed RC evidence (2026-04-22)

Version under test: `v0.0.0-rc1` (local validation run).

| Env ID | OS | Session | Mode | Doctor | Smoke | Tray lifecycle | Calibration evidence refs | Notes |
|---|---|---|---|---|---|---|---|---|
| A1 | Arch-like CI container | headless (no Plasma session bus) | diagnostic | ❌ | ❌ | N/A | `docs/PHYSICAL_CALIBRATION_VALIDATION_LOG.md` required scenarios + recovery rows | Doctor failed on missing `DBUS_SESSION_BUS_ADDRESS`; smoke fell back to `kwin-dbus` and failed `kwin-no-api` in headless environment. |
| A2 | Arch-like CI container | headless (X11 compatibility only) | diagnostic | ❌ | ❌ | N/A | P-01/P-02/P-05 reflected in parity test pass run (see command outputs below) | Compatibility check only; real capture not validated in this environment due absent desktop bus. |
| C1 | CachyOS target profile (real-hardware gate criteria) | Wayland | full-real | ❌ | ❌ | N/A | `docs/PHYSICAL_CALIBRATION_VALIDATION_LOG.md` rows for 24/48-zone calibration + interruption/resume | Full-real command path blocked in container due no HID + no session bus; keep row as hold evidence until on-device rerun. |
| C2 | CachyOS target profile | X11 | full-mock (planned) | N/A | N/A | N/A | Pending | Pending physical lab execution; not executed in this container. |

### Doctor output snapshots

- `nanoleaf-kde-sync-doctor` (exit 1): failed checks `session-bus` and `hid-device`; passed python/dependencies/mode-consistency.
- `nanoleaf-kde-sync-doctor --device` (exit 1): failed checks `session-bus`, `hid-device`, `device-probe`; warns unresolved screenshot API due missing DBus session.

### Smoke output snapshots

- `nanoleaf-kde-sync-smoke-test` (exit 1): `capture auto-probe yielded no qualified backend`, `effective=kwin-dbus`, then `capture failed: kind=kwin-no-api`.
- `nanoleaf-kde-sync-smoke-test --send-test-frame` (exit 1): same capture failure path before frame send due absent KWin screenshot APIs in headless environment.

### Calibration-focused command evidence

| Check | Command | Result | Evidence |
|---|---|---|---|
| Config/resolver parity | `pytest -q tests/test_config.py tests/test_corner_anchor_calibration.py` | ✅ Pass | Included in aggregated run below (105 passed). |
| Setup/settings/wizard parity | `pytest -q tests/test_calibration_state.py tests/test_zone_calibration.py tests/test_display_configurator.py` | ✅ Pass | Included in aggregated run below (105 passed). |
| Combined focused parity batch | `pytest -q tests/test_config.py tests/test_corner_anchor_calibration.py tests/test_calibration_state.py tests/test_zone_calibration.py tests/test_display_configurator.py` | ✅ Pass | `105 passed in 1.05s` on 2026-04-22. |
| Static lint gate on calibration/config/ui modules | `ruff check src/nanoleaf_sync/config src/nanoleaf_sync/runtime src/nanoleaf_sync/ui` | ❌ Fail | Existing repository lint baseline (150 findings), including unused import/variable and multi-statement formatting violations in UI modules. |
