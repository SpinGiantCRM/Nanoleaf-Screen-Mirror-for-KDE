# Repo cull audit (2026-04-20)

This audit is focused on reducing maintenance drag without changing core functionality.

## Completion status (implemented)

- ✅ Removed `docs/requirements.txt` and switched contributor install guidance to `pip install -e .[test]`.
- ✅ Made release PR body the source of truth for RC evidence; matrix doc is now optional historical archive.
- ✅ Documented `nanoleaf-kde-sync-rc-runner` invocation and added tests for row output contract.
- ✅ Standardized on `scripts/setup_udev.sh` as the canonical udev installation path across docs.
- ✅ Moved vendor protocol PDF from repo root to `docs/reference/` and recorded checksum metadata.
- ✅ Fixed the failing runtime flow test (`tests/test_runtime_real_driver_flow.py::test_run_loop_with_usb_driver_initializes_then_sends_frame`) so cleanup proceeds from a green baseline.

## High-confidence keepers (providing clear value)

- Core app/runtime/capture/device modules under `src/nanoleaf_sync/**` are covered by broad tests and are in active use via entry points.
- CI and release version guards (`scripts/check_release_versions.py`) prevent mismatched package metadata, tags, and artifact naming.
- Troubleshooting + hardware setup docs are practical and referenced from README.

## Cull candidates (trim first, remove later if desired)

### 1) `docs/requirements.txt` is redundant maintenance

- It duplicates dependency definitions that already live in `pyproject.toml` (runtime + test extras).
- It is only referenced as an optional command in `CONTRIBUTING.md`, which can drift and create confusion.

Recommendation:
- Stop maintaining this file manually.
- Either remove it or generate it from project metadata when needed.

Risk if kept as-is:
- Dependency drift between contributor docs and actual install/test paths.

### 2) Release process has multiple overlapping surfaces

Current release flow spans:
- `.github/workflows/release.yml`
- `.github/PULL_REQUEST_TEMPLATE/release.md`
- `docs/RC_TEST_MATRIX.md`
- CLI helper `src/nanoleaf_sync/tools/rc_runner.py`

This is useful, but currently heavy and partly manual.

Recommendation:
- Pick one “source of truth” for RC evidence (PR template _or_ docs matrix), then link to the other instead of requiring both.
- If `rc_runner` is meant to be part of the flow, add a short invocation block in docs and at least one test around its output contract.

Risk if kept as-is:
- Process friction and stale instructions across multiple places.

### 3) `scripts/setup_udev.sh` duplicates documented manual steps

- README + docs already provide direct `install`/`udevadm` commands.
- The script is not integrated into packaging or CI.

Recommendation:
- Decide one path: keep script as the canonical installer and point docs to it, or remove script and keep explicit commands only.

Risk if kept as-is:
- Two parallel workflows to maintain for the same task.

### 4) Reference PDF in repo root increases repository weight

- `NOAD1-Nanoleaf USB Lightstrip Communication Protocol-170426-150729.pdf` appears to be a static vendor reference and is not part of runtime/package flow.

Recommendation:
- Move to `docs/reference/` (clear intent) or replace with a link + checksum note in docs.

Risk if kept as-is:
- Root clutter and larger clone footprint without direct build/runtime value.

## Functional risk found during audit

- Full test run is near-clean but has one failing runtime flow test (`tests/test_runtime_real_driver_flow.py::test_run_loop_with_usb_driver_initializes_then_sends_frame`).

Recommendation:
- Resolve this first before larger cleanup so refactors are done from a green baseline.

## Suggested phased cleanup plan

1. **Phase 1 (low-risk):** simplify docs/process references and choose one udev path.
2. **Phase 2 (confidence):** make `rc_runner` explicitly documented/tested or demote it from supported workflow.
3. **Phase 3 (hygiene):** move large reference artifacts out of repo root.
4. **Phase 4 (safety):** keep CI as quality gate after each reduction.

## Bottom line

Your repository is mostly useful and purposeful.
The main “crap” is not core code; it is process overlap and duplicated maintenance surfaces.
