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
from nanoleaf_sync.device.send_policy import (
    LiveSendPolicy,
    apply_periodic_ack_check,
    degrade_policy_on_missed_acks,
    select_live_send_policy,
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
        allow_live_zone_padding: bool = False,
    ) -> None:
        self.ids = ids
        self.report_size = int(report_size)
        self._transport = transport or HIDTransport(
            ids=ids, report_size=report_size, read_timeout_ms=100
        )
        self._protocol = protocol or NanoleafTLVProtocol()
        self._min_nonzero_brightness = max(1, min(255, int(min_nonzero_brightness)))
        self._configured_zone_count = max(0, int(configured_zone_count))
        self._enable_live_frame_write_optimization = bool(enable_live_frame_write_optimization)
        self._prefer_write_only_live_send = bool(prefer_write_only_live_send)
        self._auto_turn_on = bool(auto_turn_on)
        self._allow_live_zone_padding = bool(allow_live_zone_padding)
        order = str(output_channel_order or "grb").strip().lower()
        self._set_output_channel_order(order, source="config")

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
        self._live_frames_sent_after_open: int = 0
        self._total_live_frames_sent: int = 0
        self.ack_expected_count: int = 0
        self.ack_received_count: int = 0
        self.ack_missed_count: int = 0
        self.last_ack_status: str = ""
        self.last_ack_age_ms: float | None = None
        self.last_send_policy_transition_reason: str = ""
        self.last_live_send_policy: str = "response_required"
        self.uncertain_write_failures: int = 0
        self._zone_mismatch_attempts: int = 0
        self.output_channel_order_source: str = "config"

    def _set_output_channel_order(self, order: str, *, source: str) -> None:
        normalized = str(order or "grb").strip().lower()
        if sorted(normalized) != ["b", "g", "r"]:
            raise ValueError(
                "output_channel_order must be a permutation of 'rgb' (for example: rgb, grb, bgr)."
            )
        self._output_channel_order = normalized
        self._output_channel_indices = tuple(
            {"r": 0, "g": 1, "b": 2}[ch] for ch in self._output_channel_order
        )
        self.output_channel_order_source = str(source or "config")

    @staticmethod
    def _channel_order_for_model(model_number: str | None) -> str:
        if str(model_number or "").strip().upper() in {"NL82K1", "NL82K2"}:
            return "grb"
        return "grb"

    def probe_output_channel_order(self) -> str:
        order = self._channel_order_for_model(self.model_number)
        self._set_output_channel_order(order, source="model-probe")
        return order

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
            if self._output_channel_order == "grb":
                self.probe_output_channel_order()
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

    def _try_recover_zone_count(self, frame_len: int) -> bool:
        if self._zone_mismatch_attempts >= 2:
            return False
        self._zone_mismatch_attempts += 1
        self._logger.warning(
            "Zone count mismatch (frame=%d effective=%s); re-reading device length (attempt %d)",
            frame_len,
            self.zone_count,
            self._zone_mismatch_attempts,
        )
        try:
            detected = self.get_length()
            self.reported_zone_count = detected
            if self._configured_zone_count > 0:
                self.zone_count = self._configured_zone_count
            else:
                self.zone_count = detected
            return True
        except Exception:
            self._logger.warning(
                "Failed to re-read device zone count after mismatch",
                exc_info=True,
            )
            return False

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

        if len(normalized) < self.zone_count:
            if not self._allow_live_zone_padding:
                recovered = self._try_recover_zone_count(len(normalized))
                target = int(self.zone_count or 0)
                if recovered and len(normalized) < target:
                    pad_count = target - len(normalized)
                    normalized.extend([(0, 0, 0)] * pad_count)
                if len(normalized) < target:
                    raise RuntimeError(
                        "Refusing to silently pad short live zone colors: "
                        f"frame_colors={len(normalized)} is below "
                        f"effective_zone_count={self.zone_count} "
                        f"(reported_zone_count={self.reported_zone_count}, "
                        f"configured_zone_count={self._configured_zone_count}). "
                        "Update device_zone_count calibration/config so runtime mapping "
                        "matches the physical strip."
                    )
            else:
                normalized.extend([(0, 0, 0)] * (self.zone_count - len(normalized)))
        elif len(normalized) > self.zone_count:
            if self._try_recover_zone_count(len(normalized)) and len(normalized) <= int(
                self.zone_count or 0
            ):
                pass
            elif len(normalized) > int(self.zone_count or 0):
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
        payload_buffer = bytearray(payload_len)
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
        write_with_nonblocking_drain = getattr(
            self._transport,
            "write_with_nonblocking_drain",
            None,
        )
        write_with_timing = getattr(self._transport, "write_with_timing", None)
        policy_decision = select_live_send_policy(
            report_count=report_count,
            prefer_write_only_live_send=self._prefer_write_only_live_send,
            enable_live_frame_write_optimization=self._enable_live_frame_write_optimization,
            is_live_frame=self._is_live_frame_command(CMD_SET_ZONE_COLORS),
            has_write_with_timing=callable(write_with_timing),
            has_nonblocking_drain=callable(write_with_nonblocking_drain),
            first_frame_after_reopen=self._live_frames_sent_after_open <= 0,
            probed_report_size=self._probed_report_size,
        )
        policy_decision = apply_periodic_ack_check(
            policy_decision,
            live_frame_index=self._total_live_frames_sent + 1,
        )
        missed_rate = float(self.ack_missed_count) / float(max(1, self.ack_expected_count))
        policy_decision = degrade_policy_on_missed_acks(
            policy_decision,
            missed_ack_rate=missed_rate,
        )
        live_send_policy = policy_decision.policy.value
        response_wait_skipped = policy_decision.response_wait_skipped
        self.last_send_policy_transition_reason = policy_decision.transition_reason
        self.last_live_send_policy = live_send_policy
        send_err: Exception | None = None
        if policy_decision.policy == LiveSendPolicy.WRITE_ONLY and callable(write_with_timing):
            try:
                maybe_timing = write_with_timing(request)
                if isinstance(maybe_timing, dict):
                    transport_timing = maybe_timing
                transport_timing.setdefault("flush_or_wait_ms", 0.0)
                transport_timing.setdefault("read_calls", 0)
            except Exception as exc:
                if self._write_failed_before_any_bytes(exc):
                    send_err = exc
                    live_send_policy = LiveSendPolicy.RESPONSE_REQUIRED.value
                    response_wait_skipped = False
                else:
                    self.uncertain_write_failures += 1
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
        elif policy_decision.policy == LiveSendPolicy.NONBLOCKING_DRAIN and callable(
            write_with_nonblocking_drain
        ):
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
            except Exception as exc:
                if self._write_failed_before_any_bytes(exc):
                    send_err = exc
                    live_send_policy = LiveSendPolicy.RESPONSE_REQUIRED.value
                    response_wait_skipped = False
                else:
                    self.uncertain_write_failures += 1
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
        if live_send_policy == LiveSendPolicy.RESPONSE_REQUIRED.value:
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
            "send_policy_transition_reason": self.last_send_policy_transition_reason,
            "probed_report_size": self._probed_report_size,
        }
        if self._is_live_frame_command(CMD_SET_ZONE_COLORS):
            if live_send_policy == LiveSendPolicy.RESPONSE_REQUIRED.value:
                self.ack_expected_count += 1
            ack_arrival = timing.get("ack_arrival_ms")
            if ack_arrival is not None:
                self.ack_received_count += 1
                self.last_ack_status = "received"
                self.last_ack_age_ms = float(ack_arrival)
            elif live_send_policy == LiveSendPolicy.RESPONSE_REQUIRED.value:
                self.ack_missed_count += 1
                self.last_ack_status = "missed"
            self._live_frames_sent_after_open += 1
            self._total_live_frames_sent += 1
            timing["ack_expected_count"] = self.ack_expected_count
            timing["ack_received_count"] = self.ack_received_count
            timing["ack_missed_count"] = self.ack_missed_count
            timing["ack_backlog_estimate"] = max(
                0,
                self.ack_expected_count - self.ack_received_count,
            )
            timing["last_ack_status"] = self.last_ack_status
            timing["last_ack_age_ms"] = self.last_ack_age_ms
            timing["uncertain_write_failures"] = self.uncertain_write_failures
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
            self._live_frames_sent_after_open = 0
            self.last_ack_status = ""
            self.last_ack_age_ms = None
