from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

from nanoleaf_sync.capture.factory import (
    _cached_probe_winner_lock,
    _resolve_auto_backend_with_probe,
    _has_drm_device,
    reset_cached_probe_winner,
    reset_capability_check_cache,
)


def test_auto_probe_lock_is_not_held_while_probe_executes(monkeypatch) -> None:
    reset_cached_probe_winner()
    observed = {"lock_available": False}
    probe_started = threading.Event()
    release_probe = threading.Event()

    def _fake_probe_backends(_width, _height, _candidates, _config):
        probe_started.set()
        observed["lock_available"] = _cached_probe_winner_lock.acquire(timeout=0.1)
        if observed["lock_available"]:
            _cached_probe_winner_lock.release()
        release_probe.wait(timeout=1.0)
        return SimpleNamespace(
            selected_backend="kwin-dbus",
            candidates=[SimpleNamespace(candidate="kwin-dbus")],
        )

    monkeypatch.setattr(
        "nanoleaf_sync.capture.auto_probe.probe_backends",
        _fake_probe_backends,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            _resolve_auto_backend_with_probe,
            width=64,
            height=64,
            auto_probe_enabled=True,
            cached_probe_winner=None,
        )
        assert probe_started.wait(timeout=1.0)
        release_probe.set()
        second = pool.submit(
            _resolve_auto_backend_with_probe,
            width=64,
            height=64,
            auto_probe_enabled=True,
            cached_probe_winner=None,
        )

        assert first.result(timeout=1.0) == "kwin-dbus"
        assert second.result(timeout=1.0) == "kwin-dbus"

    assert observed["lock_available"] is True
    reset_cached_probe_winner()


def test_capability_cache_refresh_detects_hotplug_change(monkeypatch) -> None:
    reset_capability_check_cache()
    state = {"exists": False}
    monkeypatch.setattr("nanoleaf_sync.capture.factory.Path.exists", lambda _self: state["exists"])

    assert _has_drm_device() is False
    state["exists"] = True
    # Stale cache still returns previous value until refreshed.
    assert _has_drm_device() is False

    reset_capability_check_cache()
    assert _has_drm_device() is True
