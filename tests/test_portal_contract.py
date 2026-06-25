from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from nanoleaf_sync.capture.xdg_portal import XDGPortalCapture, XDGPortalError


def _node_id_from_stream_entry(stream_entry: object) -> int:
    backend = XDGPortalCapture(width=4, height=4)
    props = backend._parse_stream_properties(stream_entry)
    node_id = int(stream_entry[0])  # type: ignore[index]
    if props.get("pipewire-serial") is not None:
        node_id = int(props.get("id", node_id))
    return node_id


def test_restore_token_persists_and_reloads(tmp_path: Path) -> None:
    token_path = tmp_path / "portal_token"
    backend = XDGPortalCapture(width=4, height=4, restore_token_path=token_path)

    backend._save_restore_token("saved-token")
    assert backend._load_restore_token() == "saved-token"
    assert token_path.read_text(encoding="utf-8") == "saved-token"


def test_restore_token_clear_resets_state(tmp_path: Path) -> None:
    token_path = tmp_path / "portal_token"
    token_path.write_text("stale-token", encoding="utf-8")
    backend = XDGPortalCapture(width=4, height=4, restore_token_path=token_path)
    backend.portal_restore_token_loaded = True
    backend.portal_restore_token_accepted = True
    backend.portal_restore_token_refreshed = True
    backend.portal_restore_token_state = "submitted"  # nosec B105

    backend._clear_restore_token()

    assert not token_path.exists()
    assert backend.portal_restore_token_loaded is False
    assert backend.portal_restore_token_accepted is False
    assert backend.portal_restore_token_refreshed is False
    assert backend._load_restore_token() is None


def test_restore_token_refreshed_after_successful_start(tmp_path: Path, monkeypatch) -> None:
    token_path = tmp_path / "portal_token"
    token_path.write_text("existing-token", encoding="utf-8")
    backend = XDGPortalCapture(width=4, height=4, restore_token_path=token_path)

    async def _fake_negotiate() -> tuple[int, int]:
        backend.portal_restore_token_loaded = True
        backend.portal_restore_token_accepted = True
        backend.portal_restore_token_state = "refreshed"  # nosec B105
        backend._save_restore_token("refreshed-token")
        backend.portal_restore_token_refreshed = True
        backend.last_stream_properties = {"id": 42}
        return 9, 42

    monkeypatch.setattr(backend, "_negotiate_portal", _fake_negotiate)
    monkeypatch.setattr(backend, "_open_pipewire_stream", lambda _fd, _node_id: None)

    fd, node_id = asyncio.run(backend._negotiate_portal())

    assert fd == 9
    assert node_id == 42
    assert backend._load_restore_token() == "refreshed-token"
    assert backend.portal_restore_token_refreshed is True
    assert backend.portal_restore_token_state == "refreshed"  # nosec B105


def test_restore_token_invalidated_when_negotiation_denied(tmp_path: Path, monkeypatch) -> None:
    token_path = tmp_path / "portal_token"
    token_path.write_text("existing-token", encoding="utf-8")
    backend = XDGPortalCapture(width=4, height=4, restore_token_path=token_path)

    def _denied_sync() -> tuple[int, int]:
        restore_token = backend._load_restore_token()
        backend.portal_restore_token_loaded = bool(restore_token)
        backend.portal_restore_token_state = "submitted" if restore_token else "none"  # nosec B105
        if restore_token:
            backend._clear_restore_token()
            backend.portal_restore_token_state = "invalidated"  # nosec B105
        raise XDGPortalError("SelectSources denied (response=1).")

    monkeypatch.setattr(backend, "_negotiate_portal_sync", _denied_sync)

    with pytest.raises(XDGPortalError, match="SelectSources denied"):
        backend.initialize()

    assert not token_path.exists()
    assert backend.portal_restore_token_state == "invalidated"  # nosec B105
    assert backend.portal_restore_token_loaded is False


def test_empty_frame_recovery_reopens_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = XDGPortalCapture(width=4, height=4)
    backend._initialized = True
    backend._STREAM_RECOVER_AFTER_EMPTY = 1
    reads = iter([None, np.zeros((4, 4, 3), dtype=np.uint8)])
    recoveries = {"count": 0}

    def _read() -> np.ndarray | None:
        return next(reads, None)

    def _recover(*, reason: str) -> None:
        recoveries["count"] += 1
        backend._empty_capture_streak = 0

    monkeypatch.setattr(backend, "_read_pipewire_frame", _read)
    monkeypatch.setattr(backend, "_recover_stream", _recover)

    frame = backend.capture()

    assert frame.shape == (4, 4, 3)
    assert recoveries["count"] == 1


def test_pipewire_serial_targets_property_id_not_tuple_index() -> None:
    stream_entry = (
        77,
        {
            "id": 99,
            "pipewire-serial": 42,
            "size": {"width": 4, "height": 4},
        },
    )
    assert _node_id_from_stream_entry(stream_entry) == 99


def test_pipewire_serial_absent_uses_tuple_index() -> None:
    stream_entry = (17, {"size": {"width": 4, "height": 4}})
    assert _node_id_from_stream_entry(stream_entry) == 17


def test_suspend_resume_serial_retarget_updates_open_node(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = XDGPortalCapture(width=4, height=4)
    negotiate_calls = {"count": 0}
    open_calls: list[tuple[int, int]] = []

    def _fake_negotiate_sync() -> tuple[int, int]:
        negotiate_calls["count"] += 1
        if negotiate_calls["count"] == 1:
            backend.last_stream_properties = {"id": 99, "pipewire-serial": 42}
            return 11, 99
        backend.last_stream_properties = {"id": 200, "pipewire-serial": 55}
        return 12, 200

    def _open_pipewire_stream(fd: int, node_id: int) -> None:
        open_calls.append((fd, node_id))

    monkeypatch.setattr(backend, "_negotiate_portal_sync", _fake_negotiate_sync)
    monkeypatch.setattr(backend, "_open_pipewire_stream", _open_pipewire_stream)
    monkeypatch.setattr(backend, "_close_pipewire_stream", lambda: None)
    monkeypatch.setattr(backend, "_close_portal_session_sync", lambda: None)

    backend.initialize()
    assert open_calls == [(11, 99)]

    backend._recover_stream(reason="simulated suspend/resume")

    assert negotiate_calls["count"] == 2
    assert open_calls[-1] == (12, 200)
    assert backend.last_stream_properties.get("pipewire-serial") == 55
