from __future__ import annotations

from dataclasses import dataclass


CMD_SET_ZONE_COLORS = 0x02
CMD_GET_LENGTH = 0x03
CMD_GET_ON_OFF = 0x06
CMD_SET_ON_OFF = 0x07
CMD_GET_BRIGHTNESS = 0x08
CMD_SET_BRIGHTNESS = 0x09
CMD_GET_FIRMWARE = 0x0A
CMD_GET_MODEL_NUMBER = 0x0C

SUCCESS_CODE = 0
FAILURE_CODE = 1

SUPPORTED_MODEL_NUMBERS = {"NL82K1", "NL82K2"}


class ProtocolError(RuntimeError):
    """Base error for malformed or invalid protocol data."""


class ProtocolShortReadError(ProtocolError):
    """Raised when a response does not contain enough bytes for a full TLV."""


class ProtocolMalformedResponseError(ProtocolError):
    """Raised when TLV format is inconsistent with length or command expectations."""


class ProtocolResponseTypeError(ProtocolError):
    """Raised when the response type does not match request type + 0x80."""


class ProtocolCommandError(ProtocolError):
    """Raised when device reports command error via non-zero status code."""


@dataclass(frozen=True)
class TLVMessage:
    msg_type: int
    payload: bytes

    def encode(self) -> bytes:
        length = len(self.payload)
        return bytes((self.msg_type & 0xFF, (length >> 8) & 0xFF, length & 0xFF)) + self.payload


class NanoleafTLVProtocol:
    """Nanoleaf USB HID TLV protocol helper."""

    @staticmethod
    def build_request(msg_type: int, payload: bytes = b"") -> bytes:
        return TLVMessage(msg_type=msg_type, payload=payload).encode()

    @staticmethod
    def parse_tlv(data: bytes) -> TLVMessage:
        if len(data) < 3:
            raise ProtocolShortReadError(
                f"TLV response too short for header: got {len(data)} bytes"
            )

        msg_type = data[0]
        payload_len = int.from_bytes(data[1:3], byteorder="big")
        expected_len = 3 + payload_len
        if len(data) < expected_len:
            raise ProtocolShortReadError(
                f"TLV response shorter than declared length: got {len(data)} bytes, expected {expected_len}"
            )
        if len(data) > expected_len:
            # HID report padding may be present; caller should pass exact TLV bytes.
            data = data[:expected_len]

        return TLVMessage(msg_type=msg_type, payload=data[3:expected_len])

    @staticmethod
    def parse_response(request_type: int, data: bytes) -> bytes:
        message = NanoleafTLVProtocol.parse_tlv(data)
        expected_type = (request_type + 0x80) & 0xFF
        if message.msg_type != expected_type:
            raise ProtocolResponseTypeError(
                f"Unexpected response type {message.msg_type:#04x}, expected {expected_type:#04x}"
            )
        if len(message.payload) < 1:
            raise ProtocolMalformedResponseError("Response payload missing status byte")

        status = message.payload[0]
        if status != SUCCESS_CODE:
            raise ProtocolCommandError(
                f"Device returned error status={status} for request {request_type:#04x}"
            )
        return message.payload[1:]

    @staticmethod
    def parse_u8(payload: bytes, *, field_name: str) -> int:
        if len(payload) != 1:
            raise ProtocolMalformedResponseError(
                f"Expected 1-byte {field_name}, got {len(payload)} bytes"
            )
        return payload[0]

    @staticmethod
    def parse_u16_be(payload: bytes, *, field_name: str) -> int:
        if len(payload) != 2:
            raise ProtocolMalformedResponseError(
                f"Expected 2-byte {field_name}, got {len(payload)} bytes"
            )
        return int.from_bytes(payload, byteorder="big")

    @staticmethod
    def parse_model_number(payload: bytes) -> str:
        if not payload:
            raise ProtocolMalformedResponseError("Model number payload is empty")
        text = payload.decode("utf-8", errors="strict").rstrip("\x00").strip()
        if not text:
            raise ProtocolMalformedResponseError("Model number payload decodes to empty string")
        return text
