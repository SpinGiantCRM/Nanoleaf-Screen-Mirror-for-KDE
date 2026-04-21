from __future__ import annotations

from pathlib import Path

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.runtime.anchor_calibration import derive_anchor_zone_map, validate_corner_anchors
from nanoleaf_sync.ui.zone_calibration import mapping_indices, mapping_preview_text


def test_derives_full_mapping_from_valid_corner_anchors() -> None:
    mapping = derive_anchor_zone_map(
        zone_count=12,
        device_zone_count=12,
        anchors={"top_left": 0, "top_right": 3, "bottom_right": 6, "bottom_left": 9},
    )
    assert len(mapping.explicit_zone_map) == 12
    assert mapping.explicit_zone_map[0] == 0


def test_anchor_derivation_supports_clockwise_and_counter_clockwise() -> None:
    cw = derive_anchor_zone_map(
        zone_count=12,
        device_zone_count=12,
        anchors={"top_left": 0, "top_right": 3, "bottom_right": 6, "bottom_left": 9},
    )
    ccw = derive_anchor_zone_map(
        zone_count=12,
        device_zone_count=12,
        anchors={"top_left": 0, "top_right": 9, "bottom_right": 6, "bottom_left": 3},
    )
    assert cw.direction == "clockwise"
    assert ccw.direction == "counter-clockwise"


def test_anchor_validation_rejects_duplicates_and_incomplete_assignments() -> None:
    duplicate = validate_corner_anchors(
        anchors={"top_left": 1, "top_right": 1, "bottom_right": 4, "bottom_left": 7},
        device_zone_count=8,
    )
    incomplete = validate_corner_anchors(
        anchors={"top_left": 1, "top_right": None, "bottom_right": 4, "bottom_left": 7},
        device_zone_count=8,
    )
    assert duplicate.valid is False
    assert incomplete.valid is False


def test_config_round_trip_preserves_corner_anchors(tmp_path: Path) -> None:
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
    assert loaded.corner_anchor_bottom_left == 9
    assert len(loaded.explicit_zone_map) == 12


def test_preview_output_matches_runtime_mapping() -> None:
    cfg = AppConfig(
        device_zone_count=12,
        corner_anchor_top_left=0,
        corner_anchor_top_right=3,
        corner_anchor_bottom_right=6,
        corner_anchor_bottom_left=9,
    )
    idx = mapping_indices(
        zone_count=12,
        device_zone_count=12,
        zone_offset=0,
        reverse_zones=False,
        corner_anchor_top_left=cfg.corner_anchor_top_left,
        corner_anchor_top_right=cfg.corner_anchor_top_right,
        corner_anchor_bottom_right=cfg.corner_anchor_bottom_right,
        corner_anchor_bottom_left=cfg.corner_anchor_bottom_left,
    )
    assert idx[0] == 0
    preview = mapping_preview_text(
        zone_count=12,
        device_zone_count=12,
        zone_offset=0,
        reverse_zones=False,
        corner_anchor_top_left=0,
        corner_anchor_top_right=3,
        corner_anchor_bottom_right=6,
        corner_anchor_bottom_left=9,
    )
    assert "Corner anchors" in preview


def test_backward_compatibility_old_configs_do_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("zone_offset = 2\nreverse_zones = true\n", encoding="utf-8")
    cfg = ConfigManager(path=path).load()
    assert cfg.zone_offset == 2
