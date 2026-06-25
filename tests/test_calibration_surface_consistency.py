from dataclasses import fields

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig


def test_model_exposes_corner_anchor_fields() -> None:
    calibration_names = {field.name for field in fields(CalibrationConfig)}
    app_names = {field.name for field in fields(AppConfig)}
    for name in (
        "corner_anchor_top_left",
        "corner_anchor_top_right",
        "corner_anchor_bottom_right",
        "corner_anchor_bottom_left",
    ):
        assert name in calibration_names
        assert name in app_names

    cfg = AppConfig(
        corner_anchor_top_left=1,
        corner_anchor_top_right=2,
        corner_anchor_bottom_right=3,
        corner_anchor_bottom_left=4,
    )
    assert cfg.corner_anchor_top_left == 1
    assert cfg.corner_anchor_top_right == 2
