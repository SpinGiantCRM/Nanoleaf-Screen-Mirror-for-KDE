# Contributing

Thanks for helping improve `nanoleaf-kde-sync`.

## Bug reports

Please use GitHub issue templates and include:
- exact version/tag
- install method (Arch package, pip, source)
- `nanoleaf-kde-sync-doctor` output
- `nanoleaf-kde-sync-smoke-test` output
- minimal reproduction steps

If you can reproduce only in real USB mode, include `nanoleaf-kde-sync-doctor --device` output.

## Development setup

```bash
pip install -r docs/requirements.txt
pip install -e .
pytest -q
```

## Scope guidance for first public RC

High-value contributions right now:
- diagnostics and troubleshooting quality
- packaging consistency
- release/CI reliability
- small UX polish that keeps tray/service behavior stable

Please avoid large protocol/capture redesigns unless they are release blockers.
