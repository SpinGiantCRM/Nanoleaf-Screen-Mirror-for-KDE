from __future__ import annotations

from typing import Any

import numpy as np


def compare_colour_path_stages(
    *,
    captured_rgb: tuple[int, int, int],
    staged_outputs: dict[str, tuple[int, int, int]],
) -> dict[str, Any]:
    captured = tuple(int(v) for v in captured_rgb)
    rows: list[dict[str, Any]] = []
    previous = captured
    for stage, rgb in staged_outputs.items():
        current = tuple(int(v) for v in rgb)
        delta = tuple(abs(a - b) for a, b in zip(current, previous, strict=True))
        rows.append(
            {
                "stage": str(stage),
                "rgb": current,
                "delta_from_previous": delta,
                "delta_from_capture": tuple(
                    abs(a - b) for a, b in zip(current, captured, strict=True)
                ),
            }
        )
        previous = current
    return {
        "captured_rgb": captured,
        "stages": rows,
        "final_rgb": rows[-1]["rgb"] if rows else captured,
    }


def sample_frame_rgb(frame: np.ndarray, *, x: int, y: int) -> tuple[int, int, int]:
    img = np.asarray(frame)
    if img.ndim != 3 or img.shape[2] != 3:
        raise ValueError("Expected RGB frame with shape (H, W, 3)")
    row = int(np.clip(y, 0, img.shape[0] - 1))
    col = int(np.clip(x, 0, img.shape[1] - 1))
    pixel = img[row, col]
    return int(pixel[0]), int(pixel[1]), int(pixel[2])
