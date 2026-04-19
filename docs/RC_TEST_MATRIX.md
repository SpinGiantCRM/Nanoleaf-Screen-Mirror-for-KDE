# RC Test Matrix

Use this matrix before tagging a release.

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
