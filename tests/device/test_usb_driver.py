from __future__ import annotations

import pytest

from nanoleaf_sync.device.interfaces import NanoleafUSBIds
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver


class FakeTransport:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = list(responses)
        self.requests: list[bytes] = []
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def transceive(self, request: bytes) -> bytes:
        self.requests.append(request)
        if not self.responses:
            raise RuntimeError("No fake response queued")
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class FailingOpenTransport(FakeTransport):
    def open(self) -> None:
        self.opened = True
        raise RuntimeError("permission denied")


def _rsp(req_type: int, payload: bytes) -> bytes:
    return bytes((req_type + 0x80,)) + len(payload).to_bytes(2, "big") + payload


def test_initialize_queries_model_and_length() -> None:
    transport = FakeTransport([
        _rsp(0x0C, b"\x00NL82K2"),
        _rsp(0x03, b"\x00\x0A"),
    ])
    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(0x37FA, 0x8202), transport=transport)

    driver.initialize()

    assert transport.opened
    assert driver.model_number == "NL82K2"
    assert driver.zone_count == 10
    assert [req[0] for req in transport.requests] == [0x0C, 0x03]


def test_initialize_rejects_unsupported_model() -> None:
    transport = FakeTransport([
        _rsp(0x0C, b"\x00UNKNOWN"),
    ])
    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(0x37FA, 0x8202), transport=transport)

    with pytest.raises(RuntimeError, match="Unsupported Nanoleaf model"):
        driver.initialize()
    assert transport.closed is True


def test_send_frame_auto_initializes_when_needed() -> None:
    transport = FakeTransport([
        _rsp(0x0C, b"\x00NL82K2"),
        _rsp(0x03, b"\x00\x02"),
        _rsp(0x06, b"\x00\x01"),
        _rsp(0x08, b"\x00\x10"),
        _rsp(0x02, b"\x00"),
    ])
    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(0x37FA, 0x8202), transport=transport)

    driver.send_frame([(1, 2, 3), (4, 5, 6)])

    assert [req[0] for req in transport.requests] == [0x0C, 0x03, 0x06, 0x08, 0x02]


def test_initialize_open_failure_is_raised_without_marking_initialized() -> None:
    transport = FailingOpenTransport([])
    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(0x37FA, 0x8202), transport=transport)

    with pytest.raises(RuntimeError, match="permission denied"):
        driver.initialize()

    assert driver.zone_count is None


def test_send_frame_exact_zone_count() -> None:
    transport = FakeTransport([
        _rsp(0x0C, b"\x00NL82K2"),
        _rsp(0x03, b"\x00\x02"),
        _rsp(0x06, b"\x00\x01"),
        _rsp(0x08, b"\x00\x64"),
        _rsp(0x02, b"\x00"),
    ])
    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(0x37FA, 0x8202), transport=transport)
    driver.initialize()

    driver.send_frame([(1, 2, 3), (4, 5, 6)])

    req = transport.requests[-1]
    assert req[0] == 0x02
    assert req[1:3] == b"\x00\x06"
    assert req[3:] == b"\x02\x01\x03\x05\x04\x06"


def test_send_frame_rejects_when_too_many_colors_for_effective_zone_count() -> None:
    transport = FakeTransport([
        _rsp(0x0C, b"\x00NL82K2"),
        _rsp(0x03, b"\x00\x02"),
        _rsp(0x06, b"\x00\x01"),
        _rsp(0x08, b"\x00\x14"),
        _rsp(0x02, b"\x00"),
    ])
    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(0x37FA, 0x8202), transport=transport)
    driver.initialize()

    with pytest.raises(RuntimeError, match="Refusing to silently truncate zone colors"):
        driver.send_frame([(1, 1, 1), (2, 2, 2), (3, 3, 3)])


def test_send_frame_pads_black_when_too_few_colors() -> None:
    transport = FakeTransport([
        _rsp(0x0C, b"\x00NL82K2"),
        _rsp(0x03, b"\x00\x03"),
        _rsp(0x06, b"\x00\x01"),
        _rsp(0x08, b"\x00\x14"),
        _rsp(0x02, b"\x00"),
    ])
    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(0x37FA, 0x8202), transport=transport)
    driver.initialize()

    driver.send_frame([(9, 8, 7)])

    req = transport.requests[-1]
    assert req[1:3] == b"\x00\x09"
    assert req[3:] == b"\x08\x09\x07\x00\x00\x00\x00\x00\x00"


def test_send_frame_uses_configured_channel_order() -> None:
    transport = FakeTransport([
        _rsp(0x0C, b"\x00NL82K2"),
        _rsp(0x03, b"\x00\x01"),
        _rsp(0x06, b"\x00\x01"),
        _rsp(0x08, b"\x00\x64"),
        _rsp(0x02, b"\x00"),
    ])
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        transport=transport,
        output_channel_order="rgb",
    )
    driver.initialize()

    driver.send_frame([(1, 2, 3)])

    req = transport.requests[-1]
    assert req[3:] == b"\x01\x02\x03"


def test_send_frame_turns_on_and_sets_min_brightness_once() -> None:
    transport = FakeTransport([
        _rsp(0x0C, b"\x00NL82K2"),
        _rsp(0x03, b"\x00\x02"),
        _rsp(0x06, b"\x00\x00"),
        _rsp(0x07, b"\x00"),
        _rsp(0x08, b"\x00\x00"),
        _rsp(0x09, b"\x00"),
        _rsp(0x02, b"\x00"),
        _rsp(0x02, b"\x00"),
    ])
    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(0x37FA, 0x8202), transport=transport, min_nonzero_brightness=12)
    driver.initialize()

    driver.send_frame([(1, 2, 3), (4, 5, 6)])
    driver.send_frame([(7, 8, 9), (10, 11, 12)])

    assert [req[0] for req in transport.requests] == [0x0C, 0x03, 0x06, 0x07, 0x08, 0x09, 0x02, 0x02]
    assert transport.requests[5][3:] == b"\x0c"


def test_send_frame_uses_configured_zone_count_override() -> None:
    transport = FakeTransport([
        _rsp(0x0C, b"\x00NL82K2"),
        _rsp(0x03, b"\x00\x08"),
        _rsp(0x06, b"\x00\x01"),
        _rsp(0x08, b"\x00\x64"),
        _rsp(0x02, b"\x00"),
    ])
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        transport=transport,
        report_size=256,
        configured_zone_count=48,
    )
    driver.initialize()

    driver.send_frame([(10, 20, 30)] * 48)

    assert driver.reported_zone_count == 8
    assert driver.zone_count == 48
    req = transport.requests[-1]
    assert req[0] == 0x02
    assert int.from_bytes(req[1:3], "big") == 48 * 3


def test_send_frame_rejects_zone_payload_larger_than_single_report() -> None:
    transport = FakeTransport([
        _rsp(0x0C, b"\x00NL82K2"),
        _rsp(0x03, b"\x00\x08"),
        _rsp(0x06, b"\x00\x01"),
        _rsp(0x08, b"\x00\x64"),
    ])
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        transport=transport,
        configured_zone_count=48,
    )
    driver.initialize()

    with pytest.raises(RuntimeError, match="Zone color request exceeds single-report TLV capacity"):
        driver.send_frame([(10, 20, 30)] * 48)


def test_send_frame_more_than_8_zones_still_builds_one_valid_tlv_when_within_capacity() -> None:
    transport = FakeTransport([
        _rsp(0x0C, b"\x00NL82K2"),
        _rsp(0x03, b"\x00\x08"),
        _rsp(0x06, b"\x00\x01"),
        _rsp(0x08, b"\x00\x64"),
        _rsp(0x02, b"\x00"),
    ])
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        transport=transport,
        report_size=64,
        configured_zone_count=9,
    )
    driver.initialize()

    driver.send_frame([(1, 2, 3)] * 9)

    req = transport.requests[-1]
    assert req[0] == 0x02
    assert req[1:3] == b"\x00\x1b"
    assert len(req) == 30


def test_set_brightness_clamps_to_protocol_range() -> None:
    transport = FakeTransport([
        _rsp(0x09, b"\x00"),
        _rsp(0x09, b"\x00"),
    ])
    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(0x37FA, 0x8202), transport=transport)

    driver.set_brightness(999)
    driver.set_brightness(-5)

    assert transport.requests[0][3:] == b"\xFF"
    assert transport.requests[1][3:] == b"\x00"


def test_min_nonzero_brightness_clamps_to_255() -> None:
    transport = FakeTransport([
        _rsp(0x0C, b"\x00NL82K2"),
        _rsp(0x03, b"\x00\x02"),
        _rsp(0x06, b"\x00\x01"),
        _rsp(0x08, b"\x00\x00"),
        _rsp(0x09, b"\x00"),
        _rsp(0x02, b"\x00"),
    ])
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        transport=transport,
        min_nonzero_brightness=500,
    )
    driver.initialize()

    driver.send_frame([(1, 2, 3), (4, 5, 6)])

    assert transport.requests[4][3:] == b"\xFF"


def test_close_clears_cached_state() -> None:
    transport = FakeTransport([])
    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(0x37FA, 0x8202), transport=transport)
    driver._initialized = True
    driver.model_number = "NL82K2"
    driver.zone_count = 12
    driver._cached_on_state = True
    driver._cached_brightness = 22

    driver.close()

    assert driver._initialized is False
    assert driver.model_number is None
    assert driver.zone_count is None
    assert driver._cached_on_state is None
    assert driver._cached_brightness is None
