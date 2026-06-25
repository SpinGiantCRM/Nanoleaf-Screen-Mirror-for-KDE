import asyncio
import sys
import types

import numpy as np
import pytest

from nanoleaf_sync.capture.xdg_portal import XDGPortalCapture, XDGPortalError


class _FakeBusNoUniqueName:
    unique_name = None

    async def disconnect(self) -> None:
        return None

    async def connect(self):
        return self


def test_negotiate_portal_disconnects_bus_on_failure(monkeypatch) -> None:
    disconnected: list[bool] = []

    class _FakeBus:
        unique_name = ":1.23"

        async def disconnect(self) -> None:
            disconnected.append(True)

    class _FailingBusFactory:
        def __init__(self, **_kwargs) -> None:
            pass

        async def connect(self):
            return _FakeBus()

    monkeypatch.setattr("dbus_next.aio.MessageBus", _FailingBusFactory)
    backend = XDGPortalCapture(width=4, height=4)

    with pytest.raises((XDGPortalError, AttributeError)):
        asyncio.run(backend._negotiate_portal())

    assert disconnected == [True]
    assert backend._portal_bus is None


def test_open_via_gstreamer_pins_colorimetry_bt709(monkeypatch) -> None:
    backend = XDGPortalCapture(width=1, height=1)
    parse_calls: list[str] = []

    class _FakePipeline:
        def get_by_name(self, _name: str):
            return object()

        def set_state(self, _state):
            return _FakeGst.StateChangeReturn.SUCCESS

    class _FakeGst:
        class State:
            PLAYING = object()
            NULL = object()

        class StateChangeReturn:
            FAILURE = object()
            SUCCESS = object()

        @staticmethod
        def init(_arg) -> None:
            return None

        @staticmethod
        def parse_launch(desc: str) -> _FakePipeline:
            parse_calls.append(desc)
            return _FakePipeline()

    monkeypatch.setitem(sys.modules, "gi", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "gi.repository", types.SimpleNamespace(Gst=_FakeGst))
    frame = np.zeros((1, 1, 3), dtype=np.uint8)
    diag = {"sample_received": True, "buffer_present": True, "buffer_reported_size": 3}
    monkeypatch.setattr(backend, "_pull_gst_frame", lambda _sink, timeout_s: (frame, diag))

    backend._open_via_gstreamer(fd=1, node_id=2)

    assert any("colorimetry=bt709" in call for call in parse_calls)


def test_negotiate_portal_fails_cleanly_without_unique_name(monkeypatch) -> None:
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda **_kwargs: _FakeBusNoUniqueName())

    backend = XDGPortalCapture(width=4, height=4)

    with pytest.raises(XDGPortalError, match="unique name is unavailable"):
        asyncio.run(backend._negotiate_portal())


def test_close_pipewire_stream_stops_gstreamer_pipeline(monkeypatch) -> None:
    backend = XDGPortalCapture(width=4, height=4)
    backend._use_gstreamer = True
    calls: list[str] = []

    class _FakePipeline:
        def set_state(self, _state) -> None:
            calls.append("null")

    backend._gst_pipeline = _FakePipeline()

    class _FakeGst:
        class State:
            NULL = object()

    import sys

    monkeypatch.setitem(sys.modules, "gi", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "gi.repository", types.SimpleNamespace(Gst=_FakeGst))

    backend._close_pipewire_stream()

    assert calls == ["null"]
    assert backend._gst_pipeline is None
    assert backend._gst_sink is None


def test_open_pipewire_stream_falls_back_when_binding_symbols_missing(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    backend = XDGPortalCapture(width=4, height=4)
    calls: list[tuple[int, int]] = []

    class _FakePipewire:
        MainLoop = object
        Context = object
        Stream = object
        Direction = object
        StreamFlags = object

    def _fake_open_via_gstreamer(fd: int, node_id: int) -> None:
        calls.append((fd, node_id))

    import sys

    monkeypatch.setitem(sys.modules, "pipewire", _FakePipewire())
    monkeypatch.setattr(backend, "_open_via_gstreamer", _fake_open_via_gstreamer)

    with caplog.at_level("INFO"):
        backend._open_pipewire_stream(fd=11, node_id=22)

    assert calls == [(11, 22)]
    assert "unsupported" in caplog.text
    assert "SpaPod" in caplog.text


def test_read_frame_gstreamer_returns_none_without_sink() -> None:
    backend = XDGPortalCapture(width=2, height=2)
    backend._use_gstreamer = True
    assert backend._read_frame_gstreamer() is None


def test_mapped_bytes_to_rgb_handles_bgrx_and_stride_padding() -> None:
    backend = XDGPortalCapture(width=2, height=1)
    # Two pixels in BGRx with 4 bytes of row padding
    payload = bytes(
        [
            10,
            20,
            30,
            0,
            40,
            50,
            60,
            0,
            0,
            0,
            0,
            0,
        ]
    )
    frame = backend._mapped_bytes_to_rgb(
        payload=payload,
        width=2,
        height=1,
        fmt="BGRx",
        stride=12,
    )
    assert frame is not None
    assert frame.shape == (1, 2, 3)
    # Converted RGB
    assert frame[0, 0].tolist() == [30, 20, 10]
    assert frame[0, 1].tolist() == [60, 50, 40]


@pytest.mark.parametrize("fmt", ["RGB", "BGR", "RGBx", "BGRx", "RGBA", "BGRA"])
def test_mapped_bytes_to_rgb_supports_multiple_formats(fmt: str) -> None:
    backend = XDGPortalCapture(width=1, height=1)
    payload = bytes([1, 2, 3]) if fmt in {"RGB", "BGR"} else bytes([1, 2, 3, 255])
    frame = backend._mapped_bytes_to_rgb(payload=payload, width=1, height=1, fmt=fmt, stride=None)
    assert isinstance(frame, np.ndarray)
    assert frame.shape == (1, 1, 3)


def test_explicit_diagnostic_reports_zero_byte_buffer_details(monkeypatch) -> None:
    backend = XDGPortalCapture(width=2, height=2)

    monkeypatch.setattr(backend, "initialize", lambda: None)
    monkeypatch.setattr(backend, "close", lambda: None)

    def _capture() -> np.ndarray:
        backend._last_frame_diag = {
            "sample_received": True,
            "buffer_present": True,
            "buffer_reported_size": 0,
            "memory_count": 1,
            "mapped_memory_size": 0,
            "caps": "video/x-raw,format=RGB,width=2,height=2",
            "width": 2,
            "height": 2,
            "format": "RGB",
            "framerate": "30/1",
            "stride": 6,
            "pts_ns": 100,
            "dts_ns": 90,
            "duration_ns": 33_000_000,
            "empty_buffer_count": 3,
            "non_empty_buffer_count": 0,
        }
        return np.zeros((0,), dtype=np.uint8)

    monkeypatch.setattr(backend, "capture", _capture)

    result = backend.run_explicit_diagnostic()
    assert result["status"] == "failed"
    details = result["details"]
    assert details["sample_received"] is True
    assert details["buffer_present"] is True
    assert details["buffer_reported_size"] == 0
    assert details["mapped_memory_size"] == 0
    assert details["empty_buffer_count"] == 3


def test_explicit_diagnostic_returns_staged_failure(monkeypatch) -> None:
    backend = XDGPortalCapture(width=2, height=2)

    def _boom() -> None:
        raise XDGPortalError("OpenPipeWireRemote failed: synthetic")

    monkeypatch.setattr(backend, "initialize", _boom)
    monkeypatch.setattr(backend, "close", lambda: None)

    result = backend.run_explicit_diagnostic()
    assert result["status"] == "failed"
    assert result["mode"] == "explicit-test"
    assert result["failing_stage"] == "PipeWire node/stream received"
    assert isinstance(result["stages"], list)


def test_extract_caps_metadata_reads_fraction_framerate_without_raising() -> None:
    backend = XDGPortalCapture(width=2, height=2)

    class _FakeStructure:
        def get_int(self, key: str) -> tuple[bool, int]:
            return True, 2 if key == "width" else 1

        def get_string(self, _key: str) -> str:
            return "RGB"

        def get_fraction(self, _key: str) -> tuple[bool, int, int]:
            return True, 60, 1

    class _FakeCaps:
        def to_string(self) -> str:
            return "video/x-raw,format=RGB,width=2,height=1,framerate=60/1"

        def get_size(self) -> int:
            return 1

        def get_structure(self, _index: int) -> _FakeStructure:
            return _FakeStructure()

    fake_video = types.SimpleNamespace(
        VideoInfo=types.SimpleNamespace(
            new_from_caps=lambda _caps: types.SimpleNamespace(stride=[6])
        )
    )

    metadata = backend._extract_caps_metadata(_FakeCaps(), gst_video=fake_video)

    assert metadata["caps"] == "video/x-raw,format=RGB,width=2,height=1,framerate=60/1"
    assert metadata["framerate"] == "60/1"
    assert metadata["caps_metadata_warning"] is None


def test_pull_gst_frame_continues_when_fraction_parse_raises(monkeypatch) -> None:
    backend = XDGPortalCapture(width=1, height=1)
    backend._GSTREAMER_FIRST_FRAME_POLL_INTERVAL_S = 0.001

    class _FakeStructure:
        def get_int(self, key: str) -> tuple[bool, int]:
            if key == "width":
                return True, 1
            if key == "height":
                return True, 1
            return False, 0

        def get_string(self, _key: str) -> str:
            return "RGB"

        def get_fraction(self, _key: str) -> tuple[bool, int, int]:
            raise TypeError("unknown type GstFraction")

    class _FakeCaps:
        def to_string(self) -> str:
            return "video/x-raw,format=RGB,width=1,height=1,framerate=60/1"

        def get_size(self) -> int:
            return 1

        def get_structure(self, _index: int) -> _FakeStructure:
            return _FakeStructure()

    class _FakeMapInfo:
        def __init__(self) -> None:
            self.data = bytes([1, 2, 3])
            self.size = 3

    class _FakeBuffer:
        pts = 0
        dts = 0
        duration = 0

        def get_size(self) -> int:
            return 3

        def n_memory(self) -> int:
            return 1

        def map(self, _flags):
            return True, _FakeMapInfo()

        def unmap(self, _map_info) -> None:
            return None

    class _FakeSample:
        def get_caps(self) -> _FakeCaps:
            return _FakeCaps()

        def get_buffer(self) -> _FakeBuffer:
            return _FakeBuffer()

    class _FakeSink:
        def try_pull_sample(self, _timeout_ns: int) -> _FakeSample:
            return _FakeSample()

    fake_gst = types.SimpleNamespace(MapFlags=types.SimpleNamespace(READ=object()))
    fake_gst_video = types.SimpleNamespace(
        VideoInfo=types.SimpleNamespace(
            new_from_caps=lambda _caps: types.SimpleNamespace(stride=[3])
        )
    )
    monkeypatch.setitem(sys.modules, "gi", types.SimpleNamespace())
    monkeypatch.setitem(
        sys.modules, "gi.repository", types.SimpleNamespace(Gst=fake_gst, GstVideo=fake_gst_video)
    )

    mapped_calls: list[dict[str, object]] = []
    original_map = backend._mapped_bytes_to_rgb

    def _recorded_map(**kwargs):
        mapped_calls.append(kwargs)
        return original_map(**kwargs)

    monkeypatch.setattr(backend, "_mapped_bytes_to_rgb", _recorded_map)

    frame, diag = backend._pull_gst_frame(_FakeSink(), timeout_s=0.05)
    failure_summary = backend._describe_gst_pull_failure(diag)

    assert isinstance(frame, np.ndarray)
    assert mapped_calls, (
        "_mapped_bytes_to_rgb should be attempted even when framerate parsing fails"
    )
    assert diag["framerate"] == "unknown"
    assert diag["caps_metadata_warning"] == "unknown type GstFraction"
    assert diag["rgb_conversion_success"] is True
    assert "metadata parse warning=unknown type GstFraction" in failure_summary


def test_open_via_gstreamer_succeeds_even_with_caps_metadata_warning(monkeypatch) -> None:
    backend = XDGPortalCapture(width=1, height=1)

    class _FakePipeline:
        def __init__(self) -> None:
            self.sink = object()

        def get_by_name(self, _name: str):
            return self.sink

        def set_state(self, _state):
            return _FakeGst.StateChangeReturn.SUCCESS

    class _FakeGst:
        class State:
            PLAYING = object()
            NULL = object()

        class StateChangeReturn:
            FAILURE = object()
            SUCCESS = object()

        @staticmethod
        def init(_arg) -> None:
            return None

        @staticmethod
        def parse_launch(_desc: str) -> _FakePipeline:
            return _FakePipeline()

    monkeypatch.setitem(sys.modules, "gi", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "gi.repository", types.SimpleNamespace(Gst=_FakeGst))

    frame = np.zeros((1, 1, 3), dtype=np.uint8)
    diag = {
        "sample_received": True,
        "buffer_present": True,
        "buffer_reported_size": 3,
        "mapped_memory_size": 3,
        "format": "RGB",
        "framerate": "unknown",
        "caps_metadata_warning": "unknown type GstFraction",
        "rgb_conversion_attempted": True,
        "rgb_conversion_success": True,
    }
    monkeypatch.setattr(backend, "_pull_gst_frame", lambda _sink, timeout_s: (frame, diag))

    backend._open_via_gstreamer(fd=7, node_id=77)

    assert backend._use_gstreamer is True
    assert backend._gst_sink is not None


def test_open_via_gstreamer_recovers_from_parse_launch_error_with_pipeline_none_guard(
    monkeypatch,
) -> None:
    backend = XDGPortalCapture(width=1, height=1)
    parse_calls: list[str] = []

    class _FakeSink:
        pass

    class _FakePipeline:
        def __init__(self) -> None:
            self.sink = _FakeSink()

        def get_by_name(self, _name: str):
            return self.sink

        def set_state(self, _state) -> None:
            pass

    class _FakeGst:
        class State:
            PLAYING = object()
            NULL = object()

        class StateChangeReturn:
            FAILURE = object()
            SUCCESS = object()

        @staticmethod
        def init(_arg) -> None:
            return None

        @staticmethod
        def parse_launch(desc: str):
            parse_calls.append(desc)
            if len(parse_calls) == 1:
                raise RuntimeError('no element "pipewiresrc"')
            return _FakePipeline()

    monkeypatch.setitem(sys.modules, "gi", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "gi.repository", types.SimpleNamespace(Gst=_FakeGst))

    frame = np.zeros((1, 1, 3), dtype=np.uint8)
    diag = {
        "sample_received": True,
        "buffer_present": True,
        "buffer_reported_size": 3,
        "mapped_memory_size": 3,
        "format": "RGB",
        "framerate": "30/1",
    }
    monkeypatch.setattr(backend, "_pull_gst_frame", lambda _sink, timeout_s: (frame, diag))

    backend._open_via_gstreamer(fd=7, node_id=77)

    assert len(parse_calls) == 2
    assert backend._use_gstreamer is True
    assert backend._gst_sink is not None
