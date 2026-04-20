from __future__ import annotations

import json
from pathlib import Path

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.config.store import ConfigManager, _dump_toml


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


def test_config_persists_start_on_launch_and_color_mode(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    mgr = ConfigManager(path=cfg_path)

    cfg = AppConfig(start_on_launch=True, color_mode="dynamic")
    mgr.save(cfg)
    loaded = mgr.load()

    assert loaded.start_on_launch is True
    assert loaded.color_mode == "dynamic"


def test_config_persists_display_wizard_fields(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    mgr = ConfigManager(path=cfg_path)

    cfg = AppConfig(wizard_completed=True, hdr_enabled=True, color_mode="hyper")
    mgr.save(cfg)
    loaded = mgr.load()

    assert loaded.wizard_completed is True
    assert loaded.hdr_enabled is True
    assert loaded.color_mode == "hyper"


def test_config_persists_corner_refinement_settings(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    mgr = ConfigManager(path=cfg_path)

    cfg = AppConfig(
        corner_offsets_enabled=True,
        corner_zone_offsets=[2, -1, 3, 0, 99],
    )
    mgr.save(cfg)
    loaded = mgr.load()

    assert loaded.corner_offsets_enabled is True
    assert loaded.corner_zone_offsets == [2, -1, 3, 0]


def test_config_normalizes_sdr_boost_fields(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "compositor_hdr_mode = true\nsdr_boost_nits = 5000\n",
        encoding="utf-8",
    )

    cfg = ConfigManager(path=cfg_path).load()
    assert cfg.compositor_hdr_mode is True
    assert cfg.sdr_boost_nits == 1000.0


def test_config_normalizes_boolean_fields_consistently(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "\n".join(
            [
                'wizard_completed = "yes"',
                "hdr_enabled = 0",
                "start_on_launch = 1",
                "use_mock_capture = 0",
                'compositor_hdr_mode = "on"',
                "reverse_zones = 1",
                "verbose = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = ConfigManager(path=cfg_path).load()
    assert cfg.wizard_completed is True
    assert cfg.hdr_enabled is False
    assert cfg.start_on_launch is True
    assert cfg.use_mock_capture is False
    assert cfg.compositor_hdr_mode is True
    assert cfg.reverse_zones is True
    assert cfg.verbose is False


def test_dump_toml_handles_mixed_list_types() -> None:
    encoded = _dump_toml({"mixed": [1, "two", True, 3.5], "zones": []})
    assert "mixed" in encoded
    assert '"two"' in encoded
    assert "true" in encoded
    assert "3.5" in encoded


def test_config_load_normalizes_auto_probe_fields(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "\n".join(
            [
                'auto_probe_policy = "each_boot"',
                'auto_selected_backend = "KWIN_DBUS"',
                "auto_probe_signature = 12345",
                "auto_probe_timestamp = 67890",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cfg = ConfigManager(path=cfg_path).load()
    assert cfg.auto_probe_policy == "each-boot"
    assert cfg.auto_selected_backend == "kwin-dbus"
    assert cfg.auto_probe_signature == "12345"
    assert cfg.auto_probe_timestamp == "67890"


def test_config_load_normalizes_auto_probe_policy_variants(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('auto_probe_policy = "FIRST_RUN"\n', encoding="utf-8")

    cfg = ConfigManager(path=cfg_path).load()
    assert cfg.auto_probe_policy == "first-run"


def test_config_load_invalid_auto_probe_policy_falls_back_to_default(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('auto_probe_policy = "definitely-not-valid"\n', encoding="utf-8")

    cfg = ConfigManager(path=cfg_path).load()
    assert cfg.auto_probe_policy == AppConfig.auto_probe_policy


def test_config_load_unrecognized_color_mode_warns_and_falls_back(tmp_path: Path, caplog) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('color_mode = "vibrant"\n', encoding="utf-8")

    with caplog.at_level("WARNING"):
        cfg = ConfigManager(path=cfg_path).load()

    assert cfg.color_mode == AppConfig.color_mode
    assert "Unrecognized color_mode" in caplog.text


def test_config_reset_auto_probe_cache(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    mgr = ConfigManager(path=cfg_path)
    mgr.save(
        AppConfig(
            auto_selected_backend="kwin-dbus",
            auto_probe_signature="abc",
            auto_probe_timestamp="2026-01-01T00:00:00+00:00",
        )
    )

    updated = mgr.reset_auto_probe_cache()
    assert updated.auto_selected_backend == ""
    assert updated.auto_probe_signature == ""
    assert updated.auto_probe_timestamp == ""
