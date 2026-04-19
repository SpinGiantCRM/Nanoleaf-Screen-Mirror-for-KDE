from __future__ import annotations

import json
from pathlib import Path

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.config.store import ConfigManager


def test_config_save_validates_and_is_toml_loadable(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    mgr = ConfigManager(path=cfg_path)

    cfg = AppConfig(
        fps=999,
        brightness=2.0,
        smoothing=-1.0,
        smoothing_speed=9.0,
        zone_sampling_stride=-4,
        led_gamma=5.0,
        zones=[
            ZoneConfig(x=-0.5, y=0.1, w=0.5, h=0.5),
            ZoneConfig(x=0.1, y=0.1, w=0.0, h=0.5),
        ],
        device_vid=1,
        device_pid=2,
        use_mock_capture=True,
        device_zone_count=-5,
        zone_offset=123,
        reverse_zones=True,
        explicit_zone_map=[0, 1, 2],
        max_consecutive_errors=0,
        reinit_backoff_ms=-1,
        status_log_interval_s=0.1,
        verbose=True,
    )

    mgr.save(cfg)
    loaded = mgr.load()

    assert loaded.brightness == 1.0
    assert loaded.smoothing == 0.0
    assert loaded.smoothing_speed == 4.0
    assert loaded.fps == 120
    assert loaded.zone_sampling_stride == 1
    assert loaded.led_gamma == 4.0
    assert loaded.device_zone_count == 0
    assert loaded.max_consecutive_errors >= 1
    assert loaded.reinit_backoff_ms >= 0
    assert loaded.status_log_interval_s >= 0.5
    assert len(loaded.zones) == 1
    assert loaded.zones[0] == ZoneConfig(x=0.0, y=0.1, w=0.5, h=0.5)


def test_config_load_normalizes_backend(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("prefer_backend = \"KWIN_DBUS\"\n", encoding="utf-8")

    cfg = ConfigManager(path=cfg_path).load()
    assert cfg.prefer_backend == "kwin-dbus"


def test_config_load_normalizes_portal_backend_alias(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("prefer_backend = \"portal\"\n", encoding="utf-8")

    cfg = ConfigManager(path=cfg_path).load()
    assert cfg.prefer_backend == "xdg-portal"


def test_config_load_invalid_backend_falls_back_to_default(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("prefer_backend = \"totally-unknown-backend\"\n", encoding="utf-8")

    cfg = ConfigManager(path=cfg_path).load()
    assert cfg.prefer_backend == AppConfig.prefer_backend


def test_config_load_normalizes_hdr_fields(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "hdr_transfer = \"ST2084\"\nhdr_primaries = \"sRGB\"\nhdr_max_nits = 12000\n",
        encoding="utf-8",
    )

    cfg = ConfigManager(path=cfg_path).load()
    assert cfg.hdr_transfer == "pq"
    assert cfg.hdr_primaries == "bt709"
    assert cfg.hdr_max_nits == 10000.0


def test_config_migrates_legacy_json_to_toml(tmp_path: Path) -> None:
    json_path = tmp_path / "config.json"
    json_path.write_text(json.dumps({"fps": 55, "zone_preset": "horizontal"}), encoding="utf-8")

    cfg = ConfigManager(path=tmp_path / "config.toml").load()
    assert cfg.fps == 55
    assert cfg.zone_preset == "horizontal"
    assert (tmp_path / "config.toml").exists()
    assert (tmp_path / "config.json.bak").exists()
