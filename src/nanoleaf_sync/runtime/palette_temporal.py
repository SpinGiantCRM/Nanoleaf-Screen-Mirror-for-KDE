from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nanoleaf_sync.color._types import RGBTuple

CONFIDENCE_SWITCH_MARGIN = 0.15
DWELL_FRAMES_MIN = 3
DWELL_FRAMES_MAX = 6
SCENE_CUT_RGB_DELTA = 48.0
SCENE_CUT_RGB_DELTA_FORCE = 64.0
HUE_DIFF_HOLD_DEGREES = 35.0
NEUTRAL_CHROMA_THRESHOLD = 15.0
SATURATED_CHROMA_THRESHOLD = 22.0
CANDIDATE_RGB_MAX_STEP = 42.0
CANDIDATE_RGB_SCENE_CUT_STEP = 255.0


@dataclass
class ZonePaletteTemporalState:
    selected_algorithm: str = ""
    selected_confidence: float = 0.0
    selected_rgb: RGBTuple = (0, 0, 0)
    dominant_hue_degrees: float = 0.0
    dwell_remaining: int = 0
    pending_algorithm: str = ""
    pending_streak: int = 0
    held_rgb: tuple[float, float, float] = (0.0, 0.0, 0.0)
    last_scene_cut_frame: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "selected_algorithm": self.selected_algorithm,
            "selected_confidence": round(self.selected_confidence, 4),
            "selected_rgb": self.selected_rgb,
            "dominant_hue_degrees": round(self.dominant_hue_degrees, 2),
            "dwell_remaining": int(self.dwell_remaining),
            "pending_algorithm": self.pending_algorithm,
            "pending_streak": int(self.pending_streak),
            "held_rgb": tuple(round(v, 2) for v in self.held_rgb),
            "last_scene_cut_frame": int(self.last_scene_cut_frame),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> ZonePaletteTemporalState:
        if not data:
            return cls()
        held = data.get("held_rgb", (0.0, 0.0, 0.0))
        rgb = data.get("selected_rgb", (0, 0, 0))
        return cls(
            selected_algorithm=str(data.get("selected_algorithm", "") or ""),
            selected_confidence=float(data.get("selected_confidence", 0.0) or 0.0),
            selected_rgb=(
                int(rgb[0]),  # type: ignore[index]
                int(rgb[1]),  # type: ignore[index]
                int(rgb[2]),  # type: ignore[index]
            ),
            dominant_hue_degrees=float(data.get("dominant_hue_degrees", 0.0) or 0.0),
            dwell_remaining=int(data.get("dwell_remaining", 0) or 0),
            pending_algorithm=str(data.get("pending_algorithm", "") or ""),
            pending_streak=int(data.get("pending_streak", 0) or 0),
            held_rgb=(
                float(held[0]),  # type: ignore[index]
                float(held[1]),  # type: ignore[index]
                float(held[2]),  # type: ignore[index]
            ),
            last_scene_cut_frame=int(data.get("last_scene_cut_frame", 0) or 0),
        )


def _rgb_chroma(rgb: np.ndarray | RGBTuple) -> float:
    arr = np.asarray(rgb, dtype=np.float32)
    return float(np.max(arr) - np.min(arr))


def _rgb_hue_degrees_single(rgb: np.ndarray | RGBTuple) -> float:
    arr = np.asarray(rgb, dtype=np.float32).reshape(3)
    r, g, b = float(arr[0]), float(arr[1]), float(arr[2])
    mx = max(r, g, b)
    mn = min(r, g, b)
    delta = mx - mn
    if delta <= 1.0:
        return 0.0
    if mx == r:
        h = ((g - b) / delta) % 6.0
    elif mx == g:
        h = 2.0 + ((b - r) / delta)
    else:
        h = 4.0 + ((r - g) / delta)
    return float(h * 60.0)


def _hue_delta_degrees(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def _required_dwell_frames(confidence_margin: float) -> int:
    if confidence_margin >= 0.45:
        return DWELL_FRAMES_MIN
    if confidence_margin >= 0.30:
        return DWELL_FRAMES_MIN + 1
    if confidence_margin >= 0.20:
        return DWELL_FRAMES_MIN + 2
    return DWELL_FRAMES_MAX


def detect_zone_scene_cut(
    *,
    prev_rgb: RGBTuple | None,
    instant_rgb: np.ndarray,
    instant_confidence: float,
    saturated_coverage: float,
    hue_coherence: float,
    global_scene_cut: bool = False,
) -> bool:
    if global_scene_cut:
        return True
    if prev_rgb is None:
        return False
    prev = np.asarray(prev_rgb, dtype=np.float32)
    inst = np.asarray(instant_rgb, dtype=np.float32)
    delta = float(np.mean(np.abs(inst - prev)))
    return (
        delta >= SCENE_CUT_RGB_DELTA_FORCE
        or (delta >= SCENE_CUT_RGB_DELTA and instant_confidence >= 0.30)
        or (delta >= SCENE_CUT_RGB_DELTA and saturated_coverage >= 0.20 and hue_coherence >= 0.65)
    )


def _blend_candidate_rgb(
    *,
    previous: tuple[float, float, float],
    target: np.ndarray,
    max_step: float,
) -> tuple[float, float, float]:
    prev = np.asarray(previous, dtype=np.float32)
    tgt = np.asarray(target, dtype=np.float32)
    delta = tgt - prev
    step = float(np.max(np.abs(delta)))
    blended = tgt if step <= max_step else prev + (delta * (max_step / step))
    return (float(blended[0]), float(blended[1]), float(blended[2]))


def stabilize_palette_zone(
    *,
    current_best_algorithm: str,
    current_best_confidence: float,
    current_best_rgb: np.ndarray,
    candidate_rgbs: dict[str, np.ndarray],
    scores: dict[str, float],
    dominant_hue_degrees: float,
    neutral_white_coverage: float,
    saturated_coverage: float,
    hue_coherence: float,
    prev_state: ZonePaletteTemporalState | None,
    global_scene_cut: bool = False,
    frame_index: int = 0,
) -> tuple[np.ndarray, ZonePaletteTemporalState, dict[str, object]]:
    prev = prev_state or ZonePaletteTemporalState()
    had_previous = bool(str(prev.selected_algorithm or "").strip())
    prev_rgb_tuple: RGBTuple | None = prev.selected_rgb if had_previous else None
    scene_cut = detect_zone_scene_cut(
        prev_rgb=prev_rgb_tuple,
        instant_rgb=current_best_rgb,
        instant_confidence=current_best_confidence,
        saturated_coverage=saturated_coverage,
        hue_coherence=hue_coherence,
        global_scene_cut=global_scene_cut,
    )

    previous_algorithm = prev.selected_algorithm if had_previous else ""
    selected_algorithm = previous_algorithm or current_best_algorithm
    algorithm_switch_blocked = False
    switch_reason = "maintain"
    dwell_remaining = 0
    pending_algorithm = ""
    pending_streak = 0

    prev_confidence = float(scores.get(previous_algorithm, prev.selected_confidence))
    confidence_margin = float(
        scores.get(current_best_algorithm, current_best_confidence) - prev_confidence
    )

    if not had_previous:
        selected_algorithm = current_best_algorithm
        switch_reason = "initial"
    elif scene_cut:
        selected_algorithm = current_best_algorithm
        switch_reason = "scene_cut"
        pending_algorithm = ""
        pending_streak = 0
        dwell_remaining = 0
    elif current_best_algorithm == previous_algorithm:
        selected_algorithm = previous_algorithm
        switch_reason = "maintain"
        pending_algorithm = ""
        pending_streak = 0
    elif confidence_margin < CONFIDENCE_SWITCH_MARGIN:
        selected_algorithm = previous_algorithm
        algorithm_switch_blocked = True
        switch_reason = "confidence_margin"
        pending_algorithm = ""
        pending_streak = 0
        dwell_remaining = _required_dwell_frames(confidence_margin)
    else:
        if current_best_algorithm == prev.pending_algorithm:
            pending_streak = prev.pending_streak + 1
        else:
            pending_streak = 1
        pending_algorithm = current_best_algorithm
        required = _required_dwell_frames(confidence_margin)
        dwell_remaining = max(0, required - pending_streak)
        if pending_streak >= required:
            selected_algorithm = current_best_algorithm
            switch_reason = "dwell_complete"
            pending_algorithm = ""
            pending_streak = 0
            dwell_remaining = 0
        else:
            selected_algorithm = previous_algorithm
            algorithm_switch_blocked = True
            switch_reason = "dwell_pending"

    target_rgb = np.asarray(
        candidate_rgbs.get(selected_algorithm, current_best_rgb), dtype=np.float32
    )
    instant_rgb = np.asarray(current_best_rgb, dtype=np.float32)

    prev_rgb_source = prev.held_rgb if prev.held_rgb != (0.0, 0.0, 0.0) else prev.selected_rgb
    prev_chroma = _rgb_chroma(prev_rgb_source)
    target_chroma = _rgb_chroma(target_rgb)
    instant_chroma = _rgb_chroma(instant_rgb)

    if (
        not scene_cut
        and prev_chroma >= SATURATED_CHROMA_THRESHOLD
        and target_chroma <= NEUTRAL_CHROMA_THRESHOLD
        and neutral_white_coverage >= 0.18
        and instant_chroma <= NEUTRAL_CHROMA_THRESHOLD
    ):
        target_rgb = np.asarray(prev_rgb_source)
        selected_algorithm = previous_algorithm
        algorithm_switch_blocked = True
        switch_reason = "neutral_flash_blocked"

    if not scene_cut and prev.selected_rgb and selected_algorithm != previous_algorithm:
        prev_hue = _rgb_hue_degrees_single(prev.selected_rgb)
        new_hue = _rgb_hue_degrees_single(target_rgb)
        if (
            _rgb_chroma(prev.selected_rgb) >= SATURATED_CHROMA_THRESHOLD
            and _rgb_chroma(target_rgb) >= SATURATED_CHROMA_THRESHOLD
            and _hue_delta_degrees(prev_hue, new_hue) >= HUE_DIFF_HOLD_DEGREES
            and confidence_margin < 0.30
        ):
            target_rgb = np.asarray(prev.selected_rgb, dtype=np.float32)
            selected_algorithm = previous_algorithm
            algorithm_switch_blocked = True
            switch_reason = "hue_stability"

    prev_held = prev.held_rgb
    if prev_held == (0.0, 0.0, 0.0) and prev.selected_rgb:
        prev_held = tuple(float(v) for v in prev.selected_rgb)

    instant_rgb_arr = np.asarray(current_best_rgb, dtype=np.float32)
    if (
        not scene_cut
        and prev.selected_rgb
        and (algorithm_switch_blocked or selected_algorithm == previous_algorithm)
    ):
        prev_selected_arr = np.asarray(prev.selected_rgb, dtype=np.float32)
        instant_delta = float(np.mean(np.abs(instant_rgb_arr - prev_selected_arr)))
        if instant_delta > 28.0 and confidence_margin < CONFIDENCE_SWITCH_MARGIN:
            target_rgb = np.asarray(prev_held, dtype=np.float32)
            switch_reason = "candidate_rgb_hold"
            algorithm_switch_blocked = True

    if not had_previous or scene_cut or prev_held == (0.0, 0.0, 0.0):
        held_rgb = (
            float(target_rgb[0]),
            float(target_rgb[1]),
            float(target_rgb[2]),
        )
    else:
        max_step = CANDIDATE_RGB_SCENE_CUT_STEP if scene_cut else CANDIDATE_RGB_MAX_STEP
        if algorithm_switch_blocked:
            max_step = min(max_step, 20.0)
        held_rgb = _blend_candidate_rgb(previous=prev_held, target=target_rgb, max_step=max_step)
    out_rgb = np.clip(np.rint(held_rgb), 0.0, 255.0).astype(np.uint8)

    new_state = ZonePaletteTemporalState(
        selected_algorithm=selected_algorithm,
        selected_confidence=float(scores.get(selected_algorithm, current_best_confidence)),
        selected_rgb=(int(out_rgb[0]), int(out_rgb[1]), int(out_rgb[2])),
        dominant_hue_degrees=dominant_hue_degrees,
        dwell_remaining=int(dwell_remaining),
        pending_algorithm=pending_algorithm,
        pending_streak=int(pending_streak),
        held_rgb=held_rgb,
        last_scene_cut_frame=int(frame_index if scene_cut else prev.last_scene_cut_frame),
    )

    diagnostics: dict[str, object] = {
        "previous_algorithm": previous_algorithm,
        "current_best_algorithm": current_best_algorithm,
        "selected_algorithm": selected_algorithm,
        "algorithm_switch_blocked": algorithm_switch_blocked,
        "switch_reason": switch_reason,
        "dwell_remaining": int(dwell_remaining),
        "confidence_margin": round(confidence_margin, 4),
        "scene_cut_detected": scene_cut,
    }
    return out_rgb, new_state, diagnostics


def stabilize_palette_batch(
    *,
    zone_frames: list[dict[str, object]],
    prev_states: list[ZonePaletteTemporalState] | None,
    global_scene_cut: bool = False,
    frame_index: int = 0,
) -> tuple[list[np.ndarray], list[ZonePaletteTemporalState], list[dict[str, object]]]:
    prev_states = list(prev_states or [])
    colors: list[np.ndarray] = []
    states: list[ZonePaletteTemporalState] = []
    diagnostics: list[dict[str, object]] = []
    for idx, frame in enumerate(zone_frames):
        prev = prev_states[idx] if idx < len(prev_states) else None
        rgb, state, diag = stabilize_palette_zone(
            current_best_algorithm=str(frame["current_best_algorithm"]),
            current_best_confidence=float(frame["current_best_confidence"]),
            current_best_rgb=np.asarray(frame["current_best_rgb"], dtype=np.float32),
            candidate_rgbs={
                str(k): np.asarray(v, dtype=np.float32)
                for k, v in frame["candidate_rgbs"].items()  # type: ignore[union-attr]
            },
            scores={str(k): float(v) for k, v in frame["scores"].items()},  # type: ignore[union-attr]
            dominant_hue_degrees=float(frame.get("dominant_hue_degrees", 0.0) or 0.0),
            neutral_white_coverage=float(frame.get("neutral_white_coverage", 0.0) or 0.0),
            saturated_coverage=float(frame.get("saturated_coverage", 0.0) or 0.0),
            hue_coherence=float(frame.get("hue_coherence", 0.0) or 0.0),
            prev_state=prev,
            global_scene_cut=global_scene_cut,
            frame_index=frame_index,
        )
        colors.append(rgb)
        states.append(state)
        base_diag = dict(frame.get("base_diagnostics", {}) or {})
        base_diag.update(diag)
        base_diag["selected_sampling_algorithm"] = selected_algorithm_name(
            selected=str(diag["selected_algorithm"]),
            current_best=str(diag["current_best_algorithm"]),
        )
        diagnostics.append(base_diag)
    return colors, states, diagnostics


def selected_algorithm_name(*, selected: str, current_best: str) -> str:
    return selected or current_best
