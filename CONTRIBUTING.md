# Contributing

Thanks for helping improve `nanoleaf-kde-sync`.

## Before you start

- Read `docs/REPOSITORY_MAP.md` for a fast orientation to code ownership and file intent.
- Read `docs/TECHNICAL_DESIGN.md` if your change touches runtime/capture/color/device flow.
- Keep changes small and focused; mixed refactor + feature + release edits are hard to review.

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
pip install -e .[test]
pytest -q
```

## Documentation expectations (required)

This repository treats documentation as part of the product, not optional cleanup.

When you change behavior, update related docs in the same PR:
- user-visible behavior: root `README.md` and relevant docs in `docs/`
- architecture/pipeline behavior: `docs/TECHNICAL_DESIGN.md`
- file movement/new modules: `docs/REPOSITORY_MAP.md`
- release/runtime commands: `docs/SMOKE_TEST.md` / `docs/RELEASE_CHECKLIST.md` where applicable

If you find stale or duplicate documentation while implementing a change, fix or remove it in the same PR when safe.

## Scope guidance for current release cycle

High-value contributions:
- diagnostics and troubleshooting quality
- packaging consistency
- release/CI reliability
- small UX polish that keeps tray/service behavior stable
- documentation improvements that reduce maintainer/onboarding ambiguity

Please avoid large protocol/capture redesigns unless they are release blockers.
