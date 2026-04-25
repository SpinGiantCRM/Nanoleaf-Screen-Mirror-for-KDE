from __future__ import annotations

import csv
import os
import struct
import tempfile
import time
import zlib
from pathlib import Path
from typing import Sequence

import numpy as np

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.state import ZoneRect


def evaluate_geometry(*, status: dict, cfg: AppConfig) -> dict[str, object]:
    kde_w = int(status.get("kde_display_width") or 0)
    kde_h = int(status.get("kde_display_height") or 0)
    kde_scale = float(status.get("kde_scale_factor") or 0.0)
    cap_w = int(status.get("captured_frame_width") or status.get("capture_width") or 0)
    cap_h = int(status.get("captured_frame_height") or status.get("capture_height") or 0)
    expected_w = int(status.get("capture_width") or 0)
    expected_h = int(status.get("capture_height") or 0)

    physical_match = kde_w > 0 and kde_h > 0 and cap_w == kde_w and cap_h == kde_h
    logical_w = int(round(kde_w / kde_scale)) if kde_w > 0 and kde_scale > 0 else 0
    logical_h = int(round(kde_h / kde_scale)) if kde_h > 0 and kde_scale > 0 else 0
    logical_match = logical_w > 0 and logical_h > 0 and cap_w == logical_w and cap_h == logical_h
    inferred_scale = (float(kde_w) / float(cap_w)) if kde_w > 0 and cap_w > 0 else 0.0

    coordinate_mode = "unknown"
    if physical_match:
        coordinate_mode = "physical"
    elif logical_match:
        coordinate_mode = "logical"
    elif kde_w > 0 and cap_w > 0:
        coordinate_mode = "scaled"

    mismatch = bool(
        cap_w > 0
        and cap_h > 0
        and kde_w > 0
        and kde_h > 0
        and not physical_match
        and not logical_match
    )

    return {
        "kde_display_size": (kde_w, kde_h),
        "kde_scale_factor": kde_scale,
        "capture_backend": status.get("effective_capture_backend") or status.get("capture_backend") or "unknown",
        "captured_frame_size": (cap_w, cap_h),
        "expected_display_size": (expected_w, expected_h),
        "matches_physical": physical_match,
        "matches_logical": logical_match,
        "inferred_scale_factor": inferred_scale if inferred_scale > 0 else None,
        "coordinate_mode": coordinate_mode,
        "source_zone_count": int(status.get("source_zone_count") or 0),
        "strip_zone_count": int(status.get("configured_device_zone_count") or getattr(cfg, "device_zone_count", 0) or 0),
        "side_counts": tuple(int(i) for i in (status.get("source_zone_side_counts") or (0, 0, 0, 0))),
        "edge_thickness": status.get("edge_sampling_thickness"),
        "sample_step": int(status.get("zone_sampling_stride") or getattr(cfg, "zone_sampling_stride", 1) or 1),
        "edge_locality": status.get("edge_locality") or getattr(cfg, "edge_locality", "balanced"),
        "display_preset": status.get("display_preset") or getattr(cfg, "display_preset", "hdr"),
        "hdr_enabled_assumed": str(getattr(cfg, "display_preset", "hdr")).lower() == "hdr",
        "geometry_warning": mismatch,
        "warning_text": "Captured frame size does not match display geometry. Sampling positions may be scaled or offset.",
    }


def diagnostics_text_lines(*, status: dict, cfg: AppConfig) -> list[str]:
    geo = evaluate_geometry(status=status, cfg=cfg)
    side_counts = geo["side_counts"]
    latency_lines = latency_breakdown_lines(status=status)
    return [
        f"KDE display resolution: {geo['kde_display_size'][0]}x{geo['kde_display_size'][1]}",
        f"KDE scale factor: {geo['kde_scale_factor'] or 'unknown'}",
        f"Capture backend: {geo['capture_backend']}",
        f"Captured frame size: {geo['captured_frame_size'][0]}x{geo['captured_frame_size'][1]}",
        f"Expected display size: {geo['expected_display_size'][0]}x{geo['expected_display_size'][1]}",
        f"Match physical display: {'yes' if geo['matches_physical'] else 'no'}",
        f"Match logical/scaled display: {'yes' if geo['matches_logical'] else 'no'}",
        f"Inferred scale factor: {geo['inferred_scale_factor']:.3f}" if geo['inferred_scale_factor'] else "Inferred scale factor: unknown",
        f"Coordinate mode: {geo['coordinate_mode']}",
        f"Source-zone count: {geo['source_zone_count']} | Strip LED zone count: {geo['strip_zone_count']}",
        f"Per-side zone counts (T/R/B/L): {side_counts[0]}/{side_counts[1]}/{side_counts[2]}/{side_counts[3]}",
        f"Edge thickness: {geo['edge_thickness'] if geo['edge_thickness'] is not None else 'n/a'} | sample_step: {geo['sample_step']} | edge locality: {geo['edge_locality']}",
        f"Light spread mode: {status.get('light_spread', 'balanced')}",
        f"Display preset: {geo['display_preset']} | HDR enabled/assumed: {'yes' if geo['hdr_enabled_assumed'] else 'no'}",
        "Grey and white screen areas create neutral ambient light. Black areas turn the LEDs off.",
        geo["warning_text"] if geo["geometry_warning"] else "Display geometry and capture frame space are consistent.",
        "If per-zone output remains varied but the wall looks blended, this is likely physical diffusion.",
        "If per-zone output is already flat, software processing/sampling spread is likely.",
        *latency_lines,
    ]


def latency_breakdown_lines(*, status: dict) -> list[str]:
    measurement = status.get("latency_measurement")
    if not isinstance(measurement, dict):
        return ["Live mirroring latency stages: unavailable (no live runtime samples yet)."]

    live_only = bool(measurement.get("live_mirroring_only", False))
    dropped = int(measurement.get("dropped_or_skipped_frames") or 0)
    target_fps = float(measurement.get("target_fps") or 0.0)
    fps = float(measurement.get("effective_output_fps") or 0.0)
    fps_cap = float(measurement.get("fps_cap") or 0.0)
    fps_cap_reason = str(measurement.get("fps_cap_reason") or "none")
    stages = measurement.get("stages")
    if not isinstance(stages, dict):
        return ["Live mirroring latency stages: unavailable (stage timing payload missing)."]
    lines = [
        "Live mirroring latency stages (live-only metrics: yes)." if live_only
        else "Live mirroring latency stages (live-only metrics: no).",
        f"Target FPS: {target_fps:.1f} | Effective output FPS: {fps:.1f} | dropped/skipped frames: {dropped}",
        (
            f"FPS cap: {fps_cap:.1f} ({fps_cap_reason})"
            if fps_cap > 0.0
            else "FPS cap: unavailable"
        ),
    ]
    stage_order = (
        "loop_gap_ms",
        "pacing_wait_ms",
        "idle_wait_ms",
        "capture_wait_ms",
        "frame_processing_ms",
        "actual_work_ms",
        "hid_write_ms",
        "end_to_end_live_ms",
    )
    for stage in stage_order:
        row = stages.get(stage)
        if not isinstance(row, dict) or not bool(row.get("available", False)):
            lines.append(f"- {stage}: unavailable")
            continue
        lines.append(
            f"- {stage}: median={float(row.get('median_ms') or 0.0):.2f}ms "
            f"p95={float(row.get('p95_ms') or 0.0):.2f}ms "
            f"max={float(row.get('max_ms') or 0.0):.2f}ms "
            f"n={int(row.get('sample_count') or 0)}"
        )
    return lines


def _png_pack(tag: bytes, data: bytes) -> bytes:
    chunk = tag + data
    return struct.pack("!I", len(data)) + chunk + struct.pack("!I", zlib.crc32(chunk) & 0xFFFFFFFF)


def write_png(path: Path, image_rgb: np.ndarray) -> None:
    h, w, _ = image_rgb.shape
    raw = b"".join(b"\x00" + image_rgb[y].astype(np.uint8).tobytes() for y in range(h))
    payload = b"\x89PNG\r\n\x1a\n"
    payload += _png_pack(b"IHDR", struct.pack("!2I5B", w, h, 8, 2, 0, 0, 0))
    payload += _png_pack(b"IDAT", zlib.compress(raw, 9))
    payload += _png_pack(b"IEND", b"")
    path.write_bytes(payload)


def _draw_rect(image: np.ndarray, rect: ZoneRect, color: tuple[int, int, int], thickness: int = 2) -> None:
    x, y, w, h = rect
    x0 = max(0, int(x))
    y0 = max(0, int(y))
    x1 = min(image.shape[1], x0 + max(1, int(w)))
    y1 = min(image.shape[0], y0 + max(1, int(h)))
    if x1 <= x0 or y1 <= y0:
        return
    t = max(1, int(thickness))
    image[y0:min(y1, y0 + t), x0:x1, :] = color
    image[max(y0, y1 - t):y1, x0:x1, :] = color
    image[y0:y1, x0:min(x1, x0 + t), :] = color
    image[y0:y1, max(x0, x1 - t):x1, :] = color


def _zone_side_for_index(index: int, side_counts: tuple[int, int, int, int]) -> str:
    top, right, bottom, left = side_counts
    if index < top:
        return "top"
    if index < top + right:
        return "right"
    if index < top + right + bottom:
        return "bottom"
    if index < top + right + bottom + left:
        return "left"
    return "unknown"


def _synthetic_frame(width: int = 3840, height: int = 2160) -> np.ndarray:
    frame = np.full((height, width, 3), 40, dtype=np.uint8)
    frame[:, :, :] = np.array([96, 96, 96], dtype=np.uint8)
    return frame


def export_sampling_overlay(
    *,
    frame: np.ndarray | None,
    zones: Sequence[ZoneRect],
    side_counts: tuple[int, int, int, int],
    status: dict,
    cfg: AppConfig,
    synthetic: bool = False,
) -> Path:
    if not synthetic and not (isinstance(frame, np.ndarray) and frame.ndim == 3):
        raise ValueError("No live frame available. Start mirroring or capture one diagnostic frame.")
    base = (
        frame.copy()
        if isinstance(frame, np.ndarray) and frame.ndim == 3
        else _synthetic_frame()
    )
    side_palette = {
        "top": (0, 255, 0),
        "right": (32, 128, 255),
        "bottom": (255, 220, 0),
        "left": (255, 64, 64),
        "unknown": (255, 255, 255),
    }
    for idx, rect in enumerate(zones):
        side = _zone_side_for_index(idx, side_counts)
        _draw_rect(base, rect, side_palette[side], thickness=2)

    out_dir = Path(tempfile.gettempdir()) / "nanoleaf-kde-sync"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())
    mode = "synthetic-test" if synthetic else "live-captured"
    path = out_dir / f"sampling-overlay-{mode}-{stamp}.png"
    write_png(path, base)
    return path


def export_zone_report(*, rows: Sequence[dict[str, object]]) -> Path:
    if not rows:
        raise ValueError("No per-zone diagnostics available. Start mirroring or capture one diagnostic frame.")
    out_dir = Path(tempfile.gettempdir()) / "nanoleaf-kde-sync"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"zone-report-{int(time.time())}.csv"
    base_fields = ["zone_index", "side", "pixel_rect", "sampled_rgb", "final_output_rgb", "mapped_physical_led_index"]
    extra_fields = [
        "input_lightness",
        "output_lightness",
        "input_chroma",
        "output_chroma",
        "chroma_ratio",
        "neutral_floor_applied",
        "black_cutoff_applied",
        "grey_neutrality_verdict",
        "black_cutoff_verdict",
        "neutral_luminance_output_value",
    ]
    seen = set(base_fields)
    fields = list(base_fields)
    for key in extra_fields:
        if any(key in row for row in rows):
            fields.append(key)
            seen.add(key)
    for row in rows:
        for key in row.keys():
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    return path


def export_latency_report(*, status: dict) -> Path:
    measurement = status.get("latency_measurement")
    if not isinstance(measurement, dict):
        raise ValueError("No live latency diagnostics available. Start live mirroring to collect timing samples.")
    stages = measurement.get("stages")
    if not isinstance(stages, dict):
        raise ValueError("Latency diagnostics payload is malformed.")

    out_dir = Path(tempfile.gettempdir()) / "nanoleaf-kde-sync"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"latency-breakdown-{int(time.time())}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "stage",
                "available",
                "sample_count",
                "median_ms",
                "p95_ms",
                "max_ms",
                "live_mirroring_only",
                "target_fps",
                "fps_cap",
                "fps_cap_reason",
                "effective_output_fps",
                "dropped_or_skipped_frames",
            ],
        )
        writer.writeheader()
        for stage in (
            "capture_wait_ms",
            "pacing_wait_ms",
            "idle_wait_ms",
            "frame_processing_ms",
            "actual_work_ms",
            "hid_write_ms",
            "loop_gap_ms",
            "end_to_end_live_ms",
        ):
            row = stages.get(stage) or {}
            writer.writerow(
                {
                    "stage": stage,
                    "available": bool(row.get("available", False)),
                    "sample_count": int(row.get("sample_count", 0) or 0),
                    "median_ms": float(row.get("median_ms", 0.0) or 0.0),
                    "p95_ms": float(row.get("p95_ms", 0.0) or 0.0),
                    "max_ms": float(row.get("max_ms", 0.0) or 0.0),
                    "live_mirroring_only": bool(measurement.get("live_mirroring_only", False)),
                    "target_fps": float(measurement.get("target_fps", 0.0) or 0.0),
                    "fps_cap": float(measurement.get("fps_cap", 0.0) or 0.0),
                    "fps_cap_reason": str(measurement.get("fps_cap_reason", "") or ""),
                    "effective_output_fps": float(measurement.get("effective_output_fps", 0.0) or 0.0),
                    "dropped_or_skipped_frames": int(measurement.get("dropped_or_skipped_frames", 0) or 0),
                }
            )
    return path


def default_kde_display_metadata() -> dict[str, object]:
    scale = os.environ.get("QT_SCALE_FACTOR") or os.environ.get("GDK_SCALE") or ""
    session = os.environ.get("XDG_SESSION_TYPE", "")
    return {
        "kde_scale_factor": float(scale) if scale else 0.0,
        "kde_display_width": 0,
        "kde_display_height": 0,
        "kde_session_type": session,
    }
