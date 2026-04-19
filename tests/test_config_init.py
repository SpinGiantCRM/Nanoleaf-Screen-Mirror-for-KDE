from __future__ import annotations

from pathlib import Path

import pytest

from nanoleaf_sync.config.store import ConfigManager, mode_config


def test_mode_config_presets() -> None:
    diagnostic = mode_config("diagnostic")
    assert diagnostic.use_mock_capture is True

    full_real = mode_config("full-real")
    assert full_real.use_mock_capture is False
    assert full_real.prefer_backend == "auto"
    assert full_real.device_vid == 0x37FA


def test_mode_config_rejects_empty_mode() -> None:
    with pytest.raises(ValueError, match="mode cannot be empty"):
        mode_config("")
    with pytest.raises(ValueError, match="mode cannot be empty"):
        mode_config("   ")


def test_initialize_respects_force_flag(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    mgr = ConfigManager(path=cfg_path)

    assert mgr.initialize(mode="diagnostic") is True
    first = mgr.load()
    assert first.use_mock_capture is True

    assert mgr.initialize(mode="full-real", force=False) is False
    unchanged = mgr.load()
    assert unchanged.use_mock_capture is True

    assert mgr.initialize(mode="full-real", force=True) is True
    updated = mgr.load()
    assert updated.use_mock_capture is False
