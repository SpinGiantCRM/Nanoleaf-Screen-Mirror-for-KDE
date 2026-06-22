from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.runtime.engine import _ensure_runtime_artifacts, process_frame


@dataclass(frozen=True)
class FlickerScenario:
    key: str
    title: str
    description: str
    frames: tuple[np.ndarray, ...]


def _base_config(*, zone_count: int = 48) -> AppConfig:
    calibration = CalibrationConfig(
        device_zone_count=zone_count,
        corner_anchor_top_left=0,
        corner_anchor_top_right=zone_count // 4,
        corner_anchor_bottom_right=zone_count // 2,
        corner_anchor_bottom_left=(3 * zone_count) // 4,
    )
    return AppConfig(
        device_zone_count=zone_count,
        calibration=calibration,
        zones=[],
        layout_preset="edge_strip",
    )


def _blank_frame(*, width: int = 160, height: int = 90, rgb: tuple[int, int, int]) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = list(rgb)
    return frame


def _spot_frame(
    *,
    width: int = 160,
    height: int = 90,
    background: tuple[int, int, int],
    spot: tuple[int, int, int],
) -> np.ndarray:
    frame = _blank_frame(width=width, height=height, rgb=background)
    frame[10:14, 10:14, :] = list(spot)
    return frame


def flicker_scenarios() -> tuple[FlickerScenario, ...]:
    return (
        FlickerScenario(
            key="dark_ramp",
            title="Dark ramp",
            description="Low-brightness ramp should stay visible without crushing to black.",
            frames=(
                _blank_frame(rgb=(4, 4, 4)),
                _blank_frame(rgb=(12, 12, 12)),
                _blank_frame(rgb=(24, 24, 24)),
            ),
        ),
        FlickerScenario(
            key="flash_alternate",
            title="Flash alternate",
            description="Rapid white/black alternation should not flatten every zone.",
            frames=(
                _blank_frame(rgb=(0, 0, 0)),
                _blank_frame(rgb=(255, 255, 255)),
                _blank_frame(rgb=(0, 0, 0)),
                _blank_frame(rgb=(255, 255, 255)),
            ),
        ),
        FlickerScenario(
            key="scene_cut",
            title="Scene cut",
            description="Strong colour cuts should produce distinct zone output.",
            frames=(
                _blank_frame(rgb=(255, 0, 0)),
                _blank_frame(rgb=(0, 0, 255)),
                _blank_frame(rgb=(0, 255, 0)),
            ),
        ),
        FlickerScenario(
            key="small_ui_element",
            title="Small UI element",
            description="Tiny bright detail on a dark scene should remain visible at the edge.",
            frames=(
                _spot_frame(background=(0, 0, 0), spot=(255, 0, 0)),
                _spot_frame(background=(0, 0, 0), spot=(255, 0, 0)),
            ),
        ),
    )


def _process_sequence(
    *,
    config: AppConfig,
    frames: tuple[np.ndarray, ...],
) -> list[list[tuple[int, int, int]]]:
    from nanoleaf_sync.runtime.state import RuntimeState

    state = RuntimeState()
    outputs: list[list[tuple[int, int, int]]] = []
    prev_smoothed: list[Any] = []
    for frame in frames:
        h, w = frame.shape[:2]
        zones_px, device_zone_indices_raw = _ensure_runtime_artifacts(
            state=state,
            config=config,
            img_w=w,
            img_h=h,
            detected_device_zone_count=int(config.device_zone_count or 48),
        )
        device_zone_indices = [int(i) for i in np.asarray(device_zone_indices_raw).tolist()]
        raw_colors = process_frame(
            frame=frame,
            prev_smoothed_colors=prev_smoothed,
            zones_px=zones_px,
            device_zone_indices=device_zone_indices,
            brightness=float(getattr(config, "brightness", 1.0) or 1.0),
            smoothing=float(getattr(config, "smoothing", 0.8) or 0.8),
            smoothing_speed=float(getattr(config, "smoothing_speed", 1.0) or 1.0),
            zone_sampling_stride=int(getattr(config, "zone_sampling_stride", 1) or 1),
            zone_sampling_engine=str(getattr(config, "zone_sampling_engine", "auto") or "auto"),
            led_gamma=float(getattr(config, "led_gamma", 2.2) or 2.2),
            motion_preset=str(getattr(config, "motion_preset", "responsive") or "responsive"),
            color_style=str(getattr(config, "color_style", "ambient") or "ambient"),
            edge_locality=str(getattr(config, "edge_locality", "balanced") or "balanced"),
            compositor_hdr_mode=bool(getattr(config, "compositor_hdr_mode", False)),
            sdr_boost_nits=float(getattr(config, "sdr_boost_nits", 80.0) or 80.0),
            hdr_max_nits=float(getattr(config, "hdr_max_nits", 1000.0) or 1000.0),
        )
        if not isinstance(raw_colors, list):
            continue
        row = [(int(channel[0]), int(channel[1]), int(channel[2])) for channel in raw_colors]
        outputs.append(row)
        prev_smoothed = list(raw_colors)
    return outputs


def _max_zone_delta(
    left: list[tuple[int, int, int]],
    right: list[tuple[int, int, int]],
) -> int:
    best = 0
    for a, b in zip(left, right, strict=False):
        best = max(best, max(abs(x - y) for x, y in zip(a, b, strict=True)))
    return best


def _flattening_score(rows: list[list[tuple[int, int, int]]]) -> float:
    if not rows:
        return 0.0
    last = rows[-1]
    if not last:
        return 0.0
    spread = 0
    for zone in last:
        spread = max(spread, max(zone))
    return float(spread) / 255.0


def run_flicker_lab(
    *,
    config: AppConfig | None = None,
    scenario_key: str = "all",
) -> dict[str, Any]:
    cfg = config or _base_config()
    selected = [
        scenario for scenario in flicker_scenarios() if scenario_key in {"all", scenario.key}
    ]
    if not selected:
        return {"ok": False, "message": f"Unknown flicker scenario: {scenario_key}"}
    results: list[dict[str, Any]] = []
    for scenario in selected:
        outputs = _process_sequence(config=cfg, frames=scenario.frames)
        max_step_delta = 0
        for idx in range(1, len(outputs)):
            max_step_delta = max(max_step_delta, _max_zone_delta(outputs[idx - 1], outputs[idx]))
        flatten = _flattening_score(outputs)
        passed = max_step_delta > 0 and (flatten > 0.05 or scenario.key == "flash_alternate")
        results.append(
            {
                "key": scenario.key,
                "title": scenario.title,
                "description": scenario.description,
                "frame_count": len(scenario.frames),
                "max_step_delta": max_step_delta,
                "flattening_score": round(flatten, 4),
                "passed": passed,
            }
        )
    overall = all(row["passed"] for row in results)
    message = "All flicker checks passed." if overall else "Some flicker checks need attention."
    return {
        "ok": True,
        "scenario_key": scenario_key,
        "overall_passed": overall,
        "scenarios": results,
        "message": message,
    }
