from __future__ import annotations

import numpy as np

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.diagnostics_exports import latency_breakdown_lines
from nanoleaf_sync.runtime.startup import apply_process_priority
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.runtime.zones import (
    _AUTO_ENGINE_CACHE,
    _cached_sampling_plan,
    _zone_means_legacy,
    _zone_means_optimized,
    _edge_localized_weights,
    zone_colors_array,
)
from nanoleaf_sync.runtime.srgb import linear01_to_srgb_u8, srgb_u8_to_linear01


def _latency_status(
    *, actual_work_ms: float, hid_write_ms: float, target_fps: float = 120.0
) -> dict:
    return {
        "configured_priority_mode": "high",
        "effective_nice_value": 0,
        "priority_apply_status": "failed",
        "priority_apply_error": "Permission denied",
        "latency_measurement": {
            "live_mirroring_only": True,
            "target_fps": target_fps,
            "effective_output_fps": 55.0,
            "fps_cap": target_fps,
            "fps_cap_reason": "UI FPS control cap",
            "dropped_or_skipped_frames": 3,
            "stages": {
                "loop_gap_ms": {
                    "available": True,
                    "median_ms": actual_work_ms,
                    "p95_ms": actual_work_ms + 0.6,
                    "max_ms": actual_work_ms + 1.2,
                    "sample_count": 80,
                },
                "pacing_wait_ms": {
                    "available": False,
                    "median_ms": 0.0,
                    "p95_ms": 0.0,
                    "max_ms": 0.0,
                    "sample_count": 0,
                },
                "actual_work_ms": {
                    "available": True,
                    "median_ms": actual_work_ms,
                    "p95_ms": actual_work_ms + 0.5,
                    "max_ms": actual_work_ms + 1.0,
                    "sample_count": 80,
                },
                "capture_wait_ms": {
                    "available": True,
                    "median_ms": 0.2,
                    "p95_ms": 0.5,
                    "max_ms": 0.8,
                    "sample_count": 80,
                },
                "capture_call_ms": {
                    "available": True,
                    "median_ms": 0.2,
                    "p95_ms": 0.5,
                    "max_ms": 0.8,
                    "sample_count": 80,
                },
                "capture_worker_loop_gap_ms": {
                    "available": True,
                    "median_ms": actual_work_ms,
                    "p95_ms": actual_work_ms + 0.6,
                    "max_ms": actual_work_ms + 1.2,
                    "sample_count": 80,
                },
                "capture_success_interval_ms": {
                    "available": True,
                    "median_ms": actual_work_ms,
                    "p95_ms": actual_work_ms + 0.6,
                    "max_ms": actual_work_ms + 1.2,
                    "sample_count": 80,
                },
                "frame_handoff_wait_ms": {
                    "available": True,
                    "median_ms": 0.0,
                    "p95_ms": 0.1,
                    "max_ms": 0.2,
                    "sample_count": 80,
                },
                "pending_frame_age_ms": {
                    "available": True,
                    "median_ms": 0.1,
                    "p95_ms": 0.2,
                    "max_ms": 0.4,
                    "sample_count": 80,
                },
                "frame_processing_ms": {
                    "available": True,
                    "median_ms": 10.9,
                    "p95_ms": 11.5,
                    "max_ms": 12.0,
                    "sample_count": 80,
                },
                "frame_convert_ms": {
                    "available": True,
                    "median_ms": 0.2,
                    "p95_ms": 0.3,
                    "max_ms": 0.5,
                    "sample_count": 80,
                },
                "zone_sampling_ms": {
                    "available": True,
                    "median_ms": 7.0,
                    "p95_ms": 7.7,
                    "max_ms": 8.1,
                    "sample_count": 80,
                },
                "colour_processing_ms": {
                    "available": True,
                    "median_ms": 0.1,
                    "p95_ms": 0.2,
                    "max_ms": 0.3,
                    "sample_count": 80,
                },
                "smoothing_ms": {
                    "available": True,
                    "median_ms": 0.1,
                    "p95_ms": 0.2,
                    "max_ms": 0.3,
                    "sample_count": 80,
                },
                "led_calibration_ms": {
                    "available": True,
                    "median_ms": 0.1,
                    "p95_ms": 0.2,
                    "max_ms": 0.3,
                    "sample_count": 80,
                },
                "output_prepare_ms": {
                    "available": True,
                    "median_ms": 0.1,
                    "p95_ms": 0.2,
                    "max_ms": 0.3,
                    "sample_count": 80,
                },
                "hid_write_ms": {
                    "available": True,
                    "median_ms": hid_write_ms,
                    "p95_ms": hid_write_ms + 0.3,
                    "max_ms": hid_write_ms + 0.6,
                    "sample_count": 80,
                },
                "hid_frame_build_ms": {
                    "available": True,
                    "median_ms": 0.25,
                    "p95_ms": 0.35,
                    "max_ms": 0.6,
                    "sample_count": 80,
                },
                "hid_device_write_ms": {
                    "available": True,
                    "median_ms": hid_write_ms,
                    "p95_ms": hid_write_ms + 0.3,
                    "max_ms": hid_write_ms + 0.6,
                    "sample_count": 80,
                },
                "hid_flush_or_wait_ms": {
                    "available": False,
                    "median_ms": 0.0,
                    "p95_ms": 0.0,
                    "max_ms": 0.0,
                    "sample_count": 0,
                },
                "inferred_unattributed_gap_ms": {
                    "available": True,
                    "median_ms": 0.0,
                    "p95_ms": 0.1,
                    "max_ms": 0.2,
                    "sample_count": 80,
                },
            },
            "counters": {"no_pending_frame_ticks": 0, "capture_worker_error_count": 0},
            "flags": {"capture_worker_active": True},
            "labels": {
                "latest_capture_backend_name": "kwin-dbus",
                "hid_device_write_limited": "yes",
            },
        },
    }


def test_priority_apply_failure_is_non_fatal(monkeypatch) -> None:
    state = RuntimeState()
    monkeypatch.setattr("os.getpriority", lambda *_args, **_kwargs: 0)

    def _raise_perm(*_args, **_kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr("os.setpriority", _raise_perm)
    apply_process_priority(config=AppConfig(performance_priority="high"), state=state)
    assert state.priority_apply_status == "failed"
    assert "permission denied" in state.priority_apply_error.lower()
    assert state.configured_priority_mode == "high"


def test_priority_modes_map_to_expected_targets(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr("os.getpriority", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr("os.setpriority", lambda _which, _who, value: calls.append(int(value)))

    state = RuntimeState()
    apply_process_priority(config=AppConfig(performance_priority="normal"), state=state)
    assert calls == []
    apply_process_priority(config=AppConfig(performance_priority="high"), state=state)
    apply_process_priority(
        config=AppConfig(performance_priority="very_high_experimental"), state=state
    )
    assert calls[-2:] == [-5, -10]


def test_latency_diagnostics_recommend_60_and_warn_120_over_budget() -> None:
    lines = latency_breakdown_lines(status=_latency_status(actual_work_ms=18.1, hid_write_ms=6.9))
    assert any("120 FPS is over budget." in line for line in lines)
    assert any(
        "60 FPS is near target but currently slightly over budget." in line for line in lines
    )
    assert any("Try 60 FPS for stable use." in line for line in lines)
    assert any("configured_priority_mode: high" in line for line in lines)
    assert any("priority_apply_status: failed" in line for line in lines)
    assert any("HID path appears device-write limited" in line for line in lines)


def _legacy_reference_zone_colors(
    frame: np.ndarray, zones: list[tuple[int, int, int, int]]
) -> np.ndarray:
    """Reference implementation matching the current optimized linear-RGB averaging."""
    img = frame
    h, w, _ = img.shape
    zones_arr = np.asarray(zones, dtype=np.intp)
    x0 = np.clip(zones_arr[:, 0], 0, w)
    y0 = np.clip(zones_arr[:, 1], 0, h)
    x1 = np.clip(zones_arr[:, 0] + zones_arr[:, 2], 0, w)
    y1 = np.clip(zones_arr[:, 1] + zones_arr[:, 3], 0, h)
    areas = (x1 - x0) * (y1 - y0)
    valid = areas > 0
    out = np.zeros((len(zones), 3), dtype=np.uint8)
    if not valid.any():
        return out
    linear_img = srgb_u8_to_linear01(img)
    bx0 = int(np.min(x0[valid]))
    by0 = int(np.min(y0[valid]))
    bx1 = int(np.max(x1[valid]))
    by1 = int(np.max(y1[valid]))
    cropped_linear = linear_img[by0:by1, bx0:bx1, :]
    integral = np.zeros(
        (cropped_linear.shape[0] + 1, cropped_linear.shape[1] + 1, 3), dtype=np.float64
    )
    integral[1:, 1:, :] = cropped_linear.cumsum(axis=0, dtype=np.float64).cumsum(
        axis=1, dtype=np.float64
    )
    cx0 = x0 - bx0
    cy0 = y0 - by0
    cx1 = x1 - bx0
    cy1 = y1 - by0
    valid_idx = np.flatnonzero(valid)
    sums = (
        integral[cy1[valid_idx], cx1[valid_idx]]
        - integral[cy0[valid_idx], cx1[valid_idx]]
        - integral[cy1[valid_idx], cx0[valid_idx]]
        + integral[cy0[valid_idx], cx0[valid_idx]]
    )
    avg_linear = (sums / areas[valid_idx, None]).astype(np.float32, copy=False)
    out[valid_idx] = linear01_to_srgb_u8(avg_linear)
    for idx in valid_idx:
        weights = _edge_localized_weights(
            zone_x0=int(x0[idx]),
            zone_y0=int(y0[idx]),
            zone_x1=int(x1[idx]),
            zone_y1=int(y1[idx]),
            frame_w=w,
            frame_h=h,
            edge_locality="balanced",
        )
        if weights is None:
            continue
        patch_linear = linear_img[y0[idx] : y1[idx], x0[idx] : x1[idx]]
        weighted_linear = (patch_linear * weights[:, :, None]).sum(axis=(0, 1), dtype=np.float64)
        out[idx] = linear01_to_srgb_u8(weighted_linear.astype(np.float32, copy=False))
    return out


def test_zone_sampling_output_equivalence_after_sampling_plan_optimization() -> None:
    rng = np.random.default_rng(42)
    frame = rng.integers(0, 255, size=(270, 480, 3), dtype=np.uint8)
    zones = [
        (0, 0, 80, 32),
        (80, 0, 80, 32),
        (160, 0, 80, 32),
        (240, 0, 80, 32),
        (320, 0, 80, 32),
        (400, 0, 80, 32),
        (448, 32, 32, 68),
        (448, 100, 32, 68),
        (448, 168, 32, 68),
        (0, 236, 80, 34),
        (80, 236, 80, 34),
        (160, 236, 80, 34),
        (240, 236, 80, 34),
        (320, 236, 80, 34),
        (400, 236, 80, 34),
        (0, 168, 32, 68),
        (0, 100, 32, 68),
        (0, 32, 32, 68),
    ]
    optimized = zone_colors_array(
        frame, zones, mode="balanced", edge_locality="balanced", engine="optimized"
    )
    reference = _legacy_reference_zone_colors(frame, zones)
    np.testing.assert_array_equal(optimized, reference)


def test_zone_sampling_auto_picks_faster_engine_for_48_edge_zones() -> None:
    rng = np.random.default_rng(7)
    frame = rng.integers(0, 255, size=(270, 480, 3), dtype=np.uint8)
    zones = [(i * 10 % 448, 0 if i < 24 else 236, 32, 34) for i in range(48)]
    _AUTO_ENGINE_CACHE.clear()
    auto = zone_colors_array(frame, zones, mode="balanced", edge_locality="balanced", engine="auto")
    key = (
        tuple((int(a), int(b), int(c), int(d)) for a, b, c, d in zones),
        frame.shape[1],
        frame.shape[0],
        1,
        "balanced",
    )
    assert _AUTO_ENGINE_CACHE.get(key) in {"legacy", "optimized"}
    zones_key = tuple((int(a), int(b), int(c), int(d)) for a, b, c, d in zones)
    x0, y0, x1, y1, areas, valid_idx, bx0, by0, bx1, by1, edge_plans = _cached_sampling_plan(
        zones_key, frame.shape[1], frame.shape[0], 1, "balanced"
    )
    valid = areas > 0
    legacy = _zone_means_legacy(
        image=frame,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        areas=areas,
        valid=valid,
        valid_idx=valid_idx,
        bx0=bx0,
        by0=by0,
        bx1=bx1,
        by1=by1,
        edge_plans=edge_plans,
    )
    optimized = _zone_means_optimized(
        image=frame,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        areas=areas,
        valid=valid,
        valid_idx=valid_idx,
        bx0=bx0,
        by0=by0,
        bx1=bx1,
        by1=by1,
        edge_plans=edge_plans,
    )
    assert np.max(np.abs(legacy.astype(np.int16) - optimized.astype(np.int16))) <= 30
    np.testing.assert_array_equal(
        auto, legacy if _AUTO_ENGINE_CACHE.get(key) == "legacy" else optimized
    )
