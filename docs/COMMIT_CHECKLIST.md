# 12-Commit Execution Checklist

This checklist breaks the remaining roadmap work into 12 focused commits.

| # | Commit Goal | Status |
|---|-------------|--------|
| 1 | Replace placeholder `cursor/` folder name with `docs/` and normalize references. | ✅ Done |
| 2 | Fix packaging metadata/readme path and install instructions to match repository layout. | ✅ Done |
| 3 | Add config validation/clamping helpers for runtime-critical fields. | ⬜ Pending |
| 4 | Add corruption-safe config load behavior and regression tests. | ⬜ Pending |
| 5 | Implement atomic config writes (`tempfile` + `replace`) and tests. | ⬜ Pending |
| 6 | Add service-loop per-frame exception shielding with observability counters. | ⬜ Pending |
| 7 | Extend `get_status()` / mode reporting for UI-safe state transitions. | ⬜ Pending |
| 8 | Add calibration profile builder + migration utility scaffolding. | ⬜ Pending |
| 9 | Add benchmark script and baseline performance output format. | ⬜ Pending |
| 10 | Add CI workflow for tests + benchmark smoke gate. | ⬜ Pending |
| 11 | Add structured event export endpoint with contract tests. | ⬜ Pending |
| 12 | Prepare release notes + integration handoff for proprietary driver drop-in. | ⬜ Pending |

## Notes
- Commits 1-2 are now complete.
- Commits 3-12 are the active implementation runway.
