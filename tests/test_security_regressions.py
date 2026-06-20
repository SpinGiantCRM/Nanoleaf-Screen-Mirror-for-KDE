from __future__ import annotations

from pathlib import Path

import pytest

from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.device.protocol import (
    NanoleafTLVProtocol,
    ProtocolMalformedResponseError,
    ProtocolShortReadError,
)


def test_config_store_writes_under_config_dir(tmp_path: Path) -> None:
    config_path = tmp_path / "nanoleaf-kde-sync" / "config.toml"
    mgr = ConfigManager(path=config_path)
    mgr.initialize(mode="diagnostic", force=True)
    cfg = mgr.load()
    cfg.brightness = 0.42
    mgr.save(cfg)
    assert config_path.is_file()
    assert str(config_path.resolve()).startswith(str(tmp_path.resolve()))


def test_parse_tlv_rejects_short_payload() -> None:
    with pytest.raises(ProtocolShortReadError):
        NanoleafTLVProtocol.parse_tlv(b"\x01\x02")


def test_parse_response_rejects_missing_status_byte() -> None:
    request_type = 0x03
    response_type = (request_type + 0x80) & 0xFF
    tlv = bytes([response_type, 0x00, 0x00])
    with pytest.raises(ProtocolMalformedResponseError, match="status byte"):
        NanoleafTLVProtocol.parse_response(request_type, tlv)
