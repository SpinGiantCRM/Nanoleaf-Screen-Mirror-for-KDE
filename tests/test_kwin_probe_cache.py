from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.service import NanoleafSyncService, _build_auto_probe_signature
from tests.test_service_robustness import _valid_runtime_cfg
from tests.test_service_status_modes import FakeCapture, FakeDriver


def test_auto_probe_signature_changes_when_capture_monitor_changes() -> None:
    base = _build_auto_probe_signature(1920, 1080, capture_monitor="")
    with_monitor = _build_auto_probe_signature(1920, 1080, capture_monitor="DP-1")
    assert base != with_monitor


def test_repeated_invalid_screen_invalidates_cached_kwin_selection(monkeypatch) -> None:
    cfg = _valid_runtime_cfg(
        prefer_backend="auto",
        auto_selected_backend="kwin-dbus",
        auto_probe_signature="old-sig",
        capture_monitor="DP-stale",
        use_mock_capture=False,
    )
    service = NanoleafSyncService(config=cfg, driver_override=FakeDriver(zone_count=4))
    service._capture = FakeCapture(name="kwin-dbus")
    service._runtime.consecutive_errors = 3
    service._runtime.last_error = (
        "org.kde.KWin.ScreenShot2.Error.InvalidScreen Invalid screen requested"
    )

    saved: list[AppConfig] = []

    class _FakeConfigManager:
        def save(self, updated: AppConfig) -> None:
            saved.append(updated)

    monkeypatch.setattr("nanoleaf_sync.service.ConfigManager", _FakeConfigManager)

    service._maybe_invalidate_kwin_probe_cache_for_invalid_screen()

    assert service._kwin_invalid_screen_invalidation_done is True
    assert service.config.auto_selected_backend == ""
    assert service.config.auto_probe_signature == ""
    assert service._cached_probe_winner is None
    assert len(saved) == 1


def test_invalid_screen_invalidation_skips_when_errors_below_threshold() -> None:
    cfg = _valid_runtime_cfg(
        prefer_backend="auto",
        auto_selected_backend="kwin-dbus",
        use_mock_capture=False,
    )
    service = NanoleafSyncService(config=cfg, driver_override=FakeDriver(zone_count=4))
    service._capture = FakeCapture(name="kwin-dbus")
    service._runtime.consecutive_errors = 1
    service._runtime.last_error = (
        "org.kde.KWin.ScreenShot2.Error.InvalidScreen Invalid screen requested"
    )

    service._maybe_invalidate_kwin_probe_cache_for_invalid_screen()

    assert service._kwin_invalid_screen_invalidation_done is False
    assert service.config.auto_selected_backend == "kwin-dbus"
