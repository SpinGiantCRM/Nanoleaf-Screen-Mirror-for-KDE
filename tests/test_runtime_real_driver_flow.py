from __future__ import annotations

import threading

import numpy as np

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig, ZoneConfig
from nanoleaf_sync.device.interfaces import NanoleafUSBIds
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver
from nanoleaf_sync.runtime.startup import run_runtime_engine
from nanoleaf_sync.runtime.state import RuntimeState


class _SingleFrameCapture:
    name = "kwin-dbus"
    last_capture_path = "kwin-dbus:CaptureScreen"

    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    def capture(self) -> np.ndarray:
        return self._frame


class _FakeTransport:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = list(responses)
        self.requests: list[bytes] = []
        self.opened = False
        self.open_calls = 0
        self.close_calls = 0

    def open(self) -> None:
        self.opened = True
        self.open_calls += 1

    def transceive(self, request: bytes) -> bytes:
        self.requests.append(request)
        if not self.responses:
            raise RuntimeError("No queued response")
        return self.responses.pop(0)

    def close(self) -> None:
        self.opened = False
        self.close_calls += 1


def _rsp(req_type: int, payload: bytes) -> bytes:
    return bytes((req_type + 0x80,)) + len(payload).to_bytes(2, "big") + payload


def test_run_loop_with_usb_driver_initializes_then_sends_frame() -> None:
    frame = np.zeros((2, 4, 3), dtype=np.uint8)
    frame[:, :2] = [120, 0, 0]
    frame[:, 2:] = [0, 90, 0]

    cfg = AppConfig(
        fps=30,
        brightness=1.0,
        smoothing=1.0,
        zones=[
            ZoneConfig(x=0.0, y=0.0, w=0.25, h=1.0),
            ZoneConfig(x=0.25, y=0.0, w=0.25, h=1.0),
            ZoneConfig(x=0.5, y=0.0, w=0.25, h=1.0),
            ZoneConfig(x=0.75, y=0.0, w=0.25, h=1.0),
        ],
        device_zone_count=4,
        calibration=CalibrationConfig(
            device_zone_count=4,
            corner_anchor_top_left=0,
            corner_anchor_top_right=1,
            corner_anchor_bottom_right=2,
            corner_anchor_bottom_left=3,
        ),
        use_mock_capture=False,
        verbose=False,
    )

    # startup: model + length; first frame preconditions: on/off + brightness + rgb
    transport = _FakeTransport(
        [
            _rsp(0x0C, b"\x00NL82K2"),
            _rsp(0x03, b"\x00\x04"),
            _rsp(0x06, b"\x00\x00"),
            _rsp(0x08, b"\x00\x00"),
            _rsp(0x07, b"\x00"),
            _rsp(0x09, b"\x00"),
            _rsp(0x02, b"\x00"),
            _rsp(0x02, b"\x00"),
        ]
    )
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        transport=transport,
        min_nonzero_brightness=16,
    )

    state = RuntimeState()
    capture = _SingleFrameCapture(frame)

    original_send_frame_with_timing = driver.send_frame_with_timing
    send_calls = 0

    def _send_frame_then_stop(zone_colors):
        nonlocal send_calls
        send_calls += 1
        # Stop even if a mocked transport response is exhausted to avoid retries/reinit loops.
        state.stop_event.set()
        return original_send_frame_with_timing(zone_colors)

    driver.send_frame_with_timing = _send_frame_then_stop

    watchdog = threading.Timer(1.0, state.stop_event.set)
    watchdog.start()
    try:
        run_runtime_engine(
            config=cfg,
            state=state,
            get_capture=lambda: capture,
            get_driver=lambda: driver,
            install_drivers=driver.initialize,
            close_backends=driver.close,
            clear_backends=lambda: None,
        )
    finally:
        watchdog.cancel()

    assert send_calls >= 1

    assert transport.open_calls == 1
    assert transport.close_calls == 1
    assert transport.opened is False
    request_codes = [req[0] for req in transport.requests]
    assert request_codes[:2] == [0x0C, 0x03]
    assert len(request_codes) >= 7, "expected at least one frame write"
    assert request_codes[:7] == [0x0C, 0x03, 0x06, 0x08, 0x07, 0x09, 0x02]
    assert transport.requests[5][3:] == b"\x10"
    # Driver default output channel order is GRB, so red/green channels are swapped on the wire.
    payload = transport.requests[6][3:]
    pixel0_grb = tuple(int(channel) for channel in payload[:3])
    pixel3_grb = tuple(int(channel) for channel in payload[9:12])

    expected_pixel0_grb = (0, 118, 1)
    expected_pixel3_grb = (91, 0, 0)

    assert all(
        abs(actual - expected) <= 2 for actual, expected in zip(pixel0_grb, expected_pixel0_grb)
    )
    assert all(
        abs(actual - expected) <= 2 for actual, expected in zip(pixel3_grb, expected_pixel3_grb)
    )
