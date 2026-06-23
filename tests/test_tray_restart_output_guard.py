from __future__ import annotations

import threading
import time

import numpy as np

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.engine import run_loop
from nanoleaf_sync.runtime.output_session import OutputSessionController
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.ui.tray_app import NanoleafTrayApp


def _cfg_with_valid_calibration(zone_count: int = 48, **kwargs) -> AppConfig:
    calibration = CalibrationConfig(
        device_zone_count=zone_count,
        corner_anchor_top_left=0,
        corner_anchor_top_right=zone_count // 4,
        corner_anchor_bottom_right=zone_count // 2,
        corner_anchor_bottom_left=(3 * zone_count) // 4,
    )
    return AppConfig(device_zone_count=zone_count, calibration=calibration, **kwargs)


class _FastCapture:
    name = "kwin-dbus"
    last_capture_path = "kwin-dbus:test"

    def capture(self):
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        frame[:, :] = [30, 40, 50]
        return frame


class _CountingDriver:
    reported_zone_count = 48
    zone_count = 48

    def send_frame_with_timing(self, _colors):
        return {"device_write_ms": 1.0}


def _run_guarded_loop(
    *,
    session: OutputSessionController,
    generation: int,
    runtime_state: RuntimeState,
) -> None:
    def _stop_soon() -> None:
        deadline = time.perf_counter() + 10.0
        while time.perf_counter() < deadline and runtime_state.frames_sent < 1:
            time.sleep(0.02)
        runtime_state.stop_event.set()

    threading.Thread(target=_stop_soon, daemon=True).start()
    run_loop(
        config=_cfg_with_valid_calibration(48, fps=60, min_max_send_age_ms=500.0),
        state=runtime_state,
        get_capture=lambda: _FastCapture(),
        get_driver=lambda: _CountingDriver(),
        install_drivers=lambda: True,
        close_backends=lambda: None,
        can_mirroring_write=lambda gen=generation: session.can_mirroring_write(gen),
    )


def test_stale_mirroring_generation_drops_output_until_rebound() -> None:
    session = OutputSessionController()
    generation = session.begin_mirroring_generation()

    active_state = RuntimeState()
    _run_guarded_loop(session=session, generation=generation, runtime_state=active_state)
    assert active_state.frames_sent >= 1
    assert active_state.first_frame_sent is True

    session.revoke_mirroring_generation(generation)

    stale_state = RuntimeState()
    _run_guarded_loop(session=session, generation=generation, runtime_state=stale_state)
    assert stale_state.output_owner_dropped_frames >= 1
    assert stale_state.first_frame_sent is False

    rebound_generation = session.begin_mirroring_generation()
    rebound_state = RuntimeState()
    _run_guarded_loop(
        session=session,
        generation=rebound_generation,
        runtime_state=rebound_state,
    )
    assert rebound_generation > generation
    assert rebound_state.first_frame_sent is True
    assert rebound_state.frames_sent >= 1


def test_tray_bind_output_session_guard_uses_fresh_generation() -> None:
    class _Service:
        mirroring_generation = 0

        def bind_mirroring_generation(self, generation: int) -> None:
            self.mirroring_generation = generation

        def set_output_session_guard(self, guard) -> None:
            self._output_session_guard = guard

    session = OutputSessionController()
    service = _Service()
    tray = type(
        "Tray",
        (),
        {
            "_output_session": session,
            "_bind_output_session_guard": NanoleafTrayApp._bind_output_session_guard,
        },
    )()

    NanoleafTrayApp._bind_output_session_guard(tray, service)  # type: ignore[arg-type]
    first_generation = int(service.mirroring_generation)
    assert service._output_session_guard() is True

    session.revoke_mirroring_generation(first_generation)
    assert service._output_session_guard() is False

    NanoleafTrayApp._bind_output_session_guard(tray, service)  # type: ignore[arg-type]
    assert int(service.mirroring_generation) > first_generation
    assert service._output_session_guard() is True
