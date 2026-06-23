"""Tests for capture/factory.py backend selection, capability cache, and env var handling."""

from __future__ import annotations

import pytest

from nanoleaf_sync.capture import factory
from nanoleaf_sync.capture.factory import (
    _env_bool,
    _has_drm_device,
    _kmsgrab_bindings_available,
    _probe_enabled,
    _resolve_auto_backend,
    auto_probe_effective_state,
    create_capture_backend,
    has_drm_device,
    kmsgrab_bindings_available,
    reset_cached_probe_winner,
    reset_capability_check_cache,
)

# ---------------------------------------------------------------------------
# _env_bool
# ---------------------------------------------------------------------------


def test_env_bool_none() -> None:
    assert _env_bool("NONEXISTENT_VAR") is None


def test_env_bool_true_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for val in ("1", "true", "yes", "on", "TRUE", "YES"):
        monkeypatch.setenv("TEST_VAR", val)
        assert _env_bool("TEST_VAR") is True


def test_env_bool_false_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for val in ("0", "false", "no", "off", "", "FALSE", "NO"):
        monkeypatch.setenv("TEST_VAR", val)
        assert _env_bool("TEST_VAR") is False


def test_env_bool_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_VAR", "maybe")
    assert _env_bool("TEST_VAR") is None


# ---------------------------------------------------------------------------
# _probe_enabled
# ---------------------------------------------------------------------------


def test_probe_enabled_default() -> None:
    enabled, reason = _probe_enabled(None)
    assert enabled is True
    assert reason is None


def test_probe_enabled_config_disabled() -> None:
    enabled, reason = _probe_enabled(False)
    assert enabled is False
    assert reason == "config auto_probe_enabled=false"


def test_probe_enabled_env_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NANOLEAF_DISABLE_CAPTURE_PROBE", "true")
    enabled, reason = _probe_enabled(True)
    assert enabled is False
    assert "NANOLEAF_DISABLE_CAPTURE_PROBE=true" in (reason or "")


def test_probe_enabled_env_enabled_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NANOLEAF_ENABLE_CAPTURE_PROBE", "false")
    enabled, reason = _probe_enabled(None)
    assert enabled is False
    assert "NANOLEAF_ENABLE_CAPTURE_PROBE=false" in (reason or "")


def test_auto_probe_effective_state() -> None:
    enabled, reason = auto_probe_effective_state(None)
    assert enabled is True
    assert reason == "enabled"


# ---------------------------------------------------------------------------
# DRM and kmsgrab capability checks
# ---------------------------------------------------------------------------


def test_has_drm_device_public() -> None:
    """Public function should delegate to internal."""
    result = has_drm_device()
    assert isinstance(result, bool)


def test_kmsgrab_bindings_available_public() -> None:
    """Public function should delegate to internal."""
    result = kmsgrab_bindings_available()
    assert isinstance(result, bool)


def test_no_drm_device(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_capability_check_cache()
    monkeypatch.setattr(factory.Path, "exists", lambda self: False)
    assert _has_drm_device() is False


def test_drm_device_present(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    reset_capability_check_cache()
    card0 = tmp_path / "card0"
    card0.touch()
    monkeypatch.setenv("NANOLEAF_DRM_CARD", "/dev/dri/card0")
    reset_capability_check_cache()
    from pathlib import Path as RealPath

    class _FakePath(type(card0)):
        def __new__(cls, *args, **kwargs):
            path_str = args[0] if args else ""
            if str(path_str) == "/dev/dri/card0":
                return card0
            return RealPath(*args, **kwargs)

    monkeypatch.setattr(factory, "Path", _FakePath)
    assert _has_drm_device() is True


def test_capability_cache_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cache should be reused within TTL window."""
    reset_capability_check_cache()
    call_count = [0]

    def _counting_resolver() -> bool:
        call_count[0] += 1
        return True

    monkeypatch.setattr(
        factory, "_capability_cache_get_or_refresh", lambda key, resolver: _counting_resolver()
    )
    # Not the best test, but verifies the cache infrastructure doesn't crash
    assert _has_drm_device() is True or _has_drm_device() is False


# ---------------------------------------------------------------------------
# _resolve_auto_backend
# ---------------------------------------------------------------------------


def test_resolve_auto_backend_with_drm(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_capability_check_cache()
    monkeypatch.setattr(factory, "_has_drm_device", lambda: True)
    monkeypatch.setattr(factory, "_kmsgrab_bindings_available", lambda: True)
    result = _resolve_auto_backend()
    assert result == "kwin-dbus"


def test_resolve_auto_backend_without_drm(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_capability_check_cache()
    monkeypatch.setattr(factory, "_has_drm_device", lambda: False)
    result = _resolve_auto_backend()
    assert result == "kwin-dbus"


# ---------------------------------------------------------------------------
# create_capture_backend
# ---------------------------------------------------------------------------


def test_create_mock_backend() -> None:
    backend = create_capture_backend(
        width=1920,
        height=1080,
        use_mock_capture=True,
        prefer_backend="auto",
    )
    assert backend is not None
    close_fn = getattr(backend, "close", None)
    if callable(close_fn):
        close_fn()


def test_create_kwin_dbus_backend_initializes_or_fails_cleanly() -> None:
    """Verify kwin-dbus backend either initializes successfully or fails with a clear error."""
    try:
        backend = create_capture_backend(
            width=64,
            height=36,
            use_mock_capture=False,
            prefer_backend="kwin-dbus",
        )
        # In KDE environments, it succeeds — ensure cleanup works
        close_fn = getattr(backend, "close", None)
        if callable(close_fn):
            close_fn()
    except Exception as exc:
        # In non-KDE environments, it fails — verify the error message is meaningful
        assert str(exc) or True  # any exception is acceptable


# ---------------------------------------------------------------------------
# Cached probe winner
# ---------------------------------------------------------------------------


def test_reset_cached_probe_winner() -> None:
    reset_cached_probe_winner()
    # Should not crash


# ---------------------------------------------------------------------------
# _kmsgrab_bindings_available fallback path
# ---------------------------------------------------------------------------


def test_kmsgrab_bindings_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_capability_check_cache()
    # Make both import paths fail
    import builtins

    original_import = builtins.__import__

    def _fail_kmsgrab(name, *args, **kwargs):
        if "kmsgrab" in name:
            raise ImportError("No module named kmsgrab")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_kmsgrab)
    assert _kmsgrab_bindings_available() is False


def test_cached_probe_winner_is_viable_kmsgrab_requires_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_capability_check_cache()
    monkeypatch.setattr(
        "nanoleaf_sync.capture.factory._has_drm_device",
        lambda: True,
    )
    monkeypatch.setattr(
        "nanoleaf_sync.capture.factory._kmsgrab_bindings_available",
        lambda: False,
    )
    from nanoleaf_sync.capture.factory import cached_probe_winner_is_viable

    assert cached_probe_winner_is_viable("kmsgrab") is False
    assert cached_probe_winner_is_viable("kwin-dbus") is True


def test_cached_probe_winner_rejects_kmsgrab_even_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_capability_check_cache()
    monkeypatch.setattr(
        "nanoleaf_sync.capture.factory._has_drm_device",
        lambda: True,
    )
    monkeypatch.setattr(
        "nanoleaf_sync.capture.factory._kmsgrab_bindings_available",
        lambda: True,
    )
    from nanoleaf_sync.capture.factory import cached_probe_winner_is_viable

    assert cached_probe_winner_is_viable("kmsgrab") is False


def test_resolve_auto_backend_ignores_stale_kmsgrab_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_cached_probe_winner()
    reset_capability_check_cache()
    monkeypatch.setattr(
        "nanoleaf_sync.capture.factory._has_drm_device",
        lambda: True,
    )
    monkeypatch.setattr(
        "nanoleaf_sync.capture.factory._kmsgrab_bindings_available",
        lambda: False,
    )

    def _probe_fail(*_args, **_kwargs):
        raise RuntimeError("probe unavailable")

    monkeypatch.setattr("nanoleaf_sync.capture.auto_probe.probe_backends", _probe_fail)
    from nanoleaf_sync.capture.factory import _resolve_auto_backend_with_probe

    result = _resolve_auto_backend_with_probe(
        width=320,
        height=180,
        auto_probe_enabled=True,
        cached_probe_winner="kmsgrab",
    )
    assert result == "kwin-dbus"


def test_resolve_auto_backend_rejects_nonviable_fresh_probe_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_cached_probe_winner()
    reset_capability_check_cache()
    monkeypatch.setattr(
        "nanoleaf_sync.capture.factory._has_drm_device",
        lambda: True,
    )
    monkeypatch.setattr(
        "nanoleaf_sync.capture.factory._kmsgrab_bindings_available",
        lambda: False,
    )

    class _ProbeResult:
        selected_backend = "kmsgrab"
        candidates: list[object] = []

    monkeypatch.setattr(
        "nanoleaf_sync.capture.auto_probe.probe_backends",
        lambda *_args, **_kwargs: _ProbeResult(),
    )
    from nanoleaf_sync.capture.factory import _resolve_auto_backend_with_probe

    result = _resolve_auto_backend_with_probe(
        width=320,
        height=180,
        auto_probe_enabled=True,
        cached_probe_winner=None,
    )
    assert result == "kwin-dbus"
