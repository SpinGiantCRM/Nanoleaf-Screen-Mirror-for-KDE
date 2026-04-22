from __future__ import annotations

from pathlib import Path

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.ui.zone_calibration import mapping_indices, mapping_preview_text


def test_config_round_trip_preserves_legacy_corner_anchor_fields(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path=path)
    cfg = AppConfig(
        device_zone_count=12,
        corner_anchor_top_left=0,
        corner_anchor_top_right=3,
        corner_anchor_bottom_right=6,
        corner_anchor_bottom_left=9,
    )
    mgr.save(cfg)
    loaded = mgr.load()
    assert loaded.corner_anchor_top_left == 0
    assert loaded.corner_anchor_top_right == 3
    assert loaded.corner_anchor_bottom_right == 6
    assert loaded.corner_anchor_bottom_left == 9
    assert len(loaded.explicit_zone_map) == 0


def test_corner_anchored_model_uses_assigned_anchors_deterministically() -> None:
    baseline = mapping_indices(
        zone_count=12,
        device_zone_count=12,
        zone_offset=0,
        reverse_zones=False,
        corner_anchor_top_left=None,
        corner_anchor_top_right=None,
        corner_anchor_bottom_right=None,
        corner_anchor_bottom_left=None,
    )
    idx = mapping_indices(
        zone_count=12,
        device_zone_count=12,
        zone_offset=0,
        reverse_zones=False,
        corner_anchor_top_left=2,
        corner_anchor_top_right=5,
        corner_anchor_bottom_right=8,
        corner_anchor_bottom_left=11,
        calibration_model="corner_anchored",
    )
    assert idx != baseline
    preview = mapping_preview_text(
        zone_count=12,
        device_zone_count=12,
        zone_offset=0,
        reverse_zones=False,
        corner_anchor_top_left=2,
        corner_anchor_top_right=5,
        corner_anchor_bottom_right=8,
        corner_anchor_bottom_left=11,
        calibration_model="corner_anchored",
    )
    assert "Calibration model: corner anchored" in preview
    assert "Offset:" not in preview
    assert "Anchors (TL/TR/BR/BL): 2, 5, 8, 11" in preview


def test_backward_compatibility_old_configs_do_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("zone_offset = 2\nreverse_zones = true\n", encoding="utf-8")
    cfg = ConfigManager(path=path).load()
    assert cfg.zone_offset == 2
    assert cfg.calibration.zone_offset == 2
    assert cfg.calibration.reverse_zones is True


def test_backward_compatibility_with_new_normalized_calibration_block(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                "calibration_schema_version = 2",
                "[calibration]",
                "calibration_model = \"corner_anchored\"",
                "normalized_corner_anchors = [0, 3, 6, 9]",
                "normalized_zone_offset = 1",
                "normalized_reverse_zones = true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = ConfigManager(path=path).load()
    assert cfg.calibration_schema_version == 2
    assert cfg.calibration.calibration_model == "corner_anchored"
    assert cfg.calibration.normalized_corner_anchors == [0, 3, 6, 9]
    assert cfg.calibration.normalized_zone_offset == 1
    assert cfg.calibration.normalized_reverse_zones is True


def test_corner_anchored_config_round_trip_preserves_validated_anchor_assignments(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    mgr = ConfigManager(path=path)
    cfg = AppConfig(
        device_zone_count=12,
        calibration_model="corner_anchored",
        corner_anchor_top_left=1,
        corner_anchor_top_right=4,
        corner_anchor_bottom_right=7,
        corner_anchor_bottom_left=10,
    )
    cfg.calibration.calibration_model = "corner_anchored"
    cfg.calibration.device_zone_count = 12
    cfg.calibration.corner_anchor_top_left = 1
    cfg.calibration.corner_anchor_top_right = 4
    cfg.calibration.corner_anchor_bottom_right = 7
    cfg.calibration.corner_anchor_bottom_left = 10
    mgr.save(cfg)

    loaded = mgr.load()
    assert loaded.calibration.calibration_model == "corner_anchored"
    assert loaded.calibration.corner_anchor_top_left == 1
    assert loaded.calibration.corner_anchor_top_right == 4
    assert loaded.calibration.corner_anchor_bottom_right == 7
    assert loaded.calibration.corner_anchor_bottom_left == 10
    assert loaded.corner_anchor_top_left == 1
    assert loaded.corner_anchor_top_right == 4
    assert loaded.corner_anchor_bottom_right == 7
    assert loaded.corner_anchor_bottom_left == 10
