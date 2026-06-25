## Release PR summary

- Target version: `vX.Y.Z-rcN`
- Planned tag date (UTC): `YYYY-MM-DD`
- Changelog section updated: yes/no
- Planned release title: `nanoleaf-kde-sync vX.Y.Z-rcN — Nanoleaf screen mirroring for KDE Plasma on Linux.`

## RC matrix sign-off (required before tagging)

> Do not tag until every required matrix row/mode has evidence linked below.
> The evidence in this PR body is the release source of truth.

Reference:
- `docs/SMOKE_TEST.md`
- Evidence attached in this PR body is authoritative for RC matrix and physical calibration sign-off.

### Matrix execution checklist

- [ ] Arch Wayland run(s) completed
- [ ] Arch X11 run(s) completed
- [ ] CachyOS Wayland run(s) completed
- [ ] CachyOS X11 run(s) completed
- [ ] `full-mock` scenario completed
- [ ] `capture-real` scenario completed
- [ ] `full-real` scenario completed (or marked N/A with reason)
- [ ] Doctor checks pass for required scenarios
- [ ] Smoke checks pass for required scenarios
- [ ] Tray Start/Stop/Status lifecycle verified
- [ ] RC run results captured in artifact table in this PR body
- [ ] Optional: mirrored rows appended to a tracked release note or follow-up docs PR after sign-off

## RC run results artifact

| Date (UTC) | RC version | Env ID | Mode | Doctor | Smoke | Tray lifecycle | Tester | Notes |
|---|---|---|---|---|---|---|---|---|
| YYYY-MM-DD | vX.Y.Z-rcN | A1 | diagnostic |  |  |  | @handle |  |

## Calibration staged rollout notes

### Rollout phase outcomes

- **Alpha (Days 1-2, 5-10% rollout):**
  - Outcome:
  - Signals:
- **Beta (Days 3-5, 25-40% rollout):**
  - Outcome:
  - Signals:
- **Canary (Days 6-7, 60-80% rollout):**
  - Outcome:
  - Signals:

### Rollback-trigger check summary

- Calibration completion failure >3%:
- Repeated re-calibration reports >10%:
- Anchor validation confusion >5%:
- Multi-environment blocked completion in required phases:

### Promote/hold decision

- **Decision:** PROMOTE/HOLD.
- **Rationale:**

## Final release gate

- [ ] I confirm matrix sign-off is complete and evidence is attached before creating/pushing release tag.
