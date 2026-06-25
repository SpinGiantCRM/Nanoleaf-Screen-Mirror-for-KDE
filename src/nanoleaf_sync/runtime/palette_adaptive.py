from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nanoleaf_sync.color._types import RGBTuple
from nanoleaf_sync.runtime.palette_temporal import ZonePaletteTemporalState
from nanoleaf_sync.runtime.srgb import (
    linear01_to_srgb_float,
    linear01_to_srgb_u8,
    srgb_u8_to_linear01,
)

_CANDIDATE_ORDER = (
    "area_mean",
    "dominant_saturated_hue",
    "saturated_highlight",
    "peak_luma",
    "previous_colour_hold",
)
_SCORE_HYSTERESIS = 0.10
_LOW_LIGHT_PEAK = 32.0


@dataclass(frozen=True)
class PaletteAdaptiveFrame:
    current_best_algorithm: str
    current_best_confidence: float
    current_best_rgb: np.ndarray
    candidate_rgbs: dict[str, np.ndarray]
    scores: dict[str, float]
    diagnostics: PaletteAdaptiveDiagnostics


@dataclass(frozen=True)
class PaletteAdaptiveDiagnostics:
    selected_sampling_algorithm: str
    selected_candidate_rgb: RGBTuple
    candidate_confidence: float
    saturated_coverage: float
    neutral_white_coverage: float
    highlight_coverage: float
    dominant_hue_degrees: float
    hue_coherence: float
    rejected_neutral_candidate: bool
    fallback_reason: str
    final_reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "selected_sampling_algorithm": self.selected_sampling_algorithm,
            "selected_candidate_rgb": self.selected_candidate_rgb,
            "candidate_confidence": round(self.candidate_confidence, 4),
            "saturated_coverage": round(self.saturated_coverage, 4),
            "neutral_white_coverage": round(self.neutral_white_coverage, 4),
            "highlight_coverage": round(self.highlight_coverage, 4),
            "dominant_hue_degrees": round(self.dominant_hue_degrees, 2),
            "hue_coherence": round(self.hue_coherence, 4),
            "rejected_neutral_candidate": self.rejected_neutral_candidate,
            "fallback_reason": self.fallback_reason,
            "final_reason": self.final_reason,
        }


def _hue_degrees(rgb: np.ndarray) -> np.ndarray:
    r = rgb[:, 0]
    g = rgb[:, 1]
    b = rgb[:, 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    delta = mx - mn
    hue = np.zeros_like(mx, dtype=np.float32)
    valid = delta > 1e-6
    if not bool(valid.any()):
        return hue
    rv = r[valid]
    gv = g[valid]
    bv = b[valid]
    mxv = mx[valid]
    dvv = delta[valid]
    red_dom = mxv == rv
    green_dom = (mxv == gv) & ~red_dom
    blue_dom = ~red_dom & ~green_dom
    h = np.zeros_like(mxv, dtype=np.float32)
    if bool(red_dom.any()):
        h[red_dom] = ((gv[red_dom] - bv[red_dom]) / dvv[red_dom]) % 6.0
    if bool(green_dom.any()):
        h[green_dom] = 2.0 + ((bv[green_dom] - rv[green_dom]) / dvv[green_dom]) % 6.0
    if bool(blue_dom.any()):
        h[blue_dom] = 4.0 + ((rv[blue_dom] - gv[blue_dom]) / dvv[blue_dom]) % 6.0
    out = np.zeros_like(mx, dtype=np.float32)
    out[valid] = h * 60.0
    return out


def _meaningful_sat_mask(sat: np.ndarray, lum: np.ndarray, max_c: np.ndarray) -> np.ndarray:
    return (sat >= 0.18) & (lum >= 0.0116) & (max_c >= 0.0168)


def _low_light_linear_mean(patch_u8: np.ndarray) -> np.ndarray:
    linear = srgb_u8_to_linear01(np.asarray(patch_u8, dtype=np.uint8))
    avg_linear = linear.reshape(-1, 3).mean(axis=0)
    return linear01_to_srgb_u8(avg_linear.astype(np.float32, copy=False))


def _patch_features(
    patch_u8: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    linear = srgb_u8_to_linear01(np.asarray(patch_u8, dtype=np.uint8))
    flat = linear.reshape(-1, 3)
    if flat.size == 0:
        zeros = np.zeros(0, dtype=np.float32)
        return flat, zeros, zeros, zeros.astype(bool), zeros
    max_c = flat.max(axis=1)
    min_c = flat.min(axis=1)
    lum = (0.2126 * flat[:, 0]) + (0.7152 * flat[:, 1]) + (0.0722 * flat[:, 2])
    sat = (max_c - min_c) / np.clip(max_c, 0.0001, None)
    neutral = (sat < 0.10) & ((lum > 0.456) | (min_c > 0.578))
    return flat, lum, sat, neutral, max_c


def _candidate_area_mean(flat: np.ndarray) -> np.ndarray:
    if flat.size == 0:
        return np.zeros(3, dtype=np.float32)
    return flat.mean(axis=0)


def _candidate_dominant_saturated_hue(
    flat: np.ndarray, sat: np.ndarray, lum: np.ndarray, max_c: np.ndarray
) -> tuple[np.ndarray, float, float]:
    mask = _meaningful_sat_mask(sat, lum, max_c)
    if not bool(mask.any()):
        return _candidate_area_mean(flat), 0.0, 0.0
    selected = flat[mask]
    hues = _hue_degrees(selected)
    bins = (np.floor(hues / 20.0).astype(np.int32) % 18).astype(np.int32)
    counts = np.bincount(bins, minlength=18)
    best_bin = int(np.argmax(counts))
    bin_mask = bins == best_bin
    if not bool(bin_mask.any()):
        return selected.mean(axis=0), 0.0, 0.0
    rgb = selected[bin_mask].mean(axis=0)
    rad = np.deg2rad(hues[bin_mask])
    coherence = float(np.sqrt(np.mean(np.sin(rad)) ** 2 + np.mean(np.cos(rad)) ** 2))
    dominant_hue = float((best_bin * 20.0) + 10.0)
    return rgb, dominant_hue, coherence


def _candidate_saturated_highlight(
    flat: np.ndarray,
    sat: np.ndarray,
    lum: np.ndarray,
    neutral: np.ndarray,
    max_c: np.ndarray,
) -> tuple[np.ndarray, float]:
    if flat.size == 0:
        return np.zeros(3, dtype=np.float32), 0.0
    zone_lum = float(lum.mean())
    meaningful = _meaningful_sat_mask(sat, lum, max_c)
    bright_colored = meaningful & (lum >= max(0.021, zone_lum + 0.005)) & ~neutral
    if not bool(bright_colored.any()):
        return _candidate_area_mean(flat), 0.0
    selected = flat[bright_colored]
    sat_sel = sat[bright_colored]
    lum_sel = lum[bright_colored]
    weights = sat_sel * np.clip((lum_sel - zone_lum) / 0.08, 0.2, 1.5)
    weight_sum = float(weights.sum())
    if weight_sum <= 1e-6:
        return selected.mean(axis=0), float(bright_colored.mean())
    rgb = np.average(selected, axis=0, weights=weights)
    return rgb, float(bright_colored.mean())


def _candidate_peak_luma(
    flat: np.ndarray,
    sat: np.ndarray,
    lum: np.ndarray,
    neutral: np.ndarray,
    max_c: np.ndarray,
) -> tuple[np.ndarray, bool, float]:
    if flat.size == 0:
        return np.zeros(3, dtype=np.float32), True, 0.0
    cutoff = float(np.quantile(lum, 0.75))
    mask = lum >= cutoff
    if not bool(mask.any()):
        return flat.mean(axis=0), True, 0.0
    neutral_frac = float(neutral[mask].mean())
    meaningful = _meaningful_sat_mask(sat, lum, max_c)
    meaningful_frac = float(meaningful[mask].mean())
    rejected = neutral_frac > 0.55 or meaningful_frac < 0.20
    rgb = flat[mask].mean(axis=0)
    return rgb, rejected, float(mask.mean())


def _score_candidate(
    name: str,
    rgb: np.ndarray,
    *,
    saturated_coverage: float,
    neutral_coverage: float,
    highlight_coverage: float,
    hue_coherence: float,
    rejected_neutral_peak: bool,
    luma_contrast: float,
    prev_rgb: np.ndarray | None,
    prev_algo: str | None,
) -> float:
    chroma = float(np.max(rgb) - np.min(rgb))
    sat_proxy = chroma / max(float(np.max(rgb)), 1.0)

    if name == "area_mean":
        score = 0.35 - (saturated_coverage * 0.55) - (highlight_coverage * 0.15)
        score += neutral_coverage * 0.20
        return max(0.0, score)

    if name == "dominant_saturated_hue":
        if saturated_coverage < 0.06:
            return 0.05
        score = (saturated_coverage * 1.4) + (hue_coherence * 0.75) - (neutral_coverage * 0.35)
        score += min(0.25, sat_proxy * 0.4)
        return score

    if name == "saturated_highlight":
        if highlight_coverage < 0.02:
            return 0.05
        score = (highlight_coverage * 1.15) + (saturated_coverage * 0.55) + (luma_contrast * 0.25)
        score -= neutral_coverage * 0.60
        if neutral_coverage > 0.45 and highlight_coverage < 0.12:
            score *= 0.2
        return score

    if name == "peak_luma":
        if rejected_neutral_peak:
            return 0.0
        return (highlight_coverage * 0.7) + (saturated_coverage * 0.3) + (luma_contrast * 0.2)

    if name == "previous_colour_hold":
        if prev_rgb is None or not prev_algo:
            return 0.0
        dist = float(np.mean(np.abs(rgb - prev_rgb)))
        if dist > 45.0:
            return 0.05
        bonus = 0.28 if prev_algo == name else 0.0
        return 0.22 + bonus - ((dist / 255.0) * 0.3)

    return 0.0


def _pick_raw_best(scores: dict[str, float]) -> tuple[str, float]:
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return ranked[0]


def palette_adaptive_zone_frame(
    patch_u8: np.ndarray,
) -> PaletteAdaptiveFrame:
    patch = np.asarray(patch_u8, dtype=np.uint8)
    if patch.size == 0:
        empty = np.zeros(3, dtype=np.uint8)
        diag = PaletteAdaptiveDiagnostics(
            selected_sampling_algorithm="area_mean",
            selected_candidate_rgb=(0, 0, 0),
            candidate_confidence=0.0,
            saturated_coverage=0.0,
            neutral_white_coverage=0.0,
            highlight_coverage=0.0,
            dominant_hue_degrees=0.0,
            hue_coherence=0.0,
            rejected_neutral_candidate=False,
            fallback_reason="empty_patch",
            final_reason="empty_patch_area_mean",
        )
        return PaletteAdaptiveFrame(
            current_best_algorithm="area_mean",
            current_best_confidence=0.0,
            current_best_rgb=empty,
            candidate_rgbs={"area_mean": empty.astype(np.float32)},
            scores={"area_mean": 0.0},
            diagnostics=diag,
        )

    peak = float(patch.max())
    if peak < _LOW_LIGHT_PEAK:
        mean_u8 = _low_light_linear_mean(patch)
        rgb_tuple = (int(mean_u8[0]), int(mean_u8[1]), int(mean_u8[2]))
        diag = PaletteAdaptiveDiagnostics(
            selected_sampling_algorithm="area_mean",
            selected_candidate_rgb=rgb_tuple,
            candidate_confidence=1.0,
            saturated_coverage=0.0,
            neutral_white_coverage=0.0,
            highlight_coverage=0.0,
            dominant_hue_degrees=0.0,
            hue_coherence=0.0,
            rejected_neutral_candidate=False,
            fallback_reason="low_light",
            final_reason="low_light_area_mean",
        )
        return PaletteAdaptiveFrame(
            current_best_algorithm="area_mean",
            current_best_confidence=1.0,
            current_best_rgb=mean_u8.astype(np.float32),
            candidate_rgbs={"area_mean": mean_u8.astype(np.float32)},
            scores={"area_mean": np.float32(1.0)},
            diagnostics=diag,
        )

    flat, lum, sat, neutral, max_c = _patch_features(patch)
    meaningful_sat = _meaningful_sat_mask(sat, lum, max_c)
    saturated_coverage = float(meaningful_sat.mean())
    neutral_coverage = float(neutral.mean())
    luma_contrast = float(np.clip(np.std(lum) / 0.082, 0.0, 1.0))

    area_rgb = _candidate_area_mean(flat)
    dom_rgb, dominant_hue, hue_coherence = _candidate_dominant_saturated_hue(flat, sat, lum, max_c)
    highlight_rgb, highlight_coverage = _candidate_saturated_highlight(
        flat, sat, lum, neutral, max_c
    )
    peak_rgb, rejected_neutral_peak, peak_coverage = _candidate_peak_luma(
        flat, sat, lum, neutral, max_c
    )

    prev_arr: np.ndarray | None = None
    hold_rgb = area_rgb

    candidates: dict[str, np.ndarray] = {
        "area_mean": linear01_to_srgb_float(area_rgb),
        "dominant_saturated_hue": linear01_to_srgb_float(dom_rgb),
        "saturated_highlight": linear01_to_srgb_float(highlight_rgb),
        "peak_luma": linear01_to_srgb_float(peak_rgb),
        "previous_colour_hold": linear01_to_srgb_float(hold_rgb),
    }

    scores = {
        name: _score_candidate(
            name,
            candidates[name],
            saturated_coverage=saturated_coverage,
            neutral_coverage=neutral_coverage,
            highlight_coverage=highlight_coverage if name != "peak_luma" else peak_coverage,
            hue_coherence=hue_coherence,
            rejected_neutral_peak=rejected_neutral_peak,
            luma_contrast=luma_contrast,
            prev_rgb=prev_arr,
            prev_algo=None,
        )
        for name in _CANDIDATE_ORDER
    }

    winner, confidence = _pick_raw_best(scores)
    selected = np.clip(np.rint(candidates[winner]), 0.0, 255.0).astype(np.uint8)

    fallback_reason = ""
    if winner == "area_mean" and saturated_coverage >= 0.12:
        fallback_reason = "area_mean_stable_fallback"

    final_reason = f"{winner}_score_{confidence:.3f}"
    if rejected_neutral_peak and winner != "peak_luma":
        final_reason = f"{final_reason}_peak_luma_rejected_neutral"

    rgb_tuple = (int(selected[0]), int(selected[1]), int(selected[2]))
    diag = PaletteAdaptiveDiagnostics(
        selected_sampling_algorithm=winner,
        selected_candidate_rgb=rgb_tuple,
        candidate_confidence=float(confidence),
        saturated_coverage=saturated_coverage,
        neutral_white_coverage=neutral_coverage,
        highlight_coverage=highlight_coverage,
        dominant_hue_degrees=dominant_hue,
        hue_coherence=hue_coherence,
        rejected_neutral_candidate=rejected_neutral_peak,
        fallback_reason=fallback_reason,
        final_reason=final_reason,
    )
    return PaletteAdaptiveFrame(
        current_best_algorithm=winner,
        current_best_confidence=float(confidence),
        current_best_rgb=selected.astype(np.float32),
        candidate_rgbs=candidates,
        scores=scores,
        diagnostics=diag,
    )


def palette_adaptive_zone_color(
    patch_u8: np.ndarray,
    *,
    prev_rgb: RGBTuple | None = None,
    prev_algo: str | None = None,
    prev_state: object | None = None,
    global_scene_cut: bool = False,
    frame_index: int = 0,
) -> tuple[np.ndarray, PaletteAdaptiveDiagnostics, ZonePaletteTemporalState, dict[str, object]]:
    from nanoleaf_sync.runtime.palette_temporal import stabilize_palette_zone

    frame = palette_adaptive_zone_frame(patch_u8)
    state = (
        prev_state
        if isinstance(prev_state, ZonePaletteTemporalState)
        else ZonePaletteTemporalState.from_dict(prev_state)  # type: ignore[arg-type]
        if prev_state
        else None
    )
    if state is None and (prev_rgb is not None or prev_algo):
        state = ZonePaletteTemporalState(
            selected_algorithm=str(prev_algo or frame.current_best_algorithm),
            selected_rgb=prev_rgb or frame.diagnostics.selected_candidate_rgb,
            dominant_hue_degrees=float(frame.diagnostics.dominant_hue_degrees),
            held_rgb=tuple(
                float(v) for v in (prev_rgb or frame.diagnostics.selected_candidate_rgb)
            ),
        )
    color, new_state, temporal_diag = stabilize_palette_zone(
        current_best_algorithm=frame.current_best_algorithm,
        current_best_confidence=frame.current_best_confidence,
        current_best_rgb=frame.current_best_rgb,
        candidate_rgbs=frame.candidate_rgbs,
        scores=frame.scores,
        dominant_hue_degrees=float(frame.diagnostics.dominant_hue_degrees),
        neutral_white_coverage=float(frame.diagnostics.neutral_white_coverage),
        saturated_coverage=float(frame.diagnostics.saturated_coverage),
        hue_coherence=float(frame.diagnostics.hue_coherence),
        prev_state=state,
        global_scene_cut=global_scene_cut,
        frame_index=frame_index,
    )
    selected_algo = str(temporal_diag.get("selected_algorithm", frame.current_best_algorithm))
    diag = PaletteAdaptiveDiagnostics(
        selected_sampling_algorithm=selected_algo,
        selected_candidate_rgb=(int(color[0]), int(color[1]), int(color[2])),
        candidate_confidence=float(frame.scores.get(selected_algo, frame.current_best_confidence)),
        saturated_coverage=frame.diagnostics.saturated_coverage,
        neutral_white_coverage=frame.diagnostics.neutral_white_coverage,
        highlight_coverage=frame.diagnostics.highlight_coverage,
        dominant_hue_degrees=frame.diagnostics.dominant_hue_degrees,
        hue_coherence=frame.diagnostics.hue_coherence,
        rejected_neutral_candidate=frame.diagnostics.rejected_neutral_candidate,
        fallback_reason=str(temporal_diag.get("switch_reason", frame.diagnostics.fallback_reason)),
        final_reason=str(temporal_diag.get("switch_reason", frame.diagnostics.final_reason)),
    )
    merged_diag = {**frame.diagnostics.as_dict(), **temporal_diag, **new_state.to_dict()}
    return color, diag, new_state, merged_diag
