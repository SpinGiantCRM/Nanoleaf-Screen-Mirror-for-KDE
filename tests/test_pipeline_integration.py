from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.runtime.engine import run_loop
from nanoleaf_sync.runtime.state import RuntimeState


class _SingleFrameCapture:
    name = "fake-capture"
    last_capture_path = "test"

    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    def capture(self) -> np.ndarray:
        return self._frame


class _CollectingDriver:
    def __init__(self, stop_event) -> None:
        self.sent_frames = []
        self._stop_event = stop_event

    def send_frame(self, colors):
        self.sent_frames.append(list(colors))
        self._stop_event.set()


def test_full_pipeline_zone_map_brightness_smoothing_and_send() -> None:
    frame = np.zeros((2, 4, 3), dtype=np.uint8)
    frame[:, :2] = [200, 0, 0]   # left zone
    frame[:, 2:] = [0, 100, 0]   # right zone

    cfg = AppConfig(
        fps=30,
        brightness=0.5,
        smoothing=0.25,
        zones=[
            ZoneConfig(x=0.0, y=0.0, w=0.5, h=1.0),
            ZoneConfig(x=0.5, y=0.0, w=0.5, h=1.0),
        ],
        device_zone_count=2,
        zone_offset=1,
        use_mock_capture=False,
        verbose=False,
    )

    state = RuntimeState()
    state.prev_smoothed_colors = [(0, 0, 0), (40, 40, 40)]

    capture = _SingleFrameCapture(frame)
    driver = _CollectingDriver(state.stop_event)

    run_loop(
        config=cfg,
        state=state,
        get_capture=lambda: capture,
        get_driver=lambda: driver,
        install_drivers=lambda: None,
        close_backends=lambda: None,
    )

    assert len(driver.sent_frames) == 1
    # Adaptive One-Euro-style smoothing should stay responsive on larger deltas
    # while still blending with previous output.
    assert driver.sent_frames[0] == [(0, 42, 0), (97, 11, 11)]
