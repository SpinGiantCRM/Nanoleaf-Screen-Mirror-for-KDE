# RC Test Matrix

Use this matrix before tagging a release.

| Env ID | OS | Session | Mode | Doctor | Smoke | Tray lifecycle | Notes |
|---|---|---|---|---|---|---|---|
| A1 | Arch | Wayland | full-mock |  |  |  |  |
| A2 | Arch | X11 | capture-real |  |  |  | Expected: real capture not supported on X11 in current scope (compatibility check). |
| C1 | CachyOS | Wayland | full-real |  |  |  |  |
| C2 | CachyOS | X11 | full-mock |  |  |  | Expected: mock mode functional; real capture not required (compatibility check). |
