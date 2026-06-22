from __future__ import annotations

from nanoleaf_sync.color.capture_metadata import (
    invalidate_plasma_hdr_cache,
    resolve_capture_metadata,
)
from nanoleaf_sync.color.zone_mapper import resolve_device_zone_indices
from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.runtime.zone_derivation import derive_source_zone_artifacts


def test_kwin_display_referred_skips_gamut_adaptation() -> None:
    meta = resolve_capture_metadata(kwin_display_referred=True)
    assert meta.skip_display_gamut_adaptation is True


def test_plasma_hdr_cache_invalidation_clears_cached_state() -> None:
    from nanoleaf_sync.color.capture_metadata import _plasma_hdr_enabled

    _plasma_hdr_enabled()
    invalidate_plasma_hdr_cache()
    assert _plasma_hdr_enabled.cache_info().currsize == 0


def test_reverse_zones_applied_with_fixed_mapping() -> None:
    mapping = [0, 10, 20, 30]
    forward = resolve_device_zone_indices(
        48,
        device_zone_count=4,
        reverse=False,
        fixed_mapping=mapping,
    )
    reversed_map = resolve_device_zone_indices(
        48,
        device_zone_count=4,
        reverse=True,
        fixed_mapping=mapping,
    )
    assert forward == mapping
    assert reversed_map == list(reversed(mapping))


def test_diagnostic_capture_falls_back_when_corner_anchors_missing() -> None:
    from nanoleaf_sync.service import NanoleafSyncService
    from tests.test_service_status_modes import FakeCapture, FakeDriver

    cfg = AppConfig(fps=30, use_mock_capture=False, device_zone_count=12, display_preset="hdr")
    capture = FakeCapture(name="kwin-dbus", width=640, height=360)
    svc = NanoleafSyncService(
        config=cfg, capture_backend_override=capture, driver_override=FakeDriver()
    )
    result = svc.capture_one_diagnostic_frame()
    assert result["ok"] is True, result.get("message")


def test_persisted_zones_keep_side_counts_on_ultrawide() -> None:
    cfg = AppConfig(
        zones=[ZoneConfig(x=0.0, y=0.0, w=0.1, h=0.1)] * 48,
        source_side_counts=[12, 8, 12, 16],
        device_zone_count=48,
    )
    artifacts = derive_source_zone_artifacts(
        config=cfg,
        frame_width=3440,
        frame_height=1440,
    )
    assert artifacts.side_counts == (12, 8, 12, 16)
