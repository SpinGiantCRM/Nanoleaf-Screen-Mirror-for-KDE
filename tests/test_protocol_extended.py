"""Tests for device/protocol.py uncovered paths."""

from __future__ import annotations

import pytest

from nanoleaf_sync.device.protocol import (
    CMD_GET_LENGTH,
    MAX_TLV_PAYLOAD_LENGTH,
    NanoleafTLVProtocol,
    ProtocolCommandError,
    ProtocolMalformedResponseError,
    ProtocolPayloadTooLargeError,
    ProtocolResponseTypeError,
    ProtocolShortReadError,
    TLVMessage,
)


def test_tlv_encode_basic() -> None:
    msg = TLVMessage(msg_type=0x03, payload=b"\x00\x0a")
    encoded = msg.encode()
    assert encoded[0] == 0x03
    assert encoded[1:3] == b"\x00\x02"
    assert encoded[3:] == b"\x00\x0a"


def test_tlv_encode_payload_too_large() -> None:
    with pytest.raises(ProtocolPayloadTooLargeError):
        TLVMessage(msg_type=0x03, payload=b"\x00" * (MAX_TLV_PAYLOAD_LENGTH + 1)).encode()


def test_parse_tlv_too_short() -> None:
    with pytest.raises(ProtocolShortReadError):
        NanoleafTLVProtocol.parse_tlv(b"\x01")


def test_parse_tlv_shorter_than_declared() -> None:
    # Declares 10 bytes of payload but only has 5
    data = bytes([0x83, 0x00, 0x0A]) + b"\x00" * 5
    with pytest.raises(ProtocolShortReadError):
        NanoleafTLVProtocol.parse_tlv(data)


def test_parse_tlv_exact() -> None:
    data = bytes([0x83, 0x00, 0x02]) + b"\x00\x0a"
    msg = NanoleafTLVProtocol.parse_tlv(data)
    assert msg.msg_type == 0x83
    assert msg.payload == b"\x00\x0a"


def test_parse_tlv_with_padding() -> None:
    """TLV with trailing HID report padding bytes."""
    data = bytes([0x83, 0x00, 0x02]) + b"\x00\x0a" + b"\x00" * 10
    msg = NanoleafTLVProtocol.parse_tlv(data)
    assert msg.msg_type == 0x83
    assert msg.payload == b"\x00\x0a"


def test_parse_response_wrong_type() -> None:
    data = bytes([0x84, 0x00, 0x02]) + b"\x00\x0a"
    with pytest.raises(ProtocolResponseTypeError):
        NanoleafTLVProtocol.parse_response(0x03, data)


def test_parse_response_missing_status() -> None:
    data = bytes([0x83, 0x00, 0x00])
    with pytest.raises(ProtocolMalformedResponseError, match="status byte"):
        NanoleafTLVProtocol.parse_response(0x03, data)


def test_parse_response_error_status() -> None:
    data = bytes([0x83, 0x00, 0x01]) + b"\x01"
    with pytest.raises(ProtocolCommandError):
        NanoleafTLVProtocol.parse_response(0x03, data)


def test_parse_response_success() -> None:
    data = bytes([0x83, 0x00, 0x02]) + b"\x00\x0a"
    result = NanoleafTLVProtocol.parse_response(0x03, data)
    assert result == b"\x0a"


def test_parse_u8_wrong_length() -> None:
    with pytest.raises(ProtocolMalformedResponseError, match="Expected 1-byte"):
        NanoleafTLVProtocol.parse_u8(b"\x01\x02", field_name="test")


def test_parse_u16_be_wrong_length() -> None:
    with pytest.raises(ProtocolMalformedResponseError, match="Expected 2-byte"):
        NanoleafTLVProtocol.parse_u16_be(b"\x01", field_name="test")


def test_parse_model_number_empty() -> None:
    with pytest.raises(ProtocolMalformedResponseError, match="empty"):
        NanoleafTLVProtocol.parse_model_number(b"")


def test_parse_model_number_null_terminated() -> None:
    result = NanoleafTLVProtocol.parse_model_number(b"NL82K2\x00")
    assert result == "NL82K2"


def test_parse_model_number_strips_whitespace() -> None:
    result = NanoleafTLVProtocol.parse_model_number(b"  NL82K1  ")
    assert result == "NL82K1"


def test_parse_model_number_all_null() -> None:
    with pytest.raises(ProtocolMalformedResponseError):
        NanoleafTLVProtocol.parse_model_number(b"\x00\x00\x00")


def test_build_request() -> None:
    result = NanoleafTLVProtocol.build_request(CMD_GET_LENGTH)
    assert result == bytes([0x03, 0x00, 0x00])


def test_parse_u16_be_success() -> None:
    result = NanoleafTLVProtocol.parse_u16_be(b"\x01\x0a", field_name="test")
    assert result == 266
