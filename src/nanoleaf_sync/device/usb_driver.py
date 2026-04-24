from __future__ import annotations

import logging
from typing import Sequence

from nanoleaf_sync.device.hid_transport import HIDTransport
from nanoleaf_sync.device.interfaces import DeviceDriver, DriverCapabilities, NanoleafUSBIds, RGBTuple
from nanoleaf_sync.device.protocol import (
    CMD_GET_BRIGHTNESS,
    CMD_GET_LENGTH,
    CMD_GET_MODEL_NUMBER,
    CMD_GET_ON_OFF,
    CMD_SET_BRIGHTNESS,
    CMD_SET_ON_OFF,
    CMD_SET_ZONE_COLORS,
    SUPPORTED_MODEL_NUMBERS,
    NanoleafTLVProtocol,
)


class NanoleafUSBDriver(DeviceDriver):
    """Nanoleaf USB HID driver using the official TLV request/response protocol."""

    capabilities = DriverCapabilities(name="nanoleaf-usb")
    _logger = logging.getLogger(__name__)

    def __init__(
        self,
        *,
        ids: NanoleafUSBIds,
        report_size: int = 64,
        transport: HIDTransport | None = None,
        protocol: NanoleafTLVProtocol | None = None,
        min_nonzero_brightness: int = 10,
        output_channel_order: str = "grb",
        configured_zone_count: int = 0,
    ) -> None:
        self.ids = ids
        self.report_size = int(report_size)
        self._transport = transport or HIDTransport(
            ids=ids, report_size=report_size, read_timeout_ms=50
        )
        self._protocol = protocol or NanoleafTLVProtocol()
        self._min_nonzero_brightness = max(1, min(255, int(min_nonzero_brightness)))
        self._configured_zone_count = max(0, int(configured_zone_count))
        order = str(output_channel_order or "grb").strip().lower()
        if sorted(order) != ["b", "g", "r"]:
            raise ValueError(
                "output_channel_order must be a permutation of 'rgb' (for example: rgb, grb, bgr)."
            )
        self._output_channel_order = order

        self.model_number: str | None = None
        self.zone_count: int | None = None
        self.reported_zone_count: int | None = None
        self._initialized = False
        self._cached_on_state: bool | None = None
        self._cached_brightness: int | None = None

    def _request(self, cmd: int, payload: bytes = b"") -> bytes:
        request = self._protocol.build_request(cmd, payload)
        raw_response = self._transport.transceive(request)
        return self._protocol.parse_response(cmd, raw_response)

    def initialize(self) -> None:
        if self._initialized:
            return
        self._transport.open()
        try:
            self.model_number = self.get_model_number()
            if self.model_number not in SUPPORTED_MODEL_NUMBERS:
                raise RuntimeError(
                    f"Unsupported Nanoleaf model '{self.model_number}'. "
                    f"Expected one of: {', '.join(sorted(SUPPORTED_MODEL_NUMBERS))}"
                )
            detected_zone_count = self.get_length()
            self.reported_zone_count = detected_zone_count
            self.zone_count = (
                self._configured_zone_count
                if self._configured_zone_count > 0
                else detected_zone_count
            )
            self._initialized = True
        except Exception:
            self.close()
            raise

    def get_model_number(self) -> str:
        payload = self._request(CMD_GET_MODEL_NUMBER)
        model = self._protocol.parse_model_number(payload)
        self.model_number = model
        return model

    def get_length(self) -> int:
        payload = self._request(CMD_GET_LENGTH)
        length = self._protocol.parse_u8(payload, field_name="length")
        self.zone_count = length
        return length

    def get_on_off_state(self) -> bool:
        payload = self._request(CMD_GET_ON_OFF)
        state = bool(self._protocol.parse_u8(payload, field_name="on/off state"))
        self._cached_on_state = state
        return state

    def set_on_off_state(self, state: bool) -> None:
        self._request(CMD_SET_ON_OFF, bytes((1 if state else 0,)))
        self._cached_on_state = bool(state)

    def get_brightness(self) -> int:
        payload = self._request(CMD_GET_BRIGHTNESS)
        value = self._protocol.parse_u8(payload, field_name="brightness")
        self._cached_brightness = value
        return value

    def set_brightness(self, value: int) -> None:
        clamped = max(0, min(255, int(value)))
        self._request(CMD_SET_BRIGHTNESS, bytes((clamped,)))
        self._cached_brightness = clamped

    def set_zone_colors(self, colors: Sequence[RGBTuple]) -> None:
        if not self._initialized:
            self.initialize()
        if self.zone_count is None:
            raise RuntimeError(
                "Driver not initialized correctly: device strip length was not discovered."
            )

        if self._cached_on_state is None:
            self.get_on_off_state()
        if not self._cached_on_state:
            self.set_on_off_state(True)

        if self._cached_brightness is None:
            self.get_brightness()
        if self._cached_brightness == 0:
            self.set_brightness(self._min_nonzero_brightness)

        normalized = [
            (max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b))))
            for r, g, b in colors
        ]

        # Host policy (not protocol requirement): if fewer colors than zones, pad with black/off zones.
        if len(normalized) < self.zone_count:
            normalized.extend([(0, 0, 0)] * (self.zone_count - len(normalized)))
        elif len(normalized) > self.zone_count:
            raise RuntimeError(
                "Refusing to silently truncate zone colors: "
                f"frame_colors={len(normalized)} exceeds effective_zone_count={self.zone_count} "
                f"(reported_zone_count={self.reported_zone_count}, configured_zone_count={self._configured_zone_count}). "
                "Update device_zone_count calibration/config so runtime mapping matches the physical strip."
            )

        index_by_channel = {"r": 0, "g": 1, "b": 2}
        payload = bytes(
            rgb[index_by_channel[ch]]
            for rgb in normalized
            for ch in self._output_channel_order
        )
        request_len = 3 + len(payload)
        report_size = int(getattr(self._transport, "report_size", self.report_size))
        report_count = max(1, (request_len + report_size - 1) // report_size) if report_size > 0 else 0
        chunk_sizes = []
        if report_size > 0:
            chunk_sizes = [
                min(report_size, request_len - idx)
                for idx in range(0, request_len, report_size)
            ]
        self._logger.debug(
            "USB zone frame diagnostics: command=0x%02x intended_zone_count=%d payload_bytes=%d "
            "request_bytes=%d report_size=%d report_count=%d chunk_sizes=%s",
            CMD_SET_ZONE_COLORS,
            len(normalized),
            len(payload),
            request_len,
            report_size,
            report_count,
            chunk_sizes,
        )
        self._request(CMD_SET_ZONE_COLORS, payload)

    def send_frame(self, colors: Sequence[RGBTuple]) -> None:
        self.set_zone_colors(colors)

    def close(self) -> None:
        try:
            self._transport.close()
        finally:
            self._initialized = False
            self.model_number = None
            self.zone_count = None
            self.reported_zone_count = None
            self._cached_on_state = None
            self._cached_brightness = None
