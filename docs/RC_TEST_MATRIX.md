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

| Env ID | OS | Session | Mode | Doctor | Smoke | Tray lifecycle | Notes |
|---|---|---|---|---|---|---|---|
| A1 | Arch | Wayland | full-mock |  |  |  |  |
| A2 | Arch | X11 | capture-real |  |  |  | Expected: real capture is not supported on X11 in the current scope (compatibility check only). |
| C1 | CachyOS | Wayland | full-real |  |  |  |  |
| C2 | CachyOS | X11 | full-mock |  |  |  | Expected: mock mode should be functional; real capture is not required (compatibility check only). |
