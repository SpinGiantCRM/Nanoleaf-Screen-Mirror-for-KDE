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
        zones=[
            ZoneConfig(x=-0.5, y=0.1, w=0.5, h=0.5),  # x will clamp
            ZoneConfig(x=0.1, y=0.1, w=0.0, h=0.5),  # w<=0 => dropped
        ],
        device_vid=1,
        device_pid=2,
        use_mock_device=True,
        use_mock_capture=True,
        allow_capture_fallback=False,
        device_zone_count=-5,  # clamp to 0
        zone_offset=123,
        reverse_zones=True,
        explicit_zone_map=[0, 1, 2],
        hdr_transfer="pq",
        hdr_primaries="bt2020",
        hdr_max_nits=999999.0,  # clamp
        max_consecutive_errors=0,  # clamp
        reinit_backoff_ms=-1,  # clamp
        status_log_interval_s=0.1,  # clamp
        replay_frames_path="/tmp/replay.npz",
        verbose=True,
    )

    mgr.save(cfg)

    raw = cfg_path.read_text(encoding="utf-8")
    data = json.loads(raw)

    assert data["brightness"] == 1.0  # clamped
    assert data["smoothing"] == 0.0  # clamped
    assert data["fps"] == 60  # clamped
    assert data["device_zone_count"] == 0  # clamped
    assert data["allow_capture_fallback"] is False
    assert data["hdr_max_nits"] <= 10_000.0
    assert data["max_consecutive_errors"] >= 1
    assert data["reinit_backoff_ms"] >= 0
    assert data["status_log_interval_s"] >= 0.5

    # Zones: second zone should be dropped due to w==0.
    assert len(data["zones"]) == 1


def test_config_load_recovers_from_corruption(tmp_path: Path) -> None:
    cfg_path = tmp_path / "bad.json"
    cfg_path.write_text("{ this is not json", encoding="utf-8")

    cfg = ConfigManager(path=cfg_path).load()
    # Should fall back to defaults rather than raising.
    assert isinstance(cfg, AppConfig)


def test_config_load_recovers_from_non_object_json(tmp_path: Path) -> None:
    cfg_path = tmp_path / "bad-shape.json"
    cfg_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    cfg = ConfigManager(path=cfg_path).load()

    assert isinstance(cfg, AppConfig)


def test_config_load_normalizes_enum_like_fields(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "prefer_backend": "KWIN_DBUS",
                "hdr_transfer": "PQ",
                "hdr_primaries": "BT2020",
            }
        ),
        encoding="utf-8",
    )

    cfg = ConfigManager(path=cfg_path).load()

    assert cfg.prefer_backend == "kwin-dbus"
    assert cfg.hdr_transfer == "pq"
    assert cfg.hdr_primaries == "bt2020"


def test_config_load_invalid_enum_values_fall_back_to_defaults(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "prefer_backend": "totally-unknown-backend",
                "hdr_transfer": "gamma22",
                "hdr_primaries": "p3",
            }
        ),
        encoding="utf-8",
    )

    cfg = ConfigManager(path=cfg_path).load()

    assert cfg.prefer_backend == AppConfig.prefer_backend
    assert cfg.hdr_transfer == AppConfig.hdr_transfer
    assert cfg.hdr_primaries == AppConfig.hdr_primaries


def test_config_load_parses_bool_strings_without_truthiness_bug(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "use_mock_device": "false",
                "use_mock_capture": "0",
                "allow_capture_fallback": "no",
                "reverse_zones": "off",
                "verbose": "false",
            }
        ),
        encoding="utf-8",
    )

    cfg = ConfigManager(path=cfg_path).load()

    assert cfg.use_mock_device is False
    assert cfg.use_mock_capture is False
    assert cfg.allow_capture_fallback is False
    assert cfg.reverse_zones is False
    assert cfg.verbose is False


def test_config_load_tolerates_invalid_scalar_and_list_types(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "fps": "not-an-int",
                "brightness": "not-a-float",
                "device_vid": {"oops": 1},
                "max_consecutive_errors": [],
                "explicit_zone_map": "not-a-list",
                "zones": {"x": 1, "y": 2},
            }
        ),
        encoding="utf-8",
    )

    cfg = ConfigManager(path=cfg_path).load()

    assert cfg.fps == AppConfig.fps
    assert cfg.brightness == AppConfig.brightness
    assert cfg.device_vid == AppConfig.device_vid
    assert cfg.max_consecutive_errors == AppConfig.max_consecutive_errors
    assert cfg.explicit_zone_map == []
    assert cfg.zones == []
