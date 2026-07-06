# Feature matrix

Tracks whether each user-facing or config-level feature is implemented, wired through the mirroring runtime, surfaced in Settings, documented, and covered by automated tests.

Update this file when adding config fields, pipeline behaviour, UI controls, or docs.

| Feature | Implemented | Runtime-wired | UI surfaced | Documented | Tested | Notes |
|---------|:-----------:|:-------------:|:-----------:|:----------:|:------:|-------|
| Zone temporal accumulation | Yes | Yes | No | Partial | Yes | Config default on; internal pipeline quality |
| Blue-noise dither | Yes | Yes | No | No | Yes | Config default on |
| Zone box-filter sampling | Yes | Yes | No | No | Yes | Config default on |
| Multi-moment zone colours | Yes | Yes | No | No | Partial | Default off |
| Privacy zones | Yes | Yes | Yes | Yes | Yes | Advanced settings numeric editor |
| Virtual zone oversample | Yes | Yes | No | No | Partial | Config/API only (0 = disabled) |
| Scene-adaptive profiles | Yes | Yes | No | No | Partial | Internal/experimental; default off |
| 4D sync (`sync_mode=4d`) | Yes | Yes | Yes | Yes | Yes | Everyday settings checkbox |
| Predictive sync strength | Yes | Yes | No | Partial | Partial | Config only |
| Custom display gamut | Partial | Yes | No | Partial | Partial | Hidden from combo until chromaticity editor |
| Display preset (SDR/HDR/Auto) | Yes | Yes | Yes | Yes | Yes | Default: Auto |
| Capture monitor selection | Yes | Yes | Yes | Yes | Partial | One monitor only; not multi-monitor mirroring |
| HDR transfer / primaries | Yes | Yes | Yes | Yes | Yes | Colour settings |
| Backend auto-probe | Yes | Yes | Yes | Partial | Yes | Advanced capture settings |
| kmsgrab DRM zone patch | Yes | Yes | Partial | Partial | Yes | Advanced / 4D preset side effect |
| Live diagnostics overlay | Yes | Yes | Yes | Partial | Yes | Advanced diagnostics |
| Diagnostic bundle export | Yes | Yes | Yes | Yes | Yes | Help & Diagnostics |
| Benchmark CLI | Yes | N/A | N/A | Yes | Yes | `nanoleaf-kde-sync-benchmark` |
| Multi-monitor mirroring | No | No | No | Yes | N/A | Not planned (see ROADMAP.md) |
| Multiple USB strips | No | No | No | Yes | N/A | Not planned |
| Non-KDE desktops | No | No | No | Yes | N/A | Not planned |

## Legend

- **Implemented**: logic exists in source (config + pipeline or equivalent).
- **Runtime-wired**: active mirroring path passes the setting into `process_zone_colors` (via `build_pipeline_params_from_config` → `process_frame(params=…)`).
- **UI surfaced**: visible control in Settings or first-run wizard (not config-file-only).
- **Documented**: mentioned in USER_GUIDE, TROUBLESHOOTING, or a dedicated doc linked from README.
- **Tested**: automated test asserts behaviour or config round-trip (not manual-only).

## Maintenance

When landing a new feature:

1. Add or update the row here before merge.
2. Add a wiring test in `tests/test_config_pipeline_wiring.py` if the feature is config-driven pipeline behaviour.
3. Add a UI contract test in `tests/test_ui_config_contract.py` if the feature has a Settings control.
