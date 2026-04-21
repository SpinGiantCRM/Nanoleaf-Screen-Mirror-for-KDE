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


def test_preview_output_ignores_corner_anchors() -> None:
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
    )
    assert idx == baseline
    preview = mapping_preview_text(
        zone_count=12,
        device_zone_count=12,
        zone_offset=0,
        reverse_zones=False,
        corner_anchor_top_left=2,
        corner_anchor_top_right=5,
        corner_anchor_bottom_right=8,
        corner_anchor_bottom_left=11,
    )
    assert "legacy corner anchors are ignored" in preview


def test_backward_compatibility_old_configs_do_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("zone_offset = 2\nreverse_zones = true\n", encoding="utf-8")
    cfg = ConfigManager(path=path).load()
    assert cfg.zone_offset == 2
