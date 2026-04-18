from __future__ import annotations

import json
from pathlib import Path

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.config.store import ConfigManager


def test_config_save_validates_and_is_json_loadable(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    mgr = ConfigManager(path=cfg_path)

    cfg = AppConfig(
        fps=999,
        brightness=2.0,
        smoothing=-1.0,
        zone_sampling_stride=-4,
        zones=[
            ZoneConfig(x=-0.5, y=0.1, w=0.5, h=0.5),
            ZoneConfig(x=0.1, y=0.1, w=0.0, h=0.5),
        ],
        device_vid=1,
        device_pid=2,
        use_mock_device=True,
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
    data = json.loads(cfg_path.read_text(encoding="utf-8"))

    assert data["brightness"] == 1.0
    assert data["smoothing"] == 0.0
    assert data["fps"] == 120
    assert data["zone_sampling_stride"] == 1
    assert data["device_zone_count"] == 0
    assert data["max_consecutive_errors"] >= 1
    assert data["reinit_backoff_ms"] >= 0
    assert data["status_log_interval_s"] >= 0.5
    assert len(data["zones"]) == 1


def test_config_load_normalizes_backend(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"prefer_backend": "KWIN_DBUS"}), encoding="utf-8")

    cfg = ConfigManager(path=cfg_path).load()
    assert cfg.prefer_backend == "kwin-dbus"


def test_config_load_invalid_backend_falls_back_to_default(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"prefer_backend": "totally-unknown-backend"}),
        encoding="utf-8",
    )

    cfg = ConfigManager(path=cfg_path).load()
    assert cfg.prefer_backend == AppConfig.prefer_backend


def test_config_load_parses_bool_strings(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "use_mock_device": "false",
                "use_mock_capture": "0",
                "reverse_zones": "off",
                "verbose": "false",
            }
        ),
        encoding="utf-8",
    )

    cfg = ConfigManager(path=cfg_path).load()

    assert cfg.use_mock_device is False
    assert cfg.use_mock_capture is False
    assert cfg.reverse_zones is False
    assert cfg.verbose is False
