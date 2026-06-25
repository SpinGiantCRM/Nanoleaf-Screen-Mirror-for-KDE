from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from nanoleaf_sync.runtime.anchor_calibration import (
    CORNER_SEQUENCE_CLOCKWISE,
    CornerName,
    validate_corner_anchors,
)
from nanoleaf_sync.runtime.zone_derivation import zone_distribution_from_count

GuidedResponse = Literal["yes", "no", "close", "left", "right"]
GuidedStepKind = Literal[
    "direction",
    "corner",
    "rainbow",
    "complete",
]


@dataclass
class GuidedCalibrationSession:
    device_zone_count: int
    frame_width: int
    frame_height: int
    reverse_zones: bool = False
    anchors: dict[CornerName, int | None] = field(default_factory=dict)
    step_kind: GuidedStepKind = "direction"
    corner_index: int = 0
    corner_estimates: dict[CornerName, int] = field(default_factory=dict)
    corner_low: dict[CornerName, int] = field(default_factory=dict)
    corner_high: dict[CornerName, int] = field(default_factory=dict)
    iteration: int = 0
    elapsed_prompts: int = 0

    def __post_init__(self) -> None:
        total = max(4, int(self.device_zone_count))
        dist = zone_distribution_from_count(total)
        for corner in CORNER_SEQUENCE_CLOCKWISE:
            if corner not in self.anchors:
                self.anchors[corner] = None
            est = binary_search_estimate(
                low=0,
                high=total - 1,
                zones_per_side=dist,
                corner=corner,
            )
            self.corner_estimates[corner] = est
            self.corner_low[corner] = 0
            self.corner_high[corner] = total - 1

    @property
    def zones_per_side(self) -> tuple[int, int, int, int]:
        return zone_distribution_from_count(max(4, int(self.device_zone_count)))

    @property
    def current_corner(self) -> CornerName:
        return CORNER_SEQUENCE_CLOCKWISE[self.corner_index % 4]

    def progress_line(self) -> str:
        payload = {
            "step": self.step_kind,
            "corner": self.current_corner if self.step_kind == "corner" else None,
            "iteration": self.iteration,
            "reverse_zones": self.reverse_zones,
            "anchors": {k: v for k, v in self.anchors.items()},
            "elapsed_prompts": self.elapsed_prompts,
        }
        return json.dumps(payload)

    def apply_response(self, response: GuidedResponse) -> None:
        self.elapsed_prompts += 1
        if self.step_kind == "direction":
            self._apply_direction(response)
        elif self.step_kind == "corner":
            self._apply_corner(response)
        elif self.step_kind == "rainbow":
            self._apply_rainbow(response)
        self.iteration += 1

    def _apply_direction(self, response: GuidedResponse) -> None:
        if response == "no":
            self.reverse_zones = not self.reverse_zones
        self.step_kind = "corner"
        self.corner_index = 0

    def _apply_corner(self, response: GuidedResponse) -> None:
        corner = self.current_corner
        low = int(self.corner_low[corner])
        high = int(self.corner_high[corner])
        est = int(self.corner_estimates[corner])
        if response == "yes":
            self.anchors[corner] = est
            self.corner_index += 1
            if self.corner_index >= 4:
                self.step_kind = "rainbow"
            return
        if response == "left":
            est = binary_search_refine(est, low, high, direction="left")
        elif response == "right":
            est = binary_search_refine(est, low, high, direction="right")
        elif response == "close":
            est = binary_search_refine(est, low, high, direction="close")
        else:
            mid = (low + high) // 2
            if est < mid:
                high = mid
            else:
                low = mid + 1
            est = (low + high) // 2
        self.corner_low[corner] = low
        self.corner_high[corner] = high
        self.corner_estimates[corner] = est

    def _apply_rainbow(self, response: GuidedResponse) -> None:
        if response == "yes":
            self.step_kind = "complete"
            return
        self.step_kind = "corner"
        self.corner_index = 0

    def is_complete(self) -> bool:
        return self.step_kind == "complete"

    def validation(self) -> tuple[bool, list[str]]:
        return validate_anchor_consistency(
            anchors=self.anchors,
            device_zone_count=self.device_zone_count,
        )


def binary_search_estimate(
    *,
    low: int,
    high: int,
    zones_per_side: tuple[int, int, int, int],
    corner: CornerName,
) -> int:
    top, right, bottom, left = zones_per_side
    cumulative = {
        "top_left": 0,
        "top_right": top,
        "bottom_right": top + right,
        "bottom_left": top + right + bottom,
    }
    side_lengths = {
        "top_left": top,
        "top_right": right,
        "bottom_right": bottom,
        "bottom_left": left,
    }
    start = cumulative[corner]
    length = max(1, side_lengths[corner])
    return int(start + length // 2)


def binary_search_refine(
    estimate: int,
    low: int,
    high: int,
    *,
    direction: Literal["left", "right", "close"],
) -> int:
    span = max(1, high - low + 1)
    step = max(1, span // 4)
    if direction == "left":
        return max(low, int(estimate) - step)
    if direction == "right":
        return min(high, int(estimate) + step)
    if int(estimate) - low > high - int(estimate):
        return max(low, int(estimate) - max(1, step // 2))
    return min(high, int(estimate) + max(1, step // 2))


def validate_anchor_consistency(
    *,
    anchors: dict[CornerName, int | None],
    device_zone_count: int,
) -> tuple[bool, list[str]]:
    result = validate_corner_anchors(anchors=anchors, device_zone_count=device_zone_count)
    return result.valid, list(result.errors)
