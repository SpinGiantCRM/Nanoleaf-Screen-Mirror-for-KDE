from __future__ import annotations

from unittest.mock import ANY, MagicMock

import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.presets import (
    SYNC_MODE_4D,
    effective_drm_zone_patch_capture,
    effective_edge_locality_for_sync,
    effective_motion_preset_for_sync,
    effective_sampling_quality_for_sync,
    effective_zone_sampling_stride_for_sync,
    is_four_d_sync,
    predictive_sync_enabled_for_sync,
)
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver
from nanoleaf_sync.runtime.color_pipeline import build_pipeline_params_from_config
from nanoleaf_sync.runtime.fps_governor import capture_interval_budget_ms


def test_capture_interval_budget_paces_to_target_when_hid_work_is_low() -> None:
    interval = capture_interval_budget_ms(target_fps=60, hid_output_work_ewma_ms=5.0)
    assert interval == pytest.approx(1000.0 / 60.0, rel=0.01)


def test_capture_interval_budget_paces_to_target_at_120fps_when_hid_work_is_low() -> None:
    interval = capture_interval_budget_ms(target_fps=120, hid_output_work_ewma_ms=5.0)
    assert interval == pytest.approx(1000.0 / 120.0, rel=0.01)


def test_capture_interval_budget_extends_when_hid_work_exceeds_budget() -> None:
    interval = capture_interval_budget_ms(target_fps=120, hid_output_work_ewma_ms=22.0)
    assert interval == pytest.approx(22.0 * 1.05, rel=0.01)


def test_capture_interval_budget_uses_target_when_slower_than_hid() -> None:
    interval = capture_interval_budget_ms(target_fps=30, hid_output_work_ewma_ms=22.0)
    assert interval is not None
    assert interval == pytest.approx(1000.0 / 30.0, rel=0.01)


def test_capture_interval_budget_none_until_hid_work_known() -> None:
    assert capture_interval_budget_ms(target_fps=120, hid_output_work_ewma_ms=None) is None


def test_capture_interval_at_60fps_when_hid_work_exceeds_budget() -> None:
    interval = capture_interval_budget_ms(target_fps=60, hid_output_work_ewma_ms=22.0)
    assert interval == pytest.approx(22.0 * 1.05, rel=0.01)


def test_four_d_sync_preset_overrides() -> None:
    assert is_four_d_sync(SYNC_MODE_4D)
    assert effective_edge_locality_for_sync(edge_locality="wide", sync_mode=SYNC_MODE_4D) == "tight"
    assert (
        effective_motion_preset_for_sync(motion_preset="calm", sync_mode=SYNC_MODE_4D)
        == "responsive"
    )
    assert (
        effective_sampling_quality_for_sync(
            sampling_quality="high", sync_mode=SYNC_MODE_4D, config_fps=120
        )
        == "low"
    )
    assert (
        effective_sampling_quality_for_sync(
            sampling_quality="high", sync_mode=SYNC_MODE_4D, config_fps=60
        )
        == "balanced"
    )
    assert (
        effective_zone_sampling_stride_for_sync(
            sampling_quality="high", sync_mode=SYNC_MODE_4D, config_fps=120
        )
        == 4
    )
    assert (
        effective_zone_sampling_stride_for_sync(
            sampling_quality="high", sync_mode=SYNC_MODE_4D, config_fps=60
        )
        == 2
    )
    assert predictive_sync_enabled_for_sync(
        sync_mode=SYNC_MODE_4D,
        accuracy_mode=False,
        color_style="ambient",
    )
    assert not predictive_sync_enabled_for_sync(
        sync_mode=SYNC_MODE_4D,
        accuracy_mode=False,
        color_style="natural",
    )
    assert not predictive_sync_enabled_for_sync(
        sync_mode=SYNC_MODE_4D,
        accuracy_mode=False,
        color_style="reference",
    )
    assert not predictive_sync_enabled_for_sync(
        sync_mode=SYNC_MODE_4D,
        accuracy_mode=True,
        color_style="ambient",
    )


def test_build_pipeline_params_includes_sync_fields() -> None:
    cfg = AppConfig(sync_mode=SYNC_MODE_4D, predictive_sync_strength=0.7, fps=120)
    params = build_pipeline_params_from_config(
        cfg,
        effective_target_fps=120.0,
        staleness_ms=18.0,
    )
    assert params.sync_mode == SYNC_MODE_4D
    assert params.predictive_sync_strength == 0.7
    assert params.effective_target_fps == 120.0
    assert params.config_fps == 120.0


def test_four_d_auto_enables_drm_zone_patch_capture() -> None:
    assert effective_drm_zone_patch_capture(
        drm_zone_patch_capture=False,
        sync_mode=SYNC_MODE_4D,
    )
    assert not effective_drm_zone_patch_capture(
        drm_zone_patch_capture=False,
        sync_mode="standard",
    )


def test_report_size_probe_selects_single_report_size_for_48_zones() -> None:
    transport = MagicMock()
    transport.report_size = 64
    driver = NanoleafUSBDriver(
        ids=MagicMock(vid=0x37FA, pid=0x8202),
        transport=transport,
        configured_zone_count=48,
        report_size=64,
    )
    driver.zone_count = 48
    driver._apply_live_report_size_probe()
    assert driver.report_size == 256
    assert transport.report_size == 256


def test_four_d_usb_driver_uses_ack_for_multi_report_frames() -> None:
    transport = MagicMock()
    transport.report_size = 64
    transport.write_with_timing.return_value = {
        "write_ms": 2.5,
        "flush_or_wait_ms": 0.0,
        "read_calls": 0,
        "report_count": 3,
    }
    transport.write_with_nonblocking_drain = MagicMock(
        return_value={
            "write_ms": 3.0,
            "flush_or_wait_ms": 1.5,
            "read_calls": 1,
            "report_count": 3,
        }
    )
    driver = NanoleafUSBDriver(
        ids=MagicMock(vid=0x37FA, pid=0x8202),
        transport=transport,
        configured_zone_count=48,
        enable_live_frame_write_optimization=True,
        prefer_write_only_live_send=True,
    )
    driver.zone_count = 48
    driver._initialized = True
    driver._cached_on_state = True
    driver._cached_brightness = 128
    driver.set_zone_colors([(10, 20, 30)] * 48)
    transport.write_with_nonblocking_drain.assert_called_once_with(
        ANY, target_fps=60, drain_budget_ms=2, max_drain_reads=2
    )
    transport.write_with_timing.assert_not_called()
    assert driver.last_send_timing.get("live_send_policy") == "nonblocking_drain"


def test_four_d_usb_driver_uses_drain_for_single_report_after_probe() -> None:
    transport = MagicMock()
    transport.report_size = 256
    transport.write_with_timing.return_value = {
        "write_ms": 1.0,
        "flush_or_wait_ms": 0.0,
        "read_calls": 0,
        "report_count": 1,
    }
    transport.write_with_nonblocking_drain = MagicMock(
        return_value={
            "write_ms": 2.0,
            "flush_or_wait_ms": 1.2,
            "read_calls": 1,
            "report_count": 1,
        }
    )
    driver = NanoleafUSBDriver(
        ids=MagicMock(vid=0x37FA, pid=0x8202),
        transport=transport,
        configured_zone_count=48,
        enable_live_frame_write_optimization=True,
        prefer_write_only_live_send=True,
        report_size=256,
    )
    driver.zone_count = 48
    driver._initialized = True
    driver._cached_on_state = True
    driver._cached_brightness = 128
    driver._probed_report_size = 256
    driver.set_zone_colors([(10, 20, 30)] * 48)
    transport.write_with_nonblocking_drain.assert_called_once_with(
        ANY, target_fps=60, drain_budget_ms=2, max_drain_reads=2
    )
    transport.write_with_timing.assert_not_called()
    assert driver.last_send_timing.get("live_send_policy") == "nonblocking_drain"
    assert driver.last_send_timing.get("probed_report_size") == 256


def test_standard_mode_single_report_uses_drain_when_live_optimization_enabled() -> None:
    transport = MagicMock()
    transport.report_size = 256
    transport.write_with_nonblocking_drain = MagicMock(
        return_value={
            "write_ms": 1.0,
            "flush_or_wait_ms": 0.5,
            "read_calls": 1,
            "report_count": 1,
        }
    )
    transport.write_with_timing = MagicMock()
    driver = NanoleafUSBDriver(
        ids=MagicMock(vid=0x37FA, pid=0x8202),
        transport=transport,
        configured_zone_count=8,
        enable_live_frame_write_optimization=True,
        prefer_write_only_live_send=False,
        report_size=256,
    )
    driver.zone_count = 8
    driver._initialized = True
    driver._cached_on_state = True
    driver._cached_brightness = 128
    driver.set_zone_colors([(10, 20, 30)] * 8)
    transport.write_with_nonblocking_drain.assert_called_once()
    transport.write_with_timing.assert_not_called()
    assert driver.last_send_timing.get("live_send_policy") == "nonblocking_drain"
