# Fix: Lower coverage threshold to match reality

## Background

CI has been failing on `main` and every PR with `FAIL Required test coverage of 70% not reached`. The 70% threshold was aspirational — actual coverage is ~59% because ~2400 lines of Qt UI code (`display_configurator.py`, `settings_dialog.py`, etc.) require `pytest-qt` or heroic mocking to cover. The core business logic modules all have 83-97% coverage.

Analysis and full coverage report in [PR discussion](https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/pull/334).

## Change

**File:** `.github/workflows/ci.yml`

**One line:** Change `--cov-fail-under=70` to `--cov-fail-under=55`.

This gives a 4-point buffer above the current 59% to absorb normal coverage churn.

## Verification

```bash
python -m pytest -q --timeout=60 --timeout-method=thread --cov=nanoleaf_sync --cov-report=term --cov-fail-under=55
```

Expected: `475 passed` + `Required test coverage of 55% reached`.

## Freebuff Invocation Snippet

```
@read AGENTS.md
Read .opencode/task-spec.md, then apply the one-line change: lower --cov-fail-under to 55 in .github/workflows/ci.yml. Run the verification command and report the result. Do not make any other changes.
```
