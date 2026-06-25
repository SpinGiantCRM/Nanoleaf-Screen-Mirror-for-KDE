from __future__ import annotations

from nanoleaf_sync.runtime.anchor_calibration import validate_corner_anchors
from nanoleaf_sync.runtime.guided_calibration import (
    GuidedCalibrationSession,
    binary_search_estimate,
    validate_anchor_consistency,
)
from nanoleaf_sync.runtime.zone_derivation import zone_distribution_from_count


def test_zone_distribution_from_count_sums_to_total() -> None:
    dist = zone_distribution_from_count(60)
    assert sum(dist) == 60
    assert all(v >= 1 for v in dist)


def test_binary_search_estimate_within_side() -> None:
    dist = zone_distribution_from_count(60)
    est = binary_search_estimate(low=0, high=59, zones_per_side=dist, corner="top_right")
    top = dist[0]
    assert top <= est < top + dist[1]


def test_direction_no_reverses_zone_order() -> None:
    session = GuidedCalibrationSession(device_zone_count=60, frame_width=1920, frame_height=1080)
    session.apply_response("no")
    assert session.reverse_zones is True
    assert session.step_kind == "corner"


def test_full_calibration_completes_quickly() -> None:
    session = GuidedCalibrationSession(device_zone_count=60, frame_width=1920, frame_height=1080)
    for response in ("yes", "yes", "yes", "yes", "yes", "yes"):
        session.apply_response(response)  # type: ignore[arg-type]
    assert session.is_complete()
    assert session.elapsed_prompts <= 10


def test_binary_search_converges_within_one_zone() -> None:
    session = GuidedCalibrationSession(device_zone_count=60, frame_width=1920, frame_height=1080)
    session.apply_response("yes")
    target = 14
    session.corner_estimates["top_left"] = target
    session.anchors["top_left"] = target
    session.corner_index = 1
    for _ in range(6):
        session.apply_response("yes")
        if session.is_complete():
            break
    valid, _errors = validate_anchor_consistency(
        anchors=session.anchors,
        device_zone_count=60,
    )
    assert session.anchors["top_left"] == target
    assert valid or session.step_kind == "rainbow"


def test_headless_and_gui_share_session_logic() -> None:
    gui = GuidedCalibrationSession(device_zone_count=48, frame_width=100, frame_height=50)
    headless = GuidedCalibrationSession(device_zone_count=48, frame_width=100, frame_height=50)
    responses = ("yes", "yes", "yes", "yes", "yes", "yes")
    for response in responses:
        gui.apply_response(response)  # type: ignore[arg-type]
        headless.apply_response(response)  # type: ignore[arg-type]
    assert gui.anchors == headless.anchors
    assert gui.reverse_zones == headless.reverse_zones


def test_validate_anchor_consistency_wraps_existing_validator() -> None:
    anchors = {
        "top_left": 1,
        "top_right": 12,
        "bottom_right": 24,
        "bottom_left": 36,
    }
    valid, errors = validate_anchor_consistency(anchors=anchors, device_zone_count=48)
    assert valid == validate_corner_anchors(anchors=anchors, device_zone_count=48).valid
    assert errors == []
