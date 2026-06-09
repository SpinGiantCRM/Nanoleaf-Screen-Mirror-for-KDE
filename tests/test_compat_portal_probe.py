from __future__ import annotations

import asyncio

import pytest

from nanoleaf_sync.compat import portal_probe


class _FakeReply:
    def __init__(self, *, version: int | None = None, error_name: str | None = None) -> None:
        self.message_type = 3 if error_name else 1
        self.error_name = error_name
        self.body = [version] if version is not None else []


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
    portal_probe.reset_portal_probe_cache()
    yield
    portal_probe.reset_portal_probe_cache()


@pytest.mark.parametrize(
    ("version", "pipewire_serial", "persist_mode", "source_type"),
    [
        (1, False, False, False),
        (2, False, False, False),
        (3, False, False, True),
        (4, False, True, True),
        (5, False, True, True),
        (6, True, True, True),
    ],
)
def test_portal_version_capabilities(
    version: int,
    pipewire_serial: bool,
    persist_mode: bool,
    source_type: bool,
    monkeypatch,
) -> None:
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda: _FakeBus(version))

    assert portal_probe.get_portal_version(force_refresh=True) == version
    assert portal_probe.supports_pipewire_serial() is pipewire_serial
    assert portal_probe.supports_persist_mode() is persist_mode
    assert portal_probe.supports_source_type() is source_type


def test_portal_get_version_message_shape(monkeypatch) -> None:
    bus = _FakeBus(6)
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda: bus)

    portal_probe.get_portal_version(force_refresh=True)

    message = bus.last_message
    assert message.destination == "org.freedesktop.portal.Desktop"
    assert message.path == "/org/freedesktop/portal/desktop"
    assert message.interface == "org.freedesktop.portal.ScreenCast"
    assert message.member == "GetVersion"
    assert message.signature == ""
    assert message.body == []


def test_portal_unknown_version_logs_warning(monkeypatch, caplog) -> None:
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda: _FakeBus(7))
    assert portal_probe.get_portal_version(force_refresh=True) == 7
    assert any("newer than tested range" in record.message for record in caplog.records)


def test_portal_probe_returns_zero_when_unavailable(monkeypatch) -> None:
    class _ErrorBus:
        async def connect(self):
            return self

        async def call(self, _message):
            return _FakeReply(error_name="org.freedesktop.DBus.Error.ServiceUnknown")

    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda: _ErrorBus())
    assert portal_probe.get_portal_version(force_refresh=True) == 0
    assert portal_probe.get_portal_capabilities() == set()


def test_portal_probe_works_with_running_event_loop(monkeypatch) -> None:
    monkeypatch.setattr("dbus_next.aio.MessageBus", lambda: _FakeBus(5))

    async def _runner() -> int:
        return portal_probe.get_portal_version(force_refresh=True)

    assert asyncio.run(_runner()) == 5
