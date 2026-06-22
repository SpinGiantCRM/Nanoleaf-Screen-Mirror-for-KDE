from __future__ import annotations

import logging

import numpy as np
import pytest

from nanoleaf_sync.capture.kmsgrab import KMSGrabCapture, _wayland_session_active
from nanoleaf_sync.capture.xdg_portal import XDGPortalCapture
from nanoleaf_sync.config.normalize import migrate_config_dict
from nanoleaf_sync.runtime.engine import run_loop
from nanoleaf_sync.runtime.fps_governor import FPSGovernor
from nanoleaf_sync.runtime.state import RuntimeState


def test_legacy_pipeline_flag_is_deprecated(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nanoleaf_sync.config.model import AppConfig

    monkeypatch.setattr(
        "nanoleaf_sync.runtime.engine._run_loop_pipeline",
        lambda **_kwargs: None,
    )
    state = RuntimeState()
    with caplog.at_level(logging.WARNING):
        run_loop(
            config=AppConfig(device_zone_count=4),
            state=state,
            get_capture=lambda: None,
            get_driver=lambda: None,
            install_drivers=lambda: None,
            close_backends=lambda: None,
            use_legacy_pipeline=True,
        )

    assert any("use_legacy_pipeline is deprecated" in rec.message for rec in caplog.records)


def test_migrate_consolidates_corner_anchors_into_calibration() -> None:
    migrated = migrate_config_dict(
        {
            "corner_anchor_top_left": 0,
            "corner_anchor_top_right": 12,
            "corner_anchor_bottom_right": 24,
            "corner_anchor_bottom_left": 36,
            "calibration": {"corner_anchor_top_left": -1},
        }
    )
    calibration = migrated["calibration"]
    assert calibration["corner_anchor_top_left"] == 0
    assert calibration["corner_anchor_top_right"] == 12
    assert "corner_anchor_top_left" not in migrated


def test_migrate_strips_use_legacy_pipeline() -> None:
    migrated = migrate_config_dict({"use_legacy_pipeline": True})
    assert "use_legacy_pipeline" not in migrated


def test_kmsgrab_skips_drm_zone_sampler_on_wayland(monkeypatch) -> None:
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert _wayland_session_active() is True
    backend = KMSGrabCapture(
        width=64,
        height=36,
        allow_fallback=True,
        drm_zone_patch_capture=True,
    )
    assert backend._drm_zone_sampler is None


def test_governor_prefers_end_to_end_latency_samples() -> None:
    governor = FPSGovernor(initial_fps=60, min_fps_floor=30)
    for _ in range(15):
        governor.record_frame(2.0)
    before = governor.get_metrics()["p95_latency_ms"]
    governor.record_frame(40.0)
    after = governor.get_metrics()["p95_latency_ms"]
    assert after >= before


def test_portal_recovers_after_empty_frame_streak(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = XDGPortalCapture(width=4, height=4)
    backend._initialized = True
    backend._STREAM_RECOVER_AFTER_EMPTY = 1
    reads = iter([None, np.zeros((4, 4, 3), dtype=np.uint8)])
    recoveries = {"count": 0}

    def _read() -> np.ndarray | None:
        return next(reads, None)

    def _recover(*, reason: str) -> None:
        recoveries["count"] += 1

    monkeypatch.setattr(backend, "_read_pipewire_frame", _read)
    monkeypatch.setattr(backend, "_recover_stream", _recover)

    frame = backend.capture()
    assert frame.shape == (4, 4, 3)
    assert recoveries["count"] == 1
