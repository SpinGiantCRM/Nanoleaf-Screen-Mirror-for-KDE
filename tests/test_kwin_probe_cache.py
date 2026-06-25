from __future__ import annotations

import numpy as np

from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.service import NanoleafSyncService, _build_auto_probe_signature


class _FakeCapture(CaptureBackend):
    name = "kwin-dbus"
    last_capture_path = "kwin-dbus:test"

    def capture(self) -> np.ndarray:
        return np.zeros((9, 16, 3), dtype=np.uint8)

    def close(self) -> None:
        return None


class _FakeDriver:
    def __init__(self, zone_count: int = 4) -> None:
        self.zone_count = zone_count
        self.reported_zone_count = zone_count


def _valid_runtime_cfg(**kwargs) -> AppConfig:
    zone_count = int(kwargs.pop("device_zone_count", 48))
    return AppConfig(
        device_zone_count=zone_count,
        calibration=CalibrationConfig(
            device_zone_count=zone_count,
            corner_anchor_top_left=0,
            corner_anchor_top_right=zone_count // 4,
            corner_anchor_bottom_right=zone_count // 2,
            corner_anchor_bottom_left=(3 * zone_count) // 4,
        ),
        **kwargs,
    )


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
    service = NanoleafSyncService(config=cfg, driver_override=_FakeDriver(zone_count=4))
    service._capture = _FakeCapture()
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
    service = NanoleafSyncService(config=cfg, driver_override=_FakeDriver(zone_count=4))
    service._capture = _FakeCapture()
    service._runtime.consecutive_errors = 1
    service._runtime.last_error = (
        "org.kde.KWin.ScreenShot2.Error.InvalidScreen Invalid screen requested"
    )

    service._maybe_invalidate_kwin_probe_cache_for_invalid_screen()

    assert service._kwin_invalid_screen_invalidation_done is False
    assert service.config.auto_selected_backend == "kwin-dbus"
