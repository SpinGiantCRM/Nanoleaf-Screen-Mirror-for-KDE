from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

from nanoleaf_sync.capture.factory import (
    _cached_probe_winner_lock,
    _resolve_auto_backend_with_probe,
    _has_drm_device,
    run_explicit_xdg_portal_probe,
    run_fresh_backend_probe,
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


def test_run_fresh_backend_probe_ignores_cached_winner(monkeypatch) -> None:
    def _fake_probe_backends(_width, _height, _candidates, _config):
        return SimpleNamespace(
            selected_backend="kmsgrab",
            timed_out=False,
            candidates=[
                SimpleNamespace(
                    candidate="kmsgrab",
                    status="tested",
                    reason="selected via score=1.0",
                    latencies_ms=[1.0, 1.2],
                    median_ms=1.1,
                    p95_ms=1.2,
                    jitter_ms=0.2,
                    score=1.0,
                    tentative=True,
                    errors=[],
                ),
                SimpleNamespace(
                    candidate="kwin-dbus",
                    status="tested",
                    reason="",
                    latencies_ms=[1.4, 1.5],
                    median_ms=1.45,
                    p95_ms=1.5,
                    jitter_ms=0.1,
                    score=2.0,
                    tentative=True,
                    errors=[],
                ),
            ],
        )

    monkeypatch.setattr("nanoleaf_sync.capture.auto_probe.probe_backends", _fake_probe_backends)
    result = run_fresh_backend_probe(width=64, height=64)
    assert result["selected_backend"] == "kmsgrab"
    assert any(row["mode"] == "fresh-probe" for row in result["attempts"])


def test_run_explicit_xdg_portal_probe_is_single_flight(monkeypatch) -> None:
    gate = threading.Event()
    release = threading.Event()

    class _FakePortal:
        def __init__(self, width: int, height: int) -> None:
            self.width = width
            self.height = height

        def run_explicit_diagnostic(self):
            gate.set()
            release.wait(timeout=1.0)
            return {"status": "tested", "mode": "explicit-test", "stages": []}

    monkeypatch.setattr("nanoleaf_sync.capture.factory.XDGPortalCapture", _FakePortal)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_explicit_xdg_portal_probe, width=64, height=64)
        assert gate.wait(timeout=1.0)
        second = pool.submit(run_explicit_xdg_portal_probe, width=64, height=64)
        second_result = second.result(timeout=1.0)
        release.set()
        first_result = first.result(timeout=1.0)

    assert second_result["status"] == "failed"
    assert "already in progress" in str(second_result["reason"])
    assert first_result["status"] == "tested"
