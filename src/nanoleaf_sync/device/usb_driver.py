from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any

from nanoleaf_sync.device.hid_transport import HIDTransport, HIDWriteError
from nanoleaf_sync.device.interfaces import (
    DeviceDriver,
    DriverCapabilities,
    NanoleafUSBIds,
    RGBTuple,
)
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
        enable_live_frame_write_optimization: bool = True,
        prefer_write_only_live_send: bool = False,
        auto_turn_on: bool = True,
    ) -> None:
        self.ids = ids
        self.report_size = int(report_size)
        self._transport = transport or HIDTransport(
            ids=ids, report_size=report_size, read_timeout_ms=50
        )
        self._protocol = protocol or NanoleafTLVProtocol()
        self._min_nonzero_brightness = max(1, min(255, int(min_nonzero_brightness)))
        self._configured_zone_count = max(0, int(configured_zone_count))
        self._enable_live_frame_write_optimization = bool(enable_live_frame_write_optimization)
        self._prefer_write_only_live_send = bool(prefer_write_only_live_send)
        self._auto_turn_on = bool(auto_turn_on)
        order = str(output_channel_order or "grb").strip().lower()
        if sorted(order) != ["b", "g", "r"]:
            raise ValueError(
                "output_channel_order must be a permutation of 'rgb' (for example: rgb, grb, bgr)."
            )
        self._output_channel_order = order
        self._output_channel_indices = tuple(
            {"r": 0, "g": 1, "b": 2}[ch] for ch in self._output_channel_order
        )

        self.model_number: str | None = None
        self.zone_count: int | None = None
        self.reported_zone_count: int | None = None
        self._initialized = False
        self._cached_on_state: bool | None = None
        self._cached_brightness: int | None = None
        self.last_send_timing: dict[str, Any] = {}
        self._live_payload_buffer: bytearray | None = None
        self._live_target_fps: int = 60
        self._probed_report_size: int | None = None

    def _request(self, cmd: int, payload: bytes = b"") -> bytes:
        request = self._protocol.build_request(cmd, payload)
        raw_response = self._transport.transceive(request)
        return self._protocol.parse_response(cmd, raw_response)

    @staticmethod
    def _is_live_frame_command(cmd: int) -> bool:
        return int(cmd) == int(CMD_SET_ZONE_COLORS)

    def _request_with_timing(
        self, cmd: int, payload: bytes = b""
    ) -> tuple[bytes, dict[str, float | int | bool | str | list[int] | list[float]]]:
        request = self._protocol.build_request(cmd, payload)
        transceive_with_timing = getattr(self._transport, "transceive_with_timing", None)
        if callable(transceive_with_timing):
            raw_response, timing = transceive_with_timing(request)
            parsed = self._protocol.parse_response(cmd, raw_response)
            normalized_timing: dict[str, float | int | bool | str | list[int] | list[float]] = {}
            if isinstance(timing, dict):
                normalized_timing.update(timing)
            return parsed, normalized_timing
        raw_response = self._transport.transceive(request)
        parsed = self._protocol.parse_response(cmd, raw_response)
        return parsed, {}

    @staticmethod
    def _write_failed_before_any_bytes(exc: Exception) -> bool:
        status = getattr(exc, "write_status", None)
        if status in {"not_started", "before_write"}:
            return True
        if isinstance(exc, HIDWriteError):
            return exc.write_status == "not_started"
        return False

    def _mark_live_frame_write_failed(
        self,
        *,
        exc: Exception,
        frame_build_ms: float,
        request_len: int,
        report_size: int,
        report_count: int,
        chunk_sizes: list[int],
        live_send_policy: str,
        response_wait_skipped: bool,
    ) -> None:
        write_status = str(getattr(exc, "write_status", "uncertain") or "uncertain")
        self.last_send_timing = {
            "frame_build_ms": frame_build_ms,
            "device_write_ms": 0.0,
            "flush_or_wait_ms": None,
            "device_limited": False,
            "flush_or_wait_reason": (
                "Live HID write failed before a response wait could safely run."
            ),
            "reports_per_frame": int(report_count),
            "bytes_per_report": int(report_size),
            "total_frame_bytes": int(request_len),
            "report_data_sizes": chunk_sizes,
            "per_report_write_ms": [],
            "write_blocking": True,
            "write_retry_policy": "none",
            "write_rate_limit_policy": "none",
            "write_read_calls": 0,
            "live_send_policy": live_send_policy,
            "response_wait_skipped": response_wait_skipped,
            "send_failed": True,
            "failure_stage": "live_frame_write",
            "write_status": write_status,
            "write_failure_reason": f"{type(exc).__name__}: {exc}",
            "recovery_action": "closed_transport_for_reopen",
        }

    def _close_after_uncertain_live_write(self, exc: Exception) -> None:
        try:
            self.close()
        except Exception:
            self._logger.exception(
                "Failed to close HID transport after uncertain live frame write failure",
            )
        self._logger.warning(
            "Live HID frame write failed with uncertain device state; "
            "closed transport before retrying future frames: %s: %s",
            type(exc).__name__,
            exc,
        )

    def initialize(self) -> None:
        if self._initialized:
            return
        self._transport.open(retry_attempts=3, retry_delay_s=0.5)
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
            # Pre-read on/off state and brightness during init so the
            # first set_zone_colors call doesn't add extra HID round-trips.
            self._cached_on_state = self.get_on_off_state()
            self._cached_brightness = self.get_brightness()
            if self._prefer_write_only_live_send:
                self._apply_live_report_size_probe()
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

    def _apply_live_report_size_probe(self) -> None:
        zone_count = int(self.zone_count or self._configured_zone_count or 0)
        if zone_count <= 0:
            return
        request_len = 3 + (zone_count * 3)
        for candidate in (256, 128, 64):
            report_count = max(1, (request_len + candidate - 1) // candidate)
            if report_count == 1:
                if candidate != self.report_size:
                    self._logger.info(
                        "USB live report-size probe selected report_size=%d "
                        "for zone_count=%d request_len=%d",
                        candidate,
                        zone_count,
                        request_len,
                    )
                self.report_size = int(candidate)
                self._transport.report_size = int(candidate)
                self._probed_report_size = int(candidate)
                return

    def set_brightness(self, value: int) -> None:
        clamped = max(0, min(255, int(value)))
        self._request(CMD_SET_BRIGHTNESS, bytes((clamped,)))
        self._cached_brightness = clamped

    def set_zone_colors(
        self, colors: Sequence[RGBTuple], *, return_timing: bool = False
    ) -> dict[str, float | bool | str | None] | None:
        if not self._initialized:
            self.initialize()
        if self.zone_count is None:
            raise RuntimeError(
                "Driver not initialized correctly: device strip length was not discovered."
            )

        if self._cached_on_state is None:
            self.get_on_off_state()
        if self._auto_turn_on and not self._cached_on_state:
            self.set_on_off_state(True)

        if self._cached_brightness is None:
            self.get_brightness()
        if self._auto_turn_on and self._cached_brightness == 0:
            self.set_brightness(self._min_nonzero_brightness)

        frame_build_start = time.perf_counter()
        normalized = [
            (max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b))))
            for r, g, b in colors
        ]

        # Host policy (not protocol requirement): pad with black/off zones when short.
        if len(normalized) < self.zone_count:
            normalized.extend([(0, 0, 0)] * (self.zone_count - len(normalized)))
        elif len(normalized) > self.zone_count:
            raise RuntimeError(
                "Refusing to silently truncate zone colors: "
                f"frame_colors={len(normalized)} exceeds "
                f"effective_zone_count={self.zone_count} "
                f"(reported_zone_count={self.reported_zone_count}, "
                f"configured_zone_count={self._configured_zone_count}). "
                "Update device_zone_count calibration/config so runtime mapping "
                "matches the physical strip."
            )

        payload_len = len(normalized) * 3
        if self._live_payload_buffer is None or len(self._live_payload_buffer) != payload_len:
            self._live_payload_buffer = bytearray(payload_len)
        payload_buffer = self._live_payload_buffer
        write_idx = 0
        for rgb in normalized:
            for channel_idx in self._output_channel_indices:
                payload_buffer[write_idx] = rgb[channel_idx]
                write_idx += 1
        payload = bytes(payload_buffer)
        frame_build_end = time.perf_counter()
        request_len = 3 + len(payload)
        report_size = int(getattr(self._transport, "report_size", self.report_size))
        report_count = (
            max(1, (request_len + report_size - 1) // report_size) if report_size > 0 else 0
        )
        chunk_sizes = []
        if report_size > 0:
            chunk_sizes = [
                min(report_size, request_len - idx) for idx in range(0, request_len, report_size)
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
        request = self._protocol.build_request(CMD_SET_ZONE_COLORS, payload)
        transport_timing: dict[str, float | int | bool | str | list[int] | list[float]] = {}
        live_send_policy = "response_required"
        response_wait_skipped = False
        send_err: Exception | None = None
        requires_frame_ack = report_count > 1 or self._prefer_write_only_live_send
        if (
            self._is_live_frame_command(CMD_SET_ZONE_COLORS)
            and self._enable_live_frame_write_optimization
        ):
            write_with_nonblocking_drain = getattr(
                self._transport, "write_with_nonblocking_drain", None
            )
            write_with_timing = getattr(self._transport, "write_with_timing", None)
            if (
                callable(write_with_timing)
                and self._prefer_write_only_live_send
                and not requires_frame_ack
            ):
                live_send_policy = "write_only"
                response_wait_skipped = True
                try:
                    maybe_timing = write_with_timing(request)
                    if isinstance(maybe_timing, dict):
                        transport_timing = maybe_timing
                    transport_timing.setdefault("flush_or_wait_ms", 0.0)
                    transport_timing.setdefault("read_calls", 0)
                except Exception as exc:
                    if self._write_failed_before_any_bytes(exc):
                        send_err = exc
                        live_send_policy = "response_required"
                        response_wait_skipped = False
                    else:
                        frame_build_ms = (frame_build_end - frame_build_start) * 1000.0
                        self._mark_live_frame_write_failed(
                            exc=exc,
                            frame_build_ms=frame_build_ms,
                            request_len=request_len,
                            report_size=report_size,
                            report_count=report_count,
                            chunk_sizes=chunk_sizes,
                            live_send_policy=live_send_policy,
                            response_wait_skipped=response_wait_skipped,
                        )
                        self._close_after_uncertain_live_write(exc)
                        raise RuntimeError(
                            "Live frame write failed with uncertain HID write status; "
                            "closed transport and skipped immediate fallback "
                            "to avoid duplicate frame send."
                        ) from exc
            elif callable(write_with_nonblocking_drain):
                live_send_policy = "nonblocking_drain"
                response_wait_skipped = True
                try:
                    drain_call = write_with_nonblocking_drain
                    try:
                        maybe_timing = drain_call(
                            request,
                            target_fps=int(self._live_target_fps),
                            drain_budget_ms=2,
                            max_drain_reads=2,
                        )
                    except TypeError:
                        maybe_timing = drain_call(request)
                    if isinstance(maybe_timing, dict):
                        transport_timing = maybe_timing
                        drain_reads = int(transport_timing.get("read_calls", 0))
                        drain_ms = transport_timing.get("flush_or_wait_ms", 0.0)
                        self._logger.debug(
                            "nonblocking drain: read_calls=%d flush_or_wait_ms=%.2f",
                            drain_reads,
                            float(drain_ms) if drain_ms is not None else 0.0,
                        )
                except Exception as exc:
                    if self._write_failed_before_any_bytes(exc):
                        send_err = exc
                        live_send_policy = "response_required"
                        response_wait_skipped = False
                    else:
                        frame_build_ms = (frame_build_end - frame_build_start) * 1000.0
                        self._mark_live_frame_write_failed(
                            exc=exc,
                            frame_build_ms=frame_build_ms,
                            request_len=request_len,
                            report_size=report_size,
                            report_count=report_count,
                            chunk_sizes=chunk_sizes,
                            live_send_policy=live_send_policy,
                            response_wait_skipped=response_wait_skipped,
                        )
                        self._close_after_uncertain_live_write(exc)
                        raise RuntimeError(
                            "Live frame write failed with uncertain HID write status; "
                            "closed transport and skipped immediate fallback "
                            "to avoid duplicate frame send."
                        ) from exc
            elif callable(write_with_timing):
                live_send_policy = "write_only"
                response_wait_skipped = True
                try:
                    maybe_timing = write_with_timing(request)
                    if isinstance(maybe_timing, dict):
                        transport_timing = maybe_timing
                    transport_timing.setdefault("flush_or_wait_ms", 0.0)
                    transport_timing.setdefault("read_calls", 0)
                except Exception as exc:
                    if self._write_failed_before_any_bytes(exc):
                        send_err = exc
                        live_send_policy = "response_required"
                        response_wait_skipped = False
                    else:
                        frame_build_ms = (frame_build_end - frame_build_start) * 1000.0
                        self._mark_live_frame_write_failed(
                            exc=exc,
                            frame_build_ms=frame_build_ms,
                            request_len=request_len,
                            report_size=report_size,
                            report_count=report_count,
                            chunk_sizes=chunk_sizes,
                            live_send_policy=live_send_policy,
                            response_wait_skipped=response_wait_skipped,
                        )
                        self._close_after_uncertain_live_write(exc)
                        raise RuntimeError(
                            "Live frame write failed with uncertain HID write status; "
                            "closed transport and skipped immediate fallback "
                            "to avoid duplicate frame send."
                        ) from exc
        if live_send_policy == "response_required":
            try:
                _, transport_timing = self._request_with_timing(CMD_SET_ZONE_COLORS, payload)
            except Exception:
                if send_err is not None:
                    raise RuntimeError(
                        "Live frame write-only path failed and "
                        "response-required fallback also failed."
                    ) from send_err
                raise
        device_write_ms = float(transport_timing.get("write_ms") or 0.0)
        flush_or_wait_ms = (
            float(transport_timing.get("flush_or_wait_ms"))
            if transport_timing.get("flush_or_wait_ms") is not None
            else None
        )
        report_data_sizes = transport_timing.get("report_data_sizes")
        per_report_write_ms = transport_timing.get("per_report_write_ms")
        total_bytes = int(transport_timing.get("total_frame_bytes") or request_len)
        if live_send_policy in {"write_only", "nonblocking_drain"}:
            reports_per_frame = report_count
            bytes_per_report = report_size
            if not isinstance(report_data_sizes, list):
                report_data_sizes = chunk_sizes
        else:
            reports_per_frame = int(transport_timing.get("report_count") or report_count)
            bytes_per_report = int(transport_timing.get("bytes_per_report") or report_size)
        if isinstance(report_data_sizes, list) and isinstance(per_report_write_ms, list):
            self._logger.debug(
                "USB HID write timing: reports_per_frame=%d bytes_per_report=%d "
                "total_frame_bytes=%d "
                "report_data_sizes=%s per_report_write_ms=%s write_ms=%.2f flush_or_wait_ms=%s "
                "write_blocking=%s retry_policy=%s rate_limit_policy=%s",
                reports_per_frame,
                bytes_per_report,
                total_bytes,
                report_data_sizes,
                [round(float(v), 3) for v in per_report_write_ms],
                device_write_ms,
                f"{float(flush_or_wait_ms):.3f}" if flush_or_wait_ms is not None else "unavailable",
                "yes" if bool(transport_timing.get("write_blocking", True)) else "no",
                str(transport_timing.get("retry_policy", "none")),
                str(transport_timing.get("rate_limit_policy", "none")),
            )
        timing = {
            "frame_build_ms": (frame_build_end - frame_build_start) * 1000.0,
            "device_write_ms": device_write_ms,
            "flush_or_wait_ms": flush_or_wait_ms,
            "device_limited": device_write_ms >= 5.0,
            "flush_or_wait_reason": (
                "Measured as HID response wait/read time in transport transceive path."
                if flush_or_wait_ms is not None
                else "Flush/wait timing unavailable in current HID transport path."
            ),
            "reports_per_frame": reports_per_frame,
            "bytes_per_report": bytes_per_report,
            "total_frame_bytes": total_bytes,
            "report_data_sizes": report_data_sizes
            if isinstance(report_data_sizes, list)
            else chunk_sizes,
            "per_report_write_ms": per_report_write_ms
            if isinstance(per_report_write_ms, list)
            else [],
            "write_blocking": bool(transport_timing.get("write_blocking", True)),
            "write_retry_policy": str(transport_timing.get("retry_policy", "none")),
            "write_rate_limit_policy": str(transport_timing.get("rate_limit_policy", "none")),
            "write_read_calls": int(transport_timing.get("read_calls") or 0),
            "ack_arrival_ms": (
                float(transport_timing.get("ack_arrival_ms"))
                if transport_timing.get("ack_arrival_ms") is not None
                else None
            ),
            "live_send_policy": live_send_policy,
            "response_wait_skipped": response_wait_skipped,
            "probed_report_size": self._probed_report_size,
        }
        if send_err is not None:
            timing["write_only_failure_reason"] = f"{type(send_err).__name__}: {send_err}"
        self.last_send_timing = timing
        if bool(timing.get("device_limited")):
            live_fps = int(getattr(self, "_live_target_fps", 0) or 0)
            if live_fps > 0:
                budget_ms = 1000.0 / float(live_fps)
                wait_ms = max(0.0, budget_ms - device_write_ms)
                if wait_ms >= 0.5:
                    time.sleep(wait_ms / 1000.0)
        if return_timing:
            return timing
        return None

    def send_frame(self, colors: Sequence[RGBTuple]) -> None:
        self.set_zone_colors(colors)

    def send_frame_with_timing(
        self, colors: Sequence[RGBTuple]
    ) -> dict[str, float | bool | str | None]:
        timing = self.set_zone_colors(colors, return_timing=True)
        if isinstance(timing, dict):
            return timing
        return {
            "frame_build_ms": None,
            "device_write_ms": None,
            "flush_or_wait_ms": None,
            "device_limited": False,
            "flush_or_wait_reason": "Timing unavailable.",
        }

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
