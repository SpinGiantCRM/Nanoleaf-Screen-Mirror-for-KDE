from __future__ import annotations

import pytest

from nanoleaf_sync.capture.kwin_dbus import KWinDBusScreenshotCapture
from nanoleaf_sync.runtime.engine import run_loop
from nanoleaf_sync.runtime.startup import reinitialize_backends, should_reinitialize
from nanoleaf_sync.runtime.state import RuntimeState


def test_reinit_after_capture_failure_is_allowed_after_backoff() -> None:
    state = RuntimeState()
    state.consecutive_errors = 5
    state.last_reinit_ts = 0.0
    assert should_reinitialize(
        state=state,
        error_limit=5,
        backoff_s=0.0,
        now_ts=1.0,
    )


def test_temporal_state_keeps_smooth_and_sent_histories_separate() -> None:
    state = RuntimeState()
    state.prev_smooth_float_colors = [(10.0, 10.0, 10.0)]
    state.prev_sent_colors = [(8, 8, 8)]
    sent = [tuple(int(v) for v in row) for row in state.prev_sent_colors]
    assert state.prev_smooth_float_colors != sent


def test_legacy_pipeline_deprecation_warning_only(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nanoleaf_sync.config.model import AppConfig

    monkeypatch.setattr("nanoleaf_sync.runtime.engine._run_loop_pipeline", lambda **_kwargs: None)
    with caplog.at_level("WARNING"):
        run_loop(
            config=AppConfig(device_zone_count=4),
            state=RuntimeState(),
            get_capture=lambda: None,
            get_driver=lambda: None,
            install_drivers=lambda: None,
            close_backends=lambda: None,
            use_legacy_pipeline=True,
        )
    assert any("use_legacy_pipeline is deprecated" in rec.message for rec in caplog.records)


def test_capture_dims_tracks_output_change() -> None:
    primary = KWinDBusScreenshotCapture(width=1920, height=1080, monitor_id="")
    secondary = KWinDBusScreenshotCapture(width=2560, height=1440, monitor_id="DP-2")
    assert primary.params.width == 1920
    assert secondary.params.width == 2560
    assert secondary.params.monitor_id == "DP-2"
    primary.close()
    secondary.close()


def test_reinitialize_backends_closes_backends() -> None:
    state = RuntimeState()
    closed = {"value": 0}

    reinitialize_backends(
        install_drivers=lambda: None,
        close_backends=lambda: closed.__setitem__("value", closed["value"] + 1),
        state=state,
    )
    assert closed["value"] == 1
    assert state.is_reinitializing is False
