from __future__ import annotations

from pathlib import Path

from nanoleaf_sync.config.store import ConfigManager, mode_config


def test_mode_config_presets() -> None:
    full_mock = mode_config("full-mock")
    assert full_mock.use_mock_capture is True
    assert full_mock.use_mock_device is True

    capture_real = mode_config("capture-real")
    assert capture_real.use_mock_capture is False
    assert capture_real.use_mock_device is True
    assert capture_real.prefer_backend == "kwin-dbus"

    full_real = mode_config("full-real")
    assert full_real.use_mock_capture is False
    assert full_real.use_mock_device is False
    assert full_real.device_vid == 0x37FA


def test_initialize_respects_force_flag(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    mgr = ConfigManager(path=cfg_path)

    assert mgr.initialize(mode="full-mock") is True
    first = mgr.load()
    assert first.use_mock_capture is True

    assert mgr.initialize(mode="full-real", force=False) is False
    unchanged = mgr.load()
    assert unchanged.use_mock_device is True

    assert mgr.initialize(mode="full-real", force=True) is True
    updated = mgr.load()
    assert updated.use_mock_device is False
