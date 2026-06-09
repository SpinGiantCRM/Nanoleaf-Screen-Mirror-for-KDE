"""Tests for ConfigManager save/load edge cases, file locking, and error paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.config.normalize import validate_config
from nanoleaf_sync.config.store import ConfigManager, mode_config


def test_mode_config_full_real() -> None:
    cfg = mode_config("full-real")
    assert cfg.use_mock_capture is False
    assert cfg.prefer_backend == "auto"


def test_mode_config_real_alias() -> None:
    cfg = mode_config("real")
    assert cfg.use_mock_capture is False


def test_mode_config_diagnostic() -> None:
    cfg = mode_config("diagnostic")
    assert cfg.use_mock_capture is True


def test_mode_config_mock_alias() -> None:
    cfg = mode_config("mock")
    assert cfg.use_mock_capture is True


def test_mode_config_empty_raises() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        mode_config("")


def test_mode_config_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported mode"):
        mode_config("bogus")


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "config.toml"
    mgr = ConfigManager(path=path)
    cfg = validate_config(AppConfig())
    mgr.save(cfg)
    assert path.exists()


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path=path)
    cfg = validate_config(AppConfig(device_zone_count=48))
    mgr.save(cfg)

    mgr2 = ConfigManager(path=path)
    loaded = mgr2.load()
    assert loaded.device_zone_count == 48


def test_load_returns_default_when_no_file(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.toml"
    mgr = ConfigManager(path=path)
    cfg = mgr.load()
    assert cfg.device_zone_count == 0


def test_load_corrupt_toml_returns_default(tmp_path: Path, caplog) -> None:
    path = tmp_path / "config.toml"
    path.write_text("this is not valid toml {{{", encoding="utf-8")
    mgr = ConfigManager(path=path)
    with caplog.at_level("WARNING", logger="nanoleaf_sync.config.store"):
        cfg = mgr.load()
    assert isinstance(cfg, AppConfig)
    assert any("corrupted" in record.message.lower() for record in caplog.records)


def test_load_empty_file_returns_default(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")
    mgr = ConfigManager(path=path)
    cfg = mgr.load()
    assert isinstance(cfg, AppConfig)


def test_load_non_dict_toml_returns_default(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("key = [1, 2, 3]\n", encoding="utf-8")
    mgr = ConfigManager(path=path)
    cfg = mgr.load()
    assert isinstance(cfg, AppConfig)


def test_load_invalid_unicode_returns_default(tmp_path: Path, caplog) -> None:
    path = tmp_path / "config.toml"
    # Write binary garbage that will fail UTF-8 decode
    path.write_bytes(b"\xff\xfe\x00\x00")
    mgr = ConfigManager(path=path)
    with caplog.at_level("WARNING", logger="nanoleaf_sync.config.store"):
        cfg = mgr.load()
    assert isinstance(cfg, AppConfig)
    assert any("unreadable" in record.message.lower() for record in caplog.records)


def test_initialize_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path=path)
    result = mgr.initialize(mode="full-real")
    assert result is True
    assert path.exists()


def test_initialize_returns_false_when_exists(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("device_zone_count = 10\n", encoding="utf-8")
    mgr = ConfigManager(path=path)
    result = mgr.initialize(mode="full-real")
    assert result is False


def test_initialize_with_force_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("device_zone_count = 10\n", encoding="utf-8")
    mgr = ConfigManager(path=path)
    result = mgr.initialize(mode="full-real", force=True)
    assert result is True
    cfg = mgr.load()
    assert cfg.use_mock_capture is False


def test_exists(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path=path)
    assert mgr.exists() is False
    path.write_text("device_zone_count = 10\n", encoding="utf-8")
    assert mgr.exists() is True


def test_reset_auto_probe_cache(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path=path)
    mgr.save(
        validate_config(
            AppConfig(
                auto_selected_backend="kwin-dbus",
                auto_probe_signature="old-sig",
                auto_probe_timestamp="2024-01-01",
            )
        )
    )
    updated = mgr.reset_auto_probe_cache()
    assert updated.auto_selected_backend == ""
    assert updated.auto_probe_signature == ""
    assert updated.auto_probe_timestamp == ""


def test_reset_calibration_only(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path=path)
    mgr.save(
        validate_config(
            AppConfig(
                calibration=CalibrationConfig(device_zone_count=48),
                reverse_zones=True,
                corner_anchor_top_left=5,
            )
        )
    )
    updated = mgr.reset_calibration_only()
    # Calibration block fields are reset to defaults
    assert updated.calibration.device_zone_count == 0
    assert updated.reverse_zones is False
    # Corner anchors reset to -1
    assert updated.corner_anchor_top_left == -1
    assert updated.corner_anchor_top_right == -1
    assert updated.corner_anchor_bottom_right == -1
    assert updated.corner_anchor_bottom_left == -1
    # Calibration schema version is set
    assert updated.calibration_schema_version == 1


def test_reset_diagnostics_cache_only(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path=path)
    mgr.save(
        validate_config(
            AppConfig(
                auto_selected_backend="kwin-dbus",
                auto_probe_signature="sig",
                wizard_in_progress_state='{"flow_index":1}',
            )
        )
    )
    updated = mgr.reset_diagnostics_cache_only()
    assert updated.auto_selected_backend == ""
    assert updated.auto_probe_signature == ""
    assert updated.wizard_in_progress_state == ""


def test_reset_all_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path=path)
    mgr.save(validate_config(AppConfig(device_zone_count=48)))
    updated = mgr.reset_all_config()
    assert updated.device_zone_count == 0


def test_save_updates_internal_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path=path)
    cfg = validate_config(AppConfig(device_zone_count=12))
    mgr.save(cfg)
    assert mgr._config is not None
    assert mgr._config.device_zone_count == 12


def test_load_reads_saved_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path=path)
    mgr.save(validate_config(AppConfig(device_zone_count=42)))
    mgr2 = ConfigManager(path=path)
    loaded = mgr2.load()
    assert loaded.device_zone_count == 42


def test_save_lock_is_released_after_save(tmp_path: Path) -> None:
    """Ensure the lock file's advisory lock is released after save (another
    process can acquire it)."""
    import fcntl
    import os

    path = tmp_path / "config.toml"
    lock_path = tmp_path / "config.toml.lock"
    mgr = ConfigManager(path=path)
    mgr.save(validate_config(AppConfig()))
    # The lock file may persist on disk (it's a sentinel for fcntl.flock)
    # but the advisory lock must be released so another process can acquire it.
    if lock_path.exists():
        fd = os.open(str(lock_path), os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Lock acquired successfully — the previous lock was released
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def test_save_overwrite_existing(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path=path)
    mgr.save(validate_config(AppConfig(device_zone_count=10)))
    mgr.save(validate_config(AppConfig(device_zone_count=20)))
    loaded = mgr.load()
    assert loaded.device_zone_count == 20
