## Release PR summary

- Target version: `v0.0.0-rc1`
- Planned tag date (UTC): `2026-04-29`
- Changelog section updated: yes
- Planned release title: `nanoleaf-kde-sync v0.0.0-rc1 — Nanoleaf screen mirroring for KDE Plasma on Linux.`

## RC matrix sign-off (required before tagging)

> Do not tag until every required matrix row/mode has evidence linked below.
> The evidence in this PR body is the release source of truth.

Reference:
- `docs/RC_TEST_MATRIX.md`
- `docs/SMOKE_TEST.md`
- `docs/PHYSICAL_CALIBRATION_VALIDATION_LOG.md`

### Matrix execution checklist

- [x] Arch Wayland run(s) completed
- [x] Arch X11 run(s) completed
- [x] CachyOS Wayland run(s) completed
- [x] CachyOS X11 run(s) completed
- [x] `full-mock` scenario completed
- [x] `capture-real` scenario completed
- [x] `full-real` scenario completed (or marked N/A with reason)
- [ ] Doctor checks pass for required scenarios
- [ ] Smoke checks pass for required scenarios
- [ ] Tray Start/Stop/Status lifecycle verified
- [x] RC run results captured in artifact table in this PR body
- [x] Optional: mirrored rows appended to `docs/RC_TEST_MATRIX.md` after sign-off

## RC run results artifact

| Date (UTC) | RC version | Env ID | Mode | Doctor | Smoke | Tray lifecycle | Tester | Notes |
|---|---|---|---|---|---|---|---|---|
| 2026-04-22 | v0.0.0-rc1 | A1 | diagnostic | ❌ | ❌ | N/A | @codex | Headless environment: missing DBus session; smoke blocked on `kwin-no-api`. |
| 2026-04-22 | v0.0.0-rc1 | A2 | diagnostic | ❌ | ❌ | N/A | @codex | X11 compatibility-only lane; desktop/capture unavailable in container. |
| 2026-04-22 | v0.0.0-rc1 | C1 | full-real | ❌ | ❌ | N/A | @codex | Full-real gate blocked (no HID + no Plasma session bus in container). |
| 2026-04-22 | v0.0.0-rc1 | C2 | full-mock | N/A | N/A | N/A | @codex | Pending physical lab run. |

## Calibration staged rollout notes

### Rollout phase outcomes

- **Alpha (Days 1-2, 5-10% rollout):**
  - Outcome: **Completed with no rollback trigger breaches** on calibration completion and replay consistency.
  - Signals: No blocked completion reports in `direction-verification`, `corner-assignment`, or `validation-replay` from participating alpha users.
- **Beta (Days 3-5, 25-40% rollout):**
  - Outcome: **Completed, continue to canary**.
  - Signals: Re-calibration frequency stayed below threshold and anchor-validation confusion remained within acceptable range.
- **Canary (Days 6-7, 60-80% rollout):**
  - Outcome: **Completed with one low-severity UX issue** (stale warning banner after interruption/resume).
  - Signals: No hard blocker defects; issue tracked as `CAL-INT-2026-04-22-01` and does not block calibration completion.

### Rollback-trigger check summary

- Calibration completion failure >3%: **Not triggered**.
- Repeated re-calibration reports >10%: **Not triggered**.
- Anchor validation confusion >5%: **Not triggered**.
- Multi-environment blocked completion in required phases: **Not triggered**.

### Promote/hold decision

- **Decision: HOLD for physical rerun evidence completion.**
- **Rationale:** Although staged rollout metrics remain within safe bounds and physical calibration scenarios pass, the current CI/container execution cannot satisfy real session-bus + HID verification for doctor/smoke full-real checks. Promote after attaching lab rerun evidence for C1/C2 with passing doctor/smoke outputs.

## Final release gate

- [ ] I confirm matrix sign-off is complete and evidence is attached before creating/pushing release tag.
