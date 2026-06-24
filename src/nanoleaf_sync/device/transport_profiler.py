from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class USBTransportProfile:
    hidapi_module: str
    hidapi_version: str
    backend_class: str
    opened_path: str
    report_size: int
    report_id_prefix_required: str
    read_framing: str
    live_send_policy: str
    ack_expected_count: int
    ack_received_count: int
    ack_missed_count: int
    missed_ack_rate: float
    last_ack_status: str
    send_policy_transition_reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "hidapi_module": self.hidapi_module,
            "hidapi_version": self.hidapi_version,
            "backend_class": self.backend_class,
            "opened_path": self.opened_path,
            "report_size": self.report_size,
            "report_id_prefix_required": self.report_id_prefix_required,
            "read_framing": self.read_framing,
            "live_send_policy": self.live_send_policy,
            "ack_expected_count": self.ack_expected_count,
            "ack_received_count": self.ack_received_count,
            "ack_missed_count": self.ack_missed_count,
            "missed_ack_rate": self.missed_ack_rate,
            "last_ack_status": self.last_ack_status,
            "send_policy_transition_reason": self.send_policy_transition_reason,
        }


def build_usb_transport_profile(driver: object) -> USBTransportProfile:
    transport = getattr(driver, "_transport", None)
    expected = int(getattr(driver, "ack_expected_count", 0) or 0)
    received = int(getattr(driver, "ack_received_count", 0) or 0)
    missed = int(getattr(driver, "ack_missed_count", 0) or 0)
    denom = max(1, expected)
    missed_rate = float(missed) / float(denom)
    hid_module = ""
    hid_version = ""
    try:
        import hidraw  # type: ignore[import-untyped]

        hid_module = str(getattr(hidraw, "__file__", "") or "")
        hid_version = str(getattr(hidraw, "__version__", "") or "")
    except ImportError:
        try:
            import hid  # type: ignore[import-untyped]

            hid_module = str(getattr(hid, "__file__", "") or "")
            hid_version = str(getattr(hid, "__version__", "") or "")
        except Exception:
            pass
    opened_path = str(getattr(transport, "device_path", "") or getattr(transport, "path", "") or "")
    backend_class = str(getattr(transport, "backend_name", "") or "unknown")
    report_size = int(
        getattr(driver, "report_size", 0) or getattr(transport, "report_size", 0) or 0
    )
    prefix_mode = str(getattr(transport, "report_id_prefix_mode", "unknown") or "unknown")
    read_framing = str(getattr(transport, "read_framing_mode", "unknown") or "unknown")
    live_policy = str(getattr(driver, "last_live_send_policy", "") or "response_required")
    return USBTransportProfile(
        hidapi_module=hid_module,
        hidapi_version=hid_version,
        backend_class=backend_class,
        opened_path=opened_path,
        report_size=report_size,
        report_id_prefix_required=prefix_mode,
        read_framing=read_framing,
        live_send_policy=live_policy,
        ack_expected_count=expected,
        ack_received_count=received,
        ack_missed_count=missed,
        missed_ack_rate=missed_rate,
        last_ack_status=str(getattr(driver, "last_ack_status", "") or ""),
        send_policy_transition_reason=str(
            getattr(driver, "last_send_policy_transition_reason", "") or ""
        ),
    )
