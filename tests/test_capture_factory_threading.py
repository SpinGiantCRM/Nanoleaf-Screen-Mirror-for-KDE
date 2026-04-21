from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from types import SimpleNamespace

from nanoleaf_sync.capture.factory import (
    _resolve_auto_backend_with_probe,
    reset_cached_probe_winner,
)


def test_auto_probe_cache_is_deterministic_under_concurrency(monkeypatch) -> None:
    reset_cached_probe_winner()
    probe_calls = 0
    probe_calls_lock = threading.Lock()

    def _fake_probe_backends(_width, _height, _candidates, _config):
        nonlocal probe_calls
        with probe_calls_lock:
            probe_calls += 1
        time.sleep(0.05)
        return SimpleNamespace(
            selected_backend="kwin-dbus",
            candidates=[SimpleNamespace(candidate="kwin-dbus")],
        )

    monkeypatch.setattr(
        "nanoleaf_sync.capture.auto_probe.probe_backends",
        _fake_probe_backends,
    )

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(
                    lambda _: _resolve_auto_backend_with_probe(
                        width=64,
                        height=64,
                        auto_probe_enabled=True,
                        cached_probe_winner=None,
                    ),
                    range(24),
                )
            )

        assert results == ["kwin-dbus"] * 24
        assert probe_calls == 1
    finally:
        reset_cached_probe_winner()
