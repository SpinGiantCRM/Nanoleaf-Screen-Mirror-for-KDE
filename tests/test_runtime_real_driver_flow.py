from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.device.interfaces import NanoleafUSBIds
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver
from nanoleaf_sync.runtime.startup import run_runtime_engine
from nanoleaf_sync.runtime.state import RuntimeState


class _SingleFrameCapture:
    name = "kwin-dbus"
    last_capture_path = "kwin-dbus:CaptureScreen"

    def __init__(self, frame: np.ndarray, stop_event) -> None:
        self._frame = frame
        self._stop_event = stop_event
        self._served = False

    def capture(self) -> np.ndarray:
        if self._served:
            # Stop cleanly after one frame to keep test deterministic.
            self._stop_event.set()
        self._served = True
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
            ZoneConfig(x=0.0, y=0.0, w=0.5, h=1.0),
            ZoneConfig(x=0.5, y=0.0, w=0.5, h=1.0),
        ],
        device_zone_count=2,
        use_mock_capture=False,
        verbose=False,
    )

    # startup: model + length; first frame preconditions: on/off + brightness + rgb
    transport = _FakeTransport([
        _rsp(0x0C, b"\x00NL82K2"),
        _rsp(0x03, b"\x00\x02"),
        _rsp(0x06, b"\x00\x00"),
        _rsp(0x07, b"\x00"),
        _rsp(0x08, b"\x00\x00"),
        _rsp(0x09, b"\x00"),
        _rsp(0x02, b"\x00"),
        _rsp(0x02, b"\x00"),
    ])
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        transport=transport,
        min_nonzero_brightness=16,
    )

    state = RuntimeState()
    capture = _SingleFrameCapture(frame, state.stop_event)

    run_runtime_engine(
        config=cfg,
        state=state,
        get_capture=lambda: capture,
        get_driver=lambda: driver,
        install_drivers=driver.initialize,
        close_backends=driver.close,
        clear_backends=lambda: None,
    )

    assert transport.open_calls == 1
    assert transport.close_calls == 1
    assert transport.opened is False
    request_codes = [req[0] for req in transport.requests]
    assert request_codes[:2] == [0x0C, 0x03]
    assert len(request_codes) >= 7, "expected at least one frame write"
    assert request_codes[:7] == [0x0C, 0x03, 0x06, 0x07, 0x08, 0x09, 0x02]
    assert transport.requests[5][3:] == b"\x10"
    # Driver default output channel order is GRB, so red/green channels are swapped on the wire.
    assert transport.requests[6][3:] == b"\x00\x78\x00\x5a\x00\x00"