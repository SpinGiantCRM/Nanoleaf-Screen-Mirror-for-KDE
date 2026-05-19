from __future__ import annotations

import pytest

from nanoleaf_sync.device.hid_transport import HIDTransport
from nanoleaf_sync.device.interfaces import NanoleafUSBIds
from nanoleaf_sync.device.protocol import (
    CMD_GET_BRIGHTNESS,
    CMD_GET_LENGTH,
    CMD_GET_MODEL_NUMBER,
    CMD_GET_ON_OFF,
    CMD_SET_ZONE_COLORS,
    NanoleafTLVProtocol,
    ProtocolCommandError,
    ProtocolMalformedResponseError,
    ProtocolPayloadTooLargeError,
    ProtocolResponseTypeError,
    ProtocolShortReadError,
)


class _FakeHIDHandle:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.writes.append(bytes(data))
        return len(data)


def _response(req_type: int, payload: bytes) -> bytes:
    return bytes((req_type + 0x80,)) + len(payload).to_bytes(2, "big") + payload


def test_build_request_encodes_tlv() -> None:
    req = NanoleafTLVProtocol.build_request(CMD_SET_ZONE_COLORS, b"\x01\x02\x03")
    assert req == b"\x02\x00\x03\x01\x02\x03"


def test_build_request_rejects_payload_that_cannot_fit_two_byte_length() -> None:
    with pytest.raises(ProtocolPayloadTooLargeError, match="TLV payload too large"):
        NanoleafTLVProtocol.build_request(CMD_SET_ZONE_COLORS, b"\x00" * 65536)


def test_parse_response_returns_payload_without_status() -> None:
    parsed = NanoleafTLVProtocol.parse_response(
        CMD_GET_LENGTH, _response(CMD_GET_LENGTH, b"\x00\x0a")
    )
    assert parsed == b"\x0a"


def test_parse_length_short_read_header() -> None:
    with pytest.raises(ProtocolShortReadError):
        NanoleafTLVProtocol.parse_tlv(b"\x83\x00")


def test_parse_length_short_read_payload() -> None:
    with pytest.raises(ProtocolShortReadError):
        NanoleafTLVProtocol.parse_tlv(b"\x83\x00\x02\x00")


def test_parse_response_type_mismatch() -> None:
    with pytest.raises(ProtocolResponseTypeError):
        NanoleafTLVProtocol.parse_response(CMD_GET_ON_OFF, b"\x89\x00\x01\x00")


def test_parse_response_error_code() -> None:
    with pytest.raises(ProtocolCommandError):
        NanoleafTLVProtocol.parse_response(
            CMD_GET_BRIGHTNESS, _response(CMD_GET_BRIGHTNESS, b"\x01")
        )


def test_parse_response_missing_status_byte() -> None:
    with pytest.raises(ProtocolMalformedResponseError):
        NanoleafTLVProtocol.parse_response(CMD_GET_BRIGHTNESS, _response(CMD_GET_BRIGHTNESS, b""))


def test_command_specific_parsers() -> None:
    model_payload = NanoleafTLVProtocol.parse_response(
        CMD_GET_MODEL_NUMBER,
        _response(CMD_GET_MODEL_NUMBER, b"\x00NL82K2"),
    )
    assert NanoleafTLVProtocol.parse_model_number(model_payload) == "NL82K2"

    length_payload = NanoleafTLVProtocol.parse_response(
        CMD_GET_LENGTH, _response(CMD_GET_LENGTH, b"\x00\x1e")
    )
    assert NanoleafTLVProtocol.parse_u8(length_payload, field_name="length") == 30

    on_off_payload = NanoleafTLVProtocol.parse_response(
        CMD_GET_ON_OFF, _response(CMD_GET_ON_OFF, b"\x00\x01")
    )
    assert NanoleafTLVProtocol.parse_u8(on_off_payload, field_name="on/off state") == 1

    brightness_payload = NanoleafTLVProtocol.parse_response(
        CMD_GET_BRIGHTNESS,
        _response(CMD_GET_BRIGHTNESS, b"\x00\xff"),
    )
    assert NanoleafTLVProtocol.parse_u8(brightness_payload, field_name="brightness") == 255


def test_get_length_payload_must_be_single_byte_after_status() -> None:
    length_payload = NanoleafTLVProtocol.parse_response(
        CMD_GET_LENGTH,
        _response(CMD_GET_LENGTH, b"\x00\x00\x1e"),
    )
    with pytest.raises(ProtocolMalformedResponseError, match="Expected 1-byte length"):
        NanoleafTLVProtocol.parse_u8(length_payload, field_name="length")


def test_hid_write_single_report_boundary_success() -> None:
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    fake = _FakeHIDHandle()
    transport._handle = fake
    request = bytes([CMD_SET_ZONE_COLORS]) + b"\x00\x3d" + (b"\x01" * 61)

    transport.write(request)

    assert len(fake.writes) == 1
    assert len(fake.writes[0]) == 65
    assert fake.writes[0][1 : 1 + len(request)] == request


def test_hid_write_splits_request_across_multiple_reports_when_oversized() -> None:
    transport = HIDTransport(ids=NanoleafUSBIds(0x37FA, 0x8202), report_size=64)
    fake = _FakeHIDHandle()
    transport._handle = fake
    too_large_request = bytes([CMD_SET_ZONE_COLORS]) + b"\x00\x3e" + (b"\x01" * 62)

    transport.write(too_large_request)

    assert len(fake.writes) == 2
    first = fake.writes[0]
    second = fake.writes[1]
    assert len(first) == 65
    assert len(second) == 65
    assert first[1:] == too_large_request[:64]
    assert second[1] == too_large_request[64]
