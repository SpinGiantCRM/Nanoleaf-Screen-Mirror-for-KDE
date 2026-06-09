from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nanoleaf_sync.compat import kwin_probe


class _FakeReply:
    def __init__(self, *, version: int | None = None, error_name: str | None = None) -> None:
        self.message_type = 3 if error_name else 1
        self.error_name = error_name
        self.body = [SimpleNamespace(value=version)] if version is not None else []


class _FakeBus:
    def __init__(self, version: int) -> None:
        self._version = version
        self.last_message = None

    async def connect(self):
        return self

    async def call(self, message):
        self.last_message = message
        return _FakeReply(version=self._version)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    kwin_probe.reset_kwin_probe_cache()
    yield
    kwin_probe.reset_kwin_probe_cache()


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_screenshot2_version_probe_parses_known_versions(version: int, monkeypatch) -> None:
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda: _FakeBus(version))

    assert kwin_probe.get_screenshot2_api_version(force_refresh=True) == version
    capabilities = kwin_probe.get_screenshot2_capabilities()
    assert capabilities
    if version >= 1:
        assert "CaptureWindow" in capabilities
    if version >= 5:
        assert "hide-caller-windows" in capabilities


def test_screenshot2_version_probe_uses_properties_get_message_shape(monkeypatch) -> None:
    bus = _FakeBus(3)
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda: bus)

    kwin_probe.get_screenshot2_api_version(force_refresh=True)

    message = bus.last_message
    assert message.destination == "org.kde.KWin"
    assert message.path == "/org/kde/KWin/ScreenShot2"
    assert message.interface == "org.freedesktop.DBus.Properties"
    assert message.member == "Get"
    assert message.signature == "ss"
    assert message.body == ["org.kde.KWin.ScreenShot2", "version"]


def test_screenshot2_unknown_version_assumes_v5_compat(monkeypatch, caplog) -> None:
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda: _FakeBus(7))

    version = kwin_probe.get_screenshot2_api_version(force_refresh=True)
    assert version == 7
    assert "hide-caller-windows" in kwin_probe.get_screenshot2_capabilities()
    assert any("assuming v5 compatibility" in record.message for record in caplog.records)


def test_screenshot2_probe_returns_zero_when_unavailable(monkeypatch) -> None:
    class _ErrorBus:
        async def connect(self):
            return self

        async def call(self, _message):
            return _FakeReply(error_name="org.freedesktop.DBus.Error.ServiceUnknown")

    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda: _ErrorBus())
    assert kwin_probe.get_screenshot2_api_version(force_refresh=True) == 0
    assert kwin_probe.get_screenshot2_capabilities() == set()


def test_screenshot2_probe_works_with_running_event_loop(monkeypatch) -> None:
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda: _FakeBus(4))

    async def _runner() -> int:
        return kwin_probe.get_screenshot2_api_version(force_refresh=True)

    assert asyncio.run(_runner()) == 4
