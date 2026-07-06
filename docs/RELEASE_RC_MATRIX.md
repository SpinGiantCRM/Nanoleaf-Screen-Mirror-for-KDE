# Release candidate test matrix

Record manual verification for each release candidate on real KDE + USB hardware before publishing.

## Matrix template

| Field | Value |
|-------|-------|
| RC version / git tag | |
| Tester | |
| Date | |
| Distro | |
| KDE Plasma version | |
| Session | Wayland / X11 |
| Strip model | NL82K1 / NL82K2 |
| Strip zone count | |
| Capture backend | auto / kwin-dbus / kmsgrab / xdg-portal |
| Display preset | SDR / HDR / Auto |
| Compositor HDR | on / off |
| Start mirroring | pass / fail |
| Stop mirroring (tray stays open) | pass / fail |
| Calibration test pattern | pass / fail |
| Neutral grey/white sanity | pass / fail |
| Black → off | pass / fail |
| 4D sync spot check (optional) | pass / fail / skipped |
| Doctor | pass / fail |
| Notes | |

## Minimum bar

- At least one **Wayland + Plasma 6** row with a physical strip
- **Stop** must stop LED output without quitting the tray app
- **Doctor** must pass or document accepted failures

## Evidence storage

Keep completed matrices in the GitHub release issue or RC test issue. Do not commit hardware-specific notes to the repo unless anonymized.

## Related

- [Smoke test](SMOKE_TEST.md)
- [Security manual checks](SECURITY.md)
- CI gates (pytest, benchmark baseline) do not replace this matrix
