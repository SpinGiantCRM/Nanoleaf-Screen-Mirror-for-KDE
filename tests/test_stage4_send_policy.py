from __future__ import annotations

import pytest

from nanoleaf_sync.device.interfaces import NanoleafUSBIds
from nanoleaf_sync.device.send_policy import LiveSendPolicy, select_live_send_policy
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver
from tests.device.test_usb_driver import FakeTransport, _rsp


def test_probed_single_report_uses_drain_over_write_only() -> None:
    decision = select_live_send_policy(
        report_count=1,
        prefer_write_only_live_send=True,
        enable_live_frame_write_optimization=True,
        is_live_frame=True,
        has_write_with_timing=True,
        has_nonblocking_drain=True,
        first_frame_after_reopen=False,
        probed_report_size=256,
    )
    assert decision.policy == LiveSendPolicy.NONBLOCKING_DRAIN


def test_write_only_reachable_for_single_report_when_preferred() -> None:
    decision = select_live_send_policy(
        report_count=1,
        prefer_write_only_live_send=True,
        enable_live_frame_write_optimization=True,
        is_live_frame=True,
        has_write_with_timing=True,
        has_nonblocking_drain=True,
        first_frame_after_reopen=False,
    )
    assert decision.policy == LiveSendPolicy.WRITE_ONLY


def test_multi_report_frame_uses_drain_not_write_only() -> None:
    decision = select_live_send_policy(
        report_count=3,
        prefer_write_only_live_send=True,
        enable_live_frame_write_optimization=True,
        is_live_frame=True,
        has_write_with_timing=True,
        has_nonblocking_drain=True,
        first_frame_after_reopen=False,
    )
    assert decision.policy == LiveSendPolicy.NONBLOCKING_DRAIN


def test_first_frame_after_reopen_waits_for_response() -> None:
    decision = select_live_send_policy(
        report_count=1,
        prefer_write_only_live_send=True,
        enable_live_frame_write_optimization=True,
        is_live_frame=True,
        has_write_with_timing=True,
        has_nonblocking_drain=True,
        first_frame_after_reopen=True,
    )
    assert decision.policy == LiveSendPolicy.RESPONSE_REQUIRED


def test_short_live_frame_raises_in_strict_mode() -> None:
    transport = FakeTransport(
        [
            _rsp(0x0C, b"\x00NL82K2"),
            _rsp(0x03, b"\x00\x03"),
            _rsp(0x06, b"\x00\x01"),
            _rsp(0x08, b"\x00\x14"),
        ]
    )
    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(0x37FA, 0x8202), transport=transport)
    driver.initialize()
    with pytest.raises(RuntimeError, match="Refusing to silently pad short live zone colors"):
        driver.send_frame([(9, 8, 7)])


def test_driver_records_ack_counters_on_response_required_path() -> None:
    transport = FakeTransport(
        [
            _rsp(0x0C, b"\x00NL82K2"),
            _rsp(0x03, b"\x00\x03"),
            _rsp(0x06, b"\x00\x01"),
            _rsp(0x08, b"\x00\x14"),
            _rsp(0x02, b"\x00"),
        ]
    )
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(0x37FA, 0x8202),
        transport=transport,
        enable_live_frame_write_optimization=False,
    )
    driver.initialize()
    driver.send_frame([(9, 8, 7), (1, 2, 3), (4, 5, 6)])
    assert driver.ack_expected_count >= 1
    assert driver.last_send_policy_transition_reason
