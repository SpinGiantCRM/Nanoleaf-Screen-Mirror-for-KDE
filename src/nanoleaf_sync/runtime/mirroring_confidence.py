"""Single health score summarising mirroring pipeline status."""

from __future__ import annotations

from typing import Any


def compute_mirroring_confidence(status: dict[str, Any]) -> dict[str, object]:
    scores: list[int] = []
    weights: list[int] = []

    scores.append(max(0, 100 - int(status.get("consecutive_errors", 0)) * 20))
    weights.append(3)

    stale_rate = float(status.get("stale_drop_rate_per_second", 0) or 0)
    scores.append(max(0, 100 - int(stale_rate * 50)))
    weights.append(2)

    scores.append(100 if status.get("device_discovered") else 0)
    weights.append(3)

    calibration_status = str(status.get("calibration_status", "") or "")
    scores.append(100 if calibration_status == "ready" else 30)
    weights.append(2)

    weighted = sum(score * weight for score, weight in zip(scores, weights, strict=True))
    confidence = weighted // sum(weights)
    if confidence >= 90:
        rating = "excellent"
    elif confidence >= 70:
        rating = "good"
    elif confidence >= 50:
        rating = "fair"
    else:
        rating = "poor"
    return {"confidence_pct": int(confidence), "rating": rating}
