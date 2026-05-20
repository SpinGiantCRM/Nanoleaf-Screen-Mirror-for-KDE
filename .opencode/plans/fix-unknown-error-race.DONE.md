# Plan: Fix "Start failed: unknown error" race (DONE — fixed in v1.3.4)

## Background

The v1.3.4 fix (`d5eebe3`) addressed the slow-startup race in `_handle_auto_start_result` by changing line 658 from `if effective_running:` to `if startup_state in {"starting", "running"}:`. This prevents the "unknown error" path when the 1s timeout in `RuntimeLifecycle.start()` expires before the engine thread calls `mark_startup(True)`.

**Two remaining bugs:**

## Bug 1: Same race in `on_start()` — `src/nanoleaf_sync/ui/tray_app.py:554-577`

### Root cause

After `service.start()` returns (line 539), the thread may still be initializing. When `startup_state == "starting"`:

```
line 556: running = bool(running and startup_state == "running")
         → running = False  (startup_state is "starting")
line 567: if not running:  → True
line 571: error_text = self.service.last_error or "unknown error"
         → "unknown error" (last_error was cleared by reset_for_start)
```

This is the exact same pattern that was fixed in `_handle_auto_start_result` at line 658.

### Fix

Add a guard after line 558 matching the `_handle_auto_start_result` pattern:

```python
        running = bool(running and startup_state == "running")
        self.tray_icon.setIcon(self._running_icon if running else self._idle_icon)
        NanoleafTrayApp._safe_refresh_mode_labels(self)
+       if startup_state in {"starting", "running"}:
+           return
        if startup_state == "waiting_for_screen_selection":
```

### Why this works

- `"starting"` → thread is alive and startup is in progress, just not complete yet. Return silently.
- `"running"` → should never be hit here (first guard at line 532 catches it), but consistent with the auto-start guard.

## Bug 2: Unprotected bootstrap in `run_runtime_engine()` — `src/nanoleaf_sync/runtime/startup.py:148-158`

### Root cause

Lines 148-158 run BEFORE the `try/except` block:

```python
def run_runtime_engine(...):
    from nanoleaf_sync.runtime.engine import run_loop      # line 148 — outside try
    state.reset_for_start()                                   # line 150 — outside try
    apply_process_priority(config=config, state=state)        # line 151 — outside try
    if not initialize_or_fail(...):                           # line 152 — outside try
        clear_backends()
        return
    try:                                                      # line 160 — try starts here
        run_loop(...)
    except Exception as e:
        ...
```

If any of lines 148-158 raise an unhandled exception (import error, unexpected failure in `reset_for_start`, crash in `apply_process_priority`), the thread dies silently:
- `mark_startup()` is never called
- `last_error` stays None (cleared by `reset_startup()` then `reset_for_start()`)
- `startup_complete` is never set
- `start()` times out → returns True (startup_complete never set)
- The `on_start()` path falls through to "unknown error"

### Fix

Wrap the entire body from the import through `shutdown_backends` in the try/finally:

```python
def run_runtime_engine(...):
    try:
        from nanoleaf_sync.runtime.engine import run_loop
        state.reset_for_start()
        apply_process_priority(config=config, state=state)
        if not initialize_or_fail(...):
            clear_backends()
            return
        run_loop(...)
    except Exception as e:
        translated = translate_runtime_error(e)
        state.last_error = translated.summary
        state.last_error_kind = translated.kind
        state.last_error_guidance = translated.guidance
        state.start_failure_reason = translated.summary
        state.lifecycle_state = "failed"
        state.mark_startup(False)
        state.stop_event.set()
        logger.exception("runtime engine crashed")
    finally:
        shutdown_backends(...)
```

The import moves inside `try` so an import error (e.g., circular import, missing module) also produces a proper error message instead of silent thread death.

## Verification

```bash
python -m pytest -q --timeout=60 --timeout-method=thread
```

## Freebuff invocation snippet

```
freebuff nano
.task /home/chasem/Projects/Nanoleaf-Screen-Mirror-for-KDE/.opencode/plans/fix-unknown-error-race.md
```
