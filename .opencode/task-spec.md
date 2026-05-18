# Audit Fix: P0-P1 Issues

## Scope

Fix bugs and issues found in the full repo audit (2026-05-16). All changes are bounded (1-5 lines per fix) except for two infra reconfigs.

## AGENTS.md Rules to Follow

- Do not introduce multi-device architecture
- Do not add automatic LED-count detection
- Do not perform architecture rewrites
- Prefer kwin-dbus capture backend
- Neutral grey/white must remain neutral and visible
- Black must map to off
- Fixes must preserve existing behavior unless correcting a bug

## Changes

### 1. B1 — Empty-plot guard in `diagnostics_exports.py`

**File:** `src/nanoleaf_sync/runtime/diagnostics_exports.py`

**Change:** In `_plot_diag_timeseries`, add an early return of `None` when `samples` is empty.

```python
# After the import guard block, before plt.subplots():
def _plot_diag_timeseries(
    samples: List[DiagFrameSample], title: str, window_title: str
) -> Optional[io.BytesIO]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    if not samples:
        return None

    fig, ax = plt.subplots(figsize=(10, 4))
    ...
```

### 2. DC1, DC2 — Dead code removal

**Files:**
- `src/nanoleaf_sync/config/store.py`
- `src/nanoleaf_sync/config/serialization.py`
- `src/nanoleaf_sync/__init__.py`

**Changes:**

**DC1:** Remove the `_dump_toml` wrapper function entirely (lines with `def _dump_toml`). Replace its only usage with `dump_toml` directly if any exist.

**DC2:** Remove the `_legacy_json_path` method and its sole call site.

**DC4:** Remove `from copy import deepcopy` from `serialization.py` (unused import).

**Q6:** Delete `src/nanoleaf_sync/__init__.py` (empty file). If build/import tests fail without it, recreate with `"""Nanoleaf Screen Mirror for KDE."""` and nothing more.

### 3. B3 — Calibration OOB warning

**File:** `src/nanoleaf_sync/color/zone_mapper.py`

**Change:** Inside `resolve_device_zone_indices`, after the modulo wrap, add a `logging.warning` when any `fixed_mapping[i] >= src_n`.

```python
if fixed_mapping:
    result = [int(fixed_mapping[i]) % src_n if i < len(fixed_mapping) else 0 for i in range(dst_n)]
    for i, orig in enumerate(fixed_mapping):
        if i < len(fixed_mapping) and int(orig) >= src_n:
            _log.warning(
                "Calibration zone %d (%s) out of range [0, %d); wrapped via modulo",
                i, orig, src_n - 1,
            )
    return result
```

Requires `import logging` and a module-level `_log = logging.getLogger(__name__)` at the top.

### 4. Q1 — Expand mypy to full source tree

**File:** `pyproject.toml`

**Change:** Replace:
```toml
[tool.mypy]
files = ["src/nanoleaf_sync/runtime"]
```
with:
```toml
[tool.mypy]
files = ["src/nanoleaf_sync"]
```

### 5. Q8 — Name all anonymous threads

**File:** `src/nanoleaf_sync/runtime/engine.py` (and any other file with unnamed threads)

**Change:** Find all `threading.Thread(target=...)` calls without a `name=` argument and add descriptive names like `"capture-worker"`, `"output-writer"`, etc.

Do a grep for `threading.Thread` across the entire `src/` tree to find all sites.

### 6. Q10 — Adaptive HID write timeout

**File:** `src/nanoleaf_sync/device/hid_transport.py`

**Change:** Compute the per-frame write timeout based on target FPS rather than hardcoded 500ms.

```python
# Near where timeout is used for write:
if target_fps and target_fps > 0:
    frame_budget_ms = max(1000 // target_fps, 8)
    write_timeout_ms = max(self.read_timeout_ms, frame_budget_ms * 3)
else:
    write_timeout_ms = self.read_timeout_ms
```

If `target_fps` is not available in this scope, pass it through from the config or use a reasonable default (60 FPS → ~50ms).

### 7. Q5 — Add config schema version

**File:** `src/nanoleaf_sync/config/normalize.py`

**Change:** Add a `SCHEMA_VERSION` constant and a migration check. There's a step-by-step approach:

1. Add `SCHEMA_VERSION = 1` to `normalize.py`
2. In `normalize_config()`, if `config.schema_version < SCHEMA_VERSION`, run migrations
3. Add `schema_version: int = 1` field to `AppConfig` in `model.py`
4. After normalization, set `config.schema_version = SCHEMA_VERSION`

```python
# In normalize.py
SCHEMA_VERSION = 1

def normalize_config(config: AppConfig) -> AppConfig:
    if config.schema_version >= SCHEMA_VERSION:
        return config

    # Run migrations sequentially
    version = config.schema_version
    while version < SCHEMA_VERSION:
        version += 1
        migrate_fn = _MIGRATIONS.get(version)
        if migrate_fn:
            config = migrate_fn(config)

    config.schema_version = SCHEMA_VERSION
    return config
```

This is a no-op for current configs (schema_version=1), but enables safe future migrations.

### 8. P2 — Add profiling instrumentation to Oklch path

**File:** `src/nanoleaf_sync/runtime/color_processing.py`

**Change:** Add timing instrumentation around the color processing hot path. This is diagnostic-only and zero-cost when not reading the metrics.

```python
# In apply_color_style_mapping or near the call site
import time

def apply_color_style_mapping(frame, ...):
    t0 = time.perf_counter()
    # ... existing logic ...
    t1 = time.perf_counter()
    if hasattr(frame, '_timing'):
        frame._timing['color_process_ms'] = (t1 - t0) * 1000
```

If `frame` is a numpy array and can't have attributes, use a module-level dict keyed by frame number instead.

## Verification

Run these commands after all changes:

```bash
# 1. Unit tests pass
python -m pytest -q --timeout=60 --timeout-method=thread --durations=25

# 2. Ruff lint passes (no new errors)
ruff check src/ tests/ --select E9,F63,F7,F82

# 3. Mypy with expanded scope
mypy src/nanoleaf_sync --ignore-missing-imports --follow-imports=silent

# 4. Import smoke test
python -c "from nanoleaf_sync.config.store import ConfigManager; print('import OK')"
python -c "from nanoleaf_sync.color.zone_mapper import resolve_device_zone_indices; print('import OK')"
python -c "from nanoleaf_sync.runtime.diagnostics_exports import _plot_diag_timeseries; print('import OK')"
```

## Freebuff Invocation Snippet

```
@read AGENTS.md
Apply the spec at .opencode/task-spec.md — fix all 8 changes (B1, DC1/DC2/DC4, B3, Q1, Q8, Q10, Q5, P2 instrumentation). Each change is bounded (1-5 lines) except mypy scope (1 line in pyproject.toml) and thread naming (grep + name args). Run verification commands after all changes and report results.
```
