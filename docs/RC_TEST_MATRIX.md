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

| Env ID | OS | Session | Mode | Doctor | Smoke | Tray lifecycle | Notes |
|---|---|---|---|---|---|---|---|
| A1 | Arch | Wayland | full-mock |  |  |  |  |
| A2 | Arch | X11 | capture-real |  |  |  | Expected: real capture is not supported on X11 in the current scope (compatibility check only). |
| C1 | CachyOS | Wayland | full-real |  |  |  |  |
| C2 | CachyOS | X11 | full-mock |  |  |  | Expected: mock mode should be functional; real capture is not required (compatibility check only). |
