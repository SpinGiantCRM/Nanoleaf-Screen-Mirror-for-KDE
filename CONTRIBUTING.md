# Contributing

Thank you for helping improve Nanoleaf Screen Mirror for KDE.

## Scope

- Single Nanoleaf USB strip only — no multi-device or plugin framework
- KDE Plasma 6 + Wayland assumptions
- Prefer `kwin-dbus` capture; portal is fallback/manual benchmark path

Read [AGENTS.md](AGENTS.md) for durable project rules.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
pre-commit install
```

## Validation (must pass before PR)

```bash
./scripts/release_gate.sh
```

Or run individually:

```bash
python scripts/check_release_versions.py
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/nanoleaf_sync --ignore-missing-imports --follow-imports=silent
bandit -r src/ -c pyproject.toml
pip-audit --path .
QT_QPA_PLATFORM=offscreen python -m pytest -q --timeout=60 --timeout-method=thread \
  --cov=nanoleaf_sync --cov-fail-under=75
```

## Test coverage notes

Large UI modules (`settings_dialog`, `display_configurator`, etc.) are omitted from coverage metrics because they are monolithic Qt dialogs. Critical tray/settings behavior is covered by headless Qt tests in `tests/test_ui_headless.py` and source-structure tests.

## Pull requests

- Keep diffs focused; match existing style (type hints, ruff, no unnecessary comments)
- Include tests for behavior changes
- Update user docs when install or UX changes
- Do not commit secrets or local build artifacts under `packaging/arch/pkg/`

## Manual verification

For capture, HID, or tray changes, run the [Security manual release checklist](docs/SECURITY.md#manual-release-checklist-kde-integration) on a real KDE Plasma 6 session.
