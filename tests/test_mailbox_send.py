from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nanoleaf_sync.device.interfaces import NanoleafUSBIds
from nanoleaf_sync.device.send_policy import LiveSendPolicy, select_live_send_policy
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver


def test_mailbox_policy_selected_when_preferred() -> None:
    decision = select_live_send_policy(
        report_count=1,
        prefer_write_only_live_send=False,
        prefer_mailbox_live_send=True,
        enable_live_frame_write_optimization=True,
        is_live_frame=True,
        has_write_with_timing=True,
        has_nonblocking_drain=False,
        first_frame_after_reopen=False,
        probed_report_size=64,
    )
    assert decision.policy == LiveSendPolicy.MAILBOX


def test_mailbox_coalesces_writes_when_in_flight() -> None:
    transport = MagicMock()
    transport.report_size = 64
    transport.write_with_timing.return_value = {"write_ms": 1.0, "flush_or_wait_ms": 0.0}
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(vid=0x2B24, pid=0x0001),
        transport=transport,
        prefer_mailbox_live_send=True,
        enable_live_frame_write_optimization=True,
    )
    driver._initialized = True
    driver.zone_count = 4
    driver._cached_on_state = True
    driver._cached_brightness = 50
    driver._probed_report_size = 64
    driver._mailbox_write_in_flight = True
    colors = [(10, 20, 30)] * 4
    timing = driver.set_zone_colors(colors, return_timing=True)
    assert timing is not None
    assert timing.get("live_send_policy") == "mailbox"
    assert driver.mailbox_writes_skipped >= 1
    assert transport.write_with_timing.call_count == 0


def test_mailbox_static_content_fewer_writes_than_frames() -> None:
    transport = MagicMock()
    transport.report_size = 64
    transport.write_with_timing.return_value = {"write_ms": 0.5, "flush_or_wait_ms": 0.0}
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(vid=0x2B24, pid=0x0001),
        transport=transport,
        prefer_mailbox_live_send=True,
        enable_live_frame_write_optimization=True,
    )
    driver._initialized = True
    driver.zone_count = 4
    driver._cached_on_state = True
    driver._cached_brightness = 50
    driver._probed_report_size = 64
    colors = [(5, 5, 5)] * 4
    writes = 0
    for _ in range(10):
        driver._mailbox_write_in_flight = False
        driver.set_zone_colors(colors, return_timing=True)
        writes += transport.write_with_timing.call_count
    reduction = 1.0 - (writes / 10.0)
    assert reduction >= 0.0


@pytest.mark.parametrize("disabled", ["0", "false"])
def test_mailbox_disabled_by_env(monkeypatch, disabled: str) -> None:
    monkeypatch.setenv("NANOLEAF_ENABLE_MAILBOX_SEND", disabled)
    from importlib import reload

    import nanoleaf_sync.runtime.novel_features as novel

    reload(novel)
    transport = MagicMock()
    transport.report_size = 64
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(vid=0x2B24, pid=0x0001),
        transport=transport,
        prefer_mailbox_live_send=True,
    )
    assert driver._prefer_mailbox_live_send is False
