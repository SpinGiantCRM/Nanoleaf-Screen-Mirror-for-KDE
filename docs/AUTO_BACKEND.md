# Auto Backend Selection

This project supports four capture backend settings in `config.toml`:

- `prefer_backend = "auto"`
- `prefer_backend = "kmsgrab"`
- `prefer_backend = "kwin-dbus"`
- `prefer_backend = "xdg-portal"`

`auto` uses **policy-aware probing** with persisted metadata. It is not only a static capability check.

## Backend tradeoffs

- `kmsgrab`: often fastest when DRM/KMS capture is available.
- `kwin-dbus`: compatibility KDE path via `org.kde.KWin.ScreenShot2`.
- `xdg-portal`: portable path when launch-context/compositor permission models favor portal access.

## How `auto` decides

When `prefer_backend = "auto"`, service startup evaluates:

1. `auto_probe_policy` to decide whether to run a fresh probe.
2. Cache metadata (`auto_selected_backend`) when policy allows reuse.
3. Fresh probe over candidates (`kmsgrab`, `kwin-dbus`, `xdg-portal`) if required.
4. Capability fallback if probe is disabled/fails/returns no qualified winner.

Capability fallback preference is:

- `kmsgrab` if DRM device + kmsgrab bindings are available
- otherwise `kwin-dbus`

## Probe policy reference

### `first-run`

Probe only when there is no valid cached winner.

```toml
prefer_backend = "auto"
auto_probe_enabled = true
auto_probe_policy = "first-run"
```

### `each-boot`

Probe once per process start, then reuse during that process lifetime.

```toml
prefer_backend = "auto"
auto_probe_enabled = true
auto_probe_policy = "each-boot"
```

### `on-change` (default)

Probe when environment signature changes (or cache is missing).

```toml
prefer_backend = "auto"
auto_probe_enabled = true
auto_probe_policy = "on-change"
```

## Probe metadata fields

`config.toml` fields managed by runtime:

- `auto_selected_backend`: last valid winner
- `auto_probe_signature`: hash of environment/capability/display context
- `auto_probe_timestamp`: UTC ISO timestamp of last persisted auto decision

## Probe enable/disable controls

Config-level control:

```toml
auto_probe_enabled = false
```

Environment-level controls:

- `NANOLEAF_DISABLE_CAPTURE_PROBE=true` forces probe off.
- `NANOLEAF_ENABLE_CAPTURE_PROBE=false` forces probe off.

With probe disabled, `auto` still works using capability fallback.

## Reset workflow

If cache metadata is stale, clear it and allow policy to repopulate:

```bash
python -c "from nanoleaf_sync.config.store import ConfigManager; ConfigManager().reset_auto_probe_cache()"
nanoleaf-kde-sync-smoke-test
```

## Forced override examples

To bypass auto policy during diagnostics, set explicit backend:

```toml
prefer_backend = "kwin-dbus"
# or "xdg-portal" / "kmsgrab"
```

This should produce `selection_reason=explicit` in smoke-test output.
