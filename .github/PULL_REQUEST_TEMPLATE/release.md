## Release PR summary

- Target version: `vX.Y.Z` / `vX.Y.Z-rcN`
- Planned tag date (UTC): `YYYY-MM-DD`
- Changelog section updated: yes/no
- Planned release title: `nanoleaf-kde-sync vX.Y.Z — Nanoleaf screen mirroring for KDE Plasma on Linux.`

## RC matrix sign-off (required before tagging)

> Do not tag until every required matrix row/mode has evidence linked below.
> The evidence in this PR body is the release source of truth.

Reference:
- `docs/RC_TEST_MATRIX.md`
- `docs/SMOKE_TEST.md`

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
- [ ] Optional: mirrored rows appended to `docs/RC_TEST_MATRIX.md` after sign-off

## RC run results artifact

Paste completed rows (or link to committed table updates):

| Date (UTC) | RC version | Env ID | Mode | Doctor | Smoke | Tray lifecycle | Tester | Notes |
|---|---|---|---|---|---|---|---|---|
| YYYY-MM-DD | vX.Y.Z-rcN | A1/A2/C1/C2 | full-mock/capture-real/full-real | ✅/❌/N/A | ✅/❌/N/A | ✅/❌/N/A | @handle | logs/screenshots/issues |

## Final release gate

- [ ] I confirm matrix sign-off is complete and evidence is attached before creating/pushing release tag.
