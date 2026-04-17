from __future__ import annotations

import pytest

from nanoleaf_sync.device.protocol import (
    CMD_GET_BRIGHTNESS,
    CMD_GET_LENGTH,
    CMD_GET_MODEL_NUMBER,
    CMD_GET_ON_OFF,
    CMD_SET_ZONE_COLORS,
    NanoleafTLVProtocol,
    ProtocolCommandError,
    ProtocolMalformedResponseError,
    ProtocolResponseTypeError,
    ProtocolShortReadError,
)


def _response(req_type: int, payload: bytes) -> bytes:
    return bytes((req_type + 0x80,)) + len(payload).to_bytes(2, "big") + payload


def test_build_request_encodes_tlv() -> None:
    req = NanoleafTLVProtocol.build_request(CMD_SET_ZONE_COLORS, b"\x01\x02\x03")
    assert req == b"\x02\x00\x03\x01\x02\x03"


def test_parse_response_returns_payload_without_status() -> None:
    parsed = NanoleafTLVProtocol.parse_response(CMD_GET_LENGTH, _response(CMD_GET_LENGTH, b"\x00\x00\x0A"))
    assert parsed == b"\x00\x0A"


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
        NanoleafTLVProtocol.parse_response(CMD_GET_BRIGHTNESS, _response(CMD_GET_BRIGHTNESS, b"\x01"))


def test_parse_response_missing_status_byte() -> None:
    with pytest.raises(ProtocolMalformedResponseError):
        NanoleafTLVProtocol.parse_response(CMD_GET_BRIGHTNESS, _response(CMD_GET_BRIGHTNESS, b""))


def test_command_specific_parsers() -> None:
    model_payload = NanoleafTLVProtocol.parse_response(
        CMD_GET_MODEL_NUMBER,
        _response(CMD_GET_MODEL_NUMBER, b"\x00NL82K2"),
    )
    assert NanoleafTLVProtocol.parse_model_number(model_payload) == "NL82K2"

    length_payload = NanoleafTLVProtocol.parse_response(CMD_GET_LENGTH, _response(CMD_GET_LENGTH, b"\x00\x00\x1E"))
    assert NanoleafTLVProtocol.parse_u16_be(length_payload, field_name="length") == 30

    on_off_payload = NanoleafTLVProtocol.parse_response(CMD_GET_ON_OFF, _response(CMD_GET_ON_OFF, b"\x00\x01"))
    assert NanoleafTLVProtocol.parse_u8(on_off_payload, field_name="on/off state") == 1

    brightness_payload = NanoleafTLVProtocol.parse_response(
        CMD_GET_BRIGHTNESS,
        _response(CMD_GET_BRIGHTNESS, b"\x00\x64"),
    )
    assert NanoleafTLVProtocol.parse_u8(brightness_payload, field_name="brightness") == 100
