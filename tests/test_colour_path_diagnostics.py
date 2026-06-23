from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.colour_path_diagnostics import (
    build_kwin_capture_diagnostics,
    build_portal_capture_diagnostics,
    build_zone_colour_path_row,
    write_colour_debug_snapshot,
    zone_colour_path_stage_fields,
)
from nanoleaf_sync.runtime.engine import FrameProcessingTimings
from nanoleaf_sync.service import NanoleafSyncService
from tests.test_service_status_modes import FakeCapture, FakeDriver


def test_kwin_capture_colour_diagnostics_populated() -> None:
    capture = FakeCapture(name="kwin-dbus")
    capture.last_capture_diagnostics = {
        "screenshot2_method": "CaptureActiveScreen",
        "requested_monitor_id": "DP-1",
        "invalid_screen_fallback_used": True,
        "legacy_fallback_used": False,
        "capture_path_kind": "screenshot2-active-screen-fallback",
    }
    kwin = build_kwin_capture_diagnostics(capture)
    assert kwin["screenshot2_method"] == "CaptureActiveScreen"
    assert kwin["invalid_screen_fallback_used"] is True
    cfg = AppConfig(fps=30, display_preset="hdr", compositor_hdr_mode=True)
    svc = NanoleafSyncService(
        config=cfg, capture_backend_override=capture, driver_override=FakeDriver()
    )
    status = svc.get_status()
    colour = status["capture_colour_diagnostics"]
    assert colour["kwin"]["screenshot2_method"] == "CaptureActiveScreen"
    assert colour["capture_source"]["backend"] == "kwin-dbus"
    assert colour["capture_source"]["display_referred"] is True


def test_portal_capture_colour_diagnostics_display_referred() -> None:
    capture = FakeCapture(name="xdg-portal")
    capture._last_frame_diag = {
        "format": "BGR",
        "stride": 7680,
        "width": 2560,
        "height": 1440,
        "caps": "video/x-raw,format=BGR,width=2560,height=1440",
        "rgb_conversion_attempted": True,
        "rgb_conversion_success": True,
    }
    capture._use_gstreamer = True
    capture._node_id = 42
    capture.portal_restore_token_state = "accepted"
    portal = build_portal_capture_diagnostics(capture)
    assert portal["pixel_format"] == "BGR"
    assert portal["rgb_bgr_conversion_path"] == "bgr_channel_swap"
    assert portal["implementation_path"] == "gstreamer"
    assert portal["pipewire_node_id"] == 42
    assert portal["restore_token_state"] == "accepted"
    cfg = AppConfig(fps=30, display_preset="hdr", compositor_hdr_mode=True)
    svc = NanoleafSyncService(
        config=cfg, capture_backend_override=capture, driver_override=FakeDriver()
    )
    status = svc.get_status()
    hdr = status["hdr_colour_path"]
    colour = status["capture_colour_diagnostics"]
    assert hdr["display_referred"] is True
    assert colour["capture_source"]["display_referred"] is True
    assert colour["portal"]["pixel_format"] == "BGR"
    assert colour["portal"]["negotiated_caps"] == "video/x-raw,format=BGR,width=2560,height=1440"


def test_export_colour_debug_snapshot_without_frame_does_not_crash(tmp_path: Path) -> None:
    cfg = AppConfig(fps=30, device_zone_count=12)
    svc = NanoleafSyncService(config=cfg, driver_override=FakeDriver())
    status = svc.get_status()
    result = write_colour_debug_snapshot(
        tmp_path / "colour-debug",
        config=cfg,
        status=status,
        frame=None,
        capture=None,
    )
    assert result["ok"] is True
    assert result["thumbnail_written"] is False
    assert (tmp_path / "colour-debug" / "zones.json").is_file()
    assert (tmp_path / "colour-debug" / "config_snapshot.json").is_file()
    zones_payload = json.loads((tmp_path / "colour-debug" / "zones.json").read_text())
    assert zones_payload == []


def test_zone_colour_path_stage_fields_and_row_include_candidate_and_final() -> None:
    timings = FrameProcessingTimings(
        colour_path_before_style=((10, 20, 30),),
        colour_path_after_style=((11, 21, 31),),
        colour_path_after_spread=((12, 22, 32),),
        colour_path_after_smoothing=((13, 23, 33),),
        colour_path_after_led_calibration=((14, 24, 34),),
        colour_path_final=((15, 25, 35),),
    )
    stages = zone_colour_path_stage_fields(
        mapped_led_index=0,
        proc_timings=timings,
        fallback_pre_led=(12, 22, 32),
        fallback_final=(15, 25, 35),
    )
    assert stages["output_rgb_before_style_mapping"] == (10, 20, 30)
    assert stages["output_rgb_after_smoothing"] == (13, 23, 33)
    assert stages["final_output_rgb"] == (15, 25, 35)
    row = build_zone_colour_path_row(
        zone_index=0,
        rect=(0, 0, 4, 4),
        side="top",
        sampled_rgb=(10, 20, 30),
        mapped_led_index=0,
        pre_led_rgb=(12, 22, 32),
        final_rgb=(15, 25, 35),
        proc_timings=timings,
        sampling_fields={
            "sampling_mode_effective": "palette_adaptive",
            "selected_algorithm": "dominant_saturated_hue",
            "confidence": 0.82,
        },
        color_style="ambient",
    )
    assert row["selected_candidate"] == "dominant_saturated_hue"
    assert row["final_output_rgb"] == (15, 25, 35)
    assert row["output_rgb_after_style_mapping"] == (11, 21, 31)


def test_one_shot_diagnostic_capture_includes_colour_path_stages() -> None:
    cfg = AppConfig(fps=30, use_mock_capture=False, device_zone_count=12, display_preset="hdr")
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    frame[0:40, 0:640] = (200, 40, 40)
    capture = FakeCapture(name="kwin-dbus", width=640, height=360)
    capture._frame = frame
    svc = NanoleafSyncService(
        config=cfg, capture_backend_override=capture, driver_override=FakeDriver()
    )
    result = svc.capture_one_diagnostic_frame()
    assert result["ok"] is True, result.get("message")
    rows = svc.get_status()["_latest_zone_diagnostics"]
    assert rows
    first = rows[0]
    assert "sampled_rgb" in first
    assert "final_output_rgb" in first
    assert "output_rgb_after_style_mapping" in first


def test_service_export_colour_debug_snapshot_method(tmp_path: Path) -> None:
    cfg = AppConfig(fps=30, device_zone_count=12)
    capture = FakeCapture(name="kwin-dbus", width=64, height=36)
    svc = NanoleafSyncService(
        config=cfg, capture_backend_override=capture, driver_override=FakeDriver()
    )
    svc.capture_one_diagnostic_frame()
    result = svc.export_colour_debug_snapshot(str(tmp_path / "export"))
    assert result["ok"] is True
    assert result["thumbnail_written"] is True
    assert (tmp_path / "export" / "capture_backend_status.json").is_file()
