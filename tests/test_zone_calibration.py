from nanoleaf_sync.ui.zone_calibration import mapping_indices, mapping_preview_text


def test_mapping_indices_uses_corner_anchored_model() -> None:
    out = mapping_indices(
        zone_count=8,
        device_zone_count=8,
        reverse_zones=False,
        corner_anchor_top_left=0,
        corner_anchor_top_right=2,
        corner_anchor_bottom_right=4,
        corner_anchor_bottom_left=6,
    )
    assert len(out) == 8


def test_mapping_preview_mentions_corner_calibration() -> None:
    text = mapping_preview_text(
        zone_count=8,
        device_zone_count=8,
        reverse_zones=False,
        corner_anchor_top_left=0,
        corner_anchor_top_right=2,
        corner_anchor_bottom_right=4,
        corner_anchor_bottom_left=6,
    )
    assert "Calibration model" in text
