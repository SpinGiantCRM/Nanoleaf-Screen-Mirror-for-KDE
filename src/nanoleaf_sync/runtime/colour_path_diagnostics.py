from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from nanoleaf_sync.runtime.diagnostics_exports import write_png

if TYPE_CHECKING:
    from nanoleaf_sync.config.model import AppConfig
    from nanoleaf_sync.runtime.engine import FrameProcessingTimings

_RGB = tuple[int, int, int]
_STAGE_KEYS = (
    "output_rgb_before_style_mapping",
    "output_rgb_after_style_mapping",
    "output_rgb_after_light_spread",
    "output_rgb_after_smoothing",
    "output_rgb_after_led_calibration",
    "final_output_rgb",
)


def snapshot_device_rgb_rows(mapped: np.ndarray) -> tuple[_RGB, ...]:
    clipped = np.clip(mapped, 0.0, 255.0)
    rounded = np.rint(clipped).astype(np.uint8)
    return tuple(tuple(int(c) for c in row) for row in rounded.tolist())


def device_stage_rgb(
    stages: tuple[_RGB, ...],
    *,
    mapped_led_index: int | None,
) -> _RGB | None:
    if mapped_led_index is None or mapped_led_index < 0 or mapped_led_index >= len(stages):
        return None
    return stages[mapped_led_index]


def _portal_rgb_conversion_path(fmt: object) -> str:
    normalized = str(fmt or "").strip().upper()
    if normalized == "RGB":
        return "native_rgb"
    if normalized == "BGR":
        return "bgr_channel_swap"
    if normalized in {"RGBX", "RGBA"}:
        return "drop_alpha_native_rgb_order"
    if normalized in {"BGRX", "BGRA"}:
        return "drop_alpha_bgr_channel_swap"
    if normalized:
        return f"unknown_format:{normalized.lower()}"
    return "unknown"


def build_portal_capture_diagnostics(capture: object | None) -> dict[str, object]:
    if capture is None or str(getattr(capture, "name", "") or "") != "xdg-portal":
        return {}
    frame_diag = getattr(capture, "_last_frame_diag", None)
    if not isinstance(frame_diag, dict):
        frame_diag = {}
    fmt = frame_diag.get("format")
    use_gstreamer = bool(getattr(capture, "_use_gstreamer", False))
    return {
        "negotiated_caps": frame_diag.get("caps"),
        "pixel_format": fmt,
        "stride": frame_diag.get("stride"),
        "width": int(frame_diag.get("width") or getattr(capture, "width", 0) or 0) or None,
        "height": int(frame_diag.get("height") or getattr(capture, "height", 0) or 0) or None,
        "pipewire_node_id": getattr(capture, "_node_id", None),
        "restore_token_state": str(getattr(capture, "portal_restore_token_state", "") or "none"),
        "restore_token_loaded": bool(getattr(capture, "portal_restore_token_loaded", False)),
        "restore_token_accepted": bool(getattr(capture, "portal_restore_token_accepted", False)),
        "implementation_path": "gstreamer" if use_gstreamer else "pipewire-python",
        "rgb_bgr_conversion_path": _portal_rgb_conversion_path(fmt),
        "rgb_conversion_attempted": bool(frame_diag.get("rgb_conversion_attempted", False)),
        "rgb_conversion_success": bool(frame_diag.get("rgb_conversion_success", False)),
        "capture_path": getattr(capture, "last_capture_path", None),
    }


def build_kwin_capture_diagnostics(capture: object | None) -> dict[str, object]:
    if capture is None or str(getattr(capture, "name", "") or "") != "kwin-dbus":
        return {}
    raw = getattr(capture, "last_capture_diagnostics", None)
    if not isinstance(raw, dict) or not raw:
        return {}
    return {
        "screenshot2_method": raw.get("screenshot2_method"),
        "requested_monitor_id": raw.get("requested_monitor_id"),
        "rejected_monitor_id": raw.get("rejected_monitor_id"),
        "invalid_screen_fallback_used": bool(raw.get("invalid_screen_fallback_used", False)),
        "legacy_fallback_used": bool(raw.get("legacy_fallback_used", False)),
        "capture_path_kind": raw.get("capture_path_kind"),
        "detail": raw.get("detail"),
    }


def build_capture_source_diagnostics(
    *,
    status: dict[str, object],
    hdr_colour_path: dict[str, object],
    capture: object | None,
) -> dict[str, object]:
    identity = status.get("latest_capture_source_identity")
    identity_dict = identity if isinstance(identity, dict) else {}
    frame_ctx = status.get("latest_frame_context")
    frame_source: dict[str, object] = {}
    if isinstance(frame_ctx, dict) and isinstance(frame_ctx.get("source"), dict):
        frame_source = frame_ctx["source"]  # type: ignore[assignment]
    stream_w = int(status.get("captured_frame_width") or status.get("capture_width") or 0)
    stream_h = int(status.get("captured_frame_height") or status.get("capture_height") or 0)
    display_w = int(status.get("kde_display_width") or 0)
    display_h = int(status.get("kde_display_height") or 0)
    kde_scale = float(status.get("kde_scale_factor") or 0.0)
    inferred_scale = (
        (float(display_w) / float(stream_w)) if display_w > 0 and stream_w > 0 else None
    )
    backend = str(
        hdr_colour_path.get("backend")
        or status.get("effective_capture_backend")
        or status.get("capture_backend")
        or "unknown"
    )
    return {
        "backend": backend,
        "capture_method": str(
            status.get("capture_path") or getattr(capture, "last_capture_path", "") or ""
        ),
        "backend_source_id": frame_source.get("backend_source_id")
        or frame_source.get("monitor_id"),
        "monitor_confidence": identity_dict.get("confidence"),
        "scale_confidence": identity_dict.get("scale_confidence"),
        "stream_size": [stream_w, stream_h] if stream_w > 0 and stream_h > 0 else None,
        "display_size": [display_w, display_h] if display_w > 0 and display_h > 0 else None,
        "scale_factors": {
            "kde_scale_factor": kde_scale if kde_scale > 0 else None,
            "inferred_capture_to_display": inferred_scale,
        },
        "hdr_transfer": hdr_colour_path.get("transfer"),
        "hdr_primaries": hdr_colour_path.get("primaries"),
        "metadata_source": hdr_colour_path.get("capture_metadata_source")
        or hdr_colour_path.get("source"),
        "display_referred": bool(hdr_colour_path.get("display_referred", False)),
        "tone_mapping_applied": bool(hdr_colour_path.get("tone_mapping_applied", False)),
        "skip_display_gamut_adaptation": bool(
            hdr_colour_path.get("skip_display_gamut_adaptation", False)
        ),
        "sdr_boost_compensation_enabled": bool(
            hdr_colour_path.get("sdr_boost_compensation_enabled", False)
        ),
    }


def build_capture_colour_diagnostics(
    *,
    status: dict[str, object],
    hdr_colour_path: dict[str, object],
    capture: object | None,
) -> dict[str, object]:
    capture_source = build_capture_source_diagnostics(
        status=status,
        hdr_colour_path=hdr_colour_path,
        capture=capture,
    )
    portal = build_portal_capture_diagnostics(capture)
    kwin = build_kwin_capture_diagnostics(capture)
    return {
        "capture_source": capture_source,
        "portal": portal,
        "kwin": kwin,
    }


def _colour_stages_from_timings(
    proc_timings: FrameProcessingTimings | None,
) -> dict[str, tuple[_RGB, ...]]:
    if proc_timings is None:
        return {}
    return {
        "output_rgb_before_style_mapping": getattr(proc_timings, "colour_path_before_style", ())
        or (),
        "output_rgb_after_style_mapping": getattr(proc_timings, "colour_path_after_style", ())
        or (),
        "output_rgb_after_light_spread": getattr(proc_timings, "colour_path_after_spread", ())
        or (),
        "output_rgb_after_smoothing": getattr(proc_timings, "colour_path_after_smoothing", ())
        or (),
        "output_rgb_after_led_calibration": getattr(
            proc_timings, "colour_path_after_led_calibration", ()
        )
        or (),
        "final_output_rgb": getattr(proc_timings, "colour_path_final", ()) or (),
    }


def zone_colour_path_stage_fields(
    *,
    mapped_led_index: int | None,
    proc_timings: FrameProcessingTimings | None,
    fallback_pre_led: _RGB,
    fallback_final: _RGB,
) -> dict[str, object]:
    stages = _colour_stages_from_timings(proc_timings)
    fields: dict[str, object] = {}
    for key in _STAGE_KEYS:
        device_rows = stages.get(key, ())
        rgb = device_stage_rgb(device_rows, mapped_led_index=mapped_led_index)
        if rgb is None:
            if key == "output_rgb_after_light_spread":
                rgb = fallback_pre_led
            elif key == "final_output_rgb":
                rgb = fallback_final
            else:
                rgb = None
        fields[key] = rgb
    return fields


def resolve_mapped_led_index(
    zone_index: int,
    device_zone_indices: np.ndarray | list[int],
) -> int | None:
    indices = (
        device_zone_indices.tolist()
        if isinstance(device_zone_indices, np.ndarray)
        else list(device_zone_indices)
    )
    for led_idx, src_idx in enumerate(indices):
        if int(src_idx) == int(zone_index):
            return led_idx
    return None


def resolve_zone_side(
    zone_index: int,
    side_counts: tuple[int, int, int, int],
) -> str:
    top, right, bottom, left = side_counts
    if zone_index < top:
        return "top"
    if zone_index < top + right:
        return "right"
    if zone_index < top + right + bottom:
        return "bottom"
    if zone_index < top + right + bottom + left:
        return "left"
    return "unknown"


def build_zone_colour_path_row(
    *,
    zone_index: int,
    rect: tuple[int, int, int, int],
    side: str,
    sampled_rgb: _RGB,
    mapped_led_index: int | None,
    pre_led_rgb: _RGB,
    final_rgb: _RGB,
    proc_timings: FrameProcessingTimings | None,
    sampling_fields: dict[str, object],
    color_style: str,
    color_pipeline_fields: dict[str, object] | None = None,
) -> dict[str, object]:
    from nanoleaf_sync.runtime.color_processing import color_pipeline_diagnostics

    pipeline_extra = color_pipeline_fields or color_pipeline_diagnostics(
        input_rgb=sampled_rgb,
        output_rgb=final_rgb,
        color_style=color_style,
    )
    row: dict[str, object] = {
        "zone_index": zone_index,
        "side": side,
        "pixel_rect": rect,
        "sampled_rgb": sampled_rgb,
        "output_rgb_before_led_calibration": pre_led_rgb,
        "final_output_rgb": final_rgb,
        "mapped_physical_led_index": mapped_led_index,
        "input_luminance": color_pipeline_diagnostics(
            input_rgb=sampled_rgb,
            output_rgb=sampled_rgb,
            color_style=color_style,
        )["sampled_luminance"],
        "led_calibration_applied": pre_led_rgb != final_rgb,
        **sampling_fields,
        **zone_colour_path_stage_fields(
            mapped_led_index=mapped_led_index,
            proc_timings=proc_timings,
            fallback_pre_led=pre_led_rgb,
            fallback_final=final_rgb,
        ),
        **pipeline_extra,
    }
    selected = row.get("selected_algorithm") or row.get("selected_candidate")
    if selected is not None:
        row["selected_candidate"] = selected
    return row


def _config_snapshot(config: AppConfig) -> dict[str, object]:
    return {
        "device_zone_count": int(getattr(config, "device_zone_count", 0) or 0),
        "prefer_backend": str(getattr(config, "prefer_backend", "")),
        "display_preset": str(getattr(config, "display_preset", "")),
        "capture_monitor": str(getattr(config, "capture_monitor", "") or ""),
        "fps": int(getattr(config, "fps", 0) or 0),
        "sync_mode": str(getattr(config, "sync_mode", "")),
        "color_style": str(getattr(config, "color_style", "")),
        "sampling_mode": str(getattr(config, "sampling_mode", "")),
        "zone_sampling_engine": str(getattr(config, "zone_sampling_engine", "")),
        "compositor_hdr_mode": bool(getattr(config, "compositor_hdr_mode", False)),
        "sdr_boost_nits": float(getattr(config, "sdr_boost_nits", 80.0)),
        "hdr_transfer": str(getattr(config, "hdr_transfer", "")),
        "hdr_primaries": str(getattr(config, "hdr_primaries", "")),
        "live_diagnostics_enabled": bool(getattr(config, "live_diagnostics_enabled", False)),
        "verbose": bool(getattr(config, "verbose", False)),
    }


def _downscale_thumbnail(frame: np.ndarray, *, max_width: int = 320) -> np.ndarray:
    h, w, _ = frame.shape
    if w <= max_width:
        return frame
    scale = max_width / float(w)
    target_w = max(1, int(round(w * scale)))
    target_h = max(1, int(round(h * scale)))
    y_idx = (np.linspace(0, h - 1, target_h)).astype(np.intp)
    x_idx = (np.linspace(0, w - 1, target_w)).astype(np.intp)
    return frame[np.ix_(y_idx, x_idx)]


def write_colour_debug_snapshot(
    output_path: Path,
    *,
    config: AppConfig,
    status: dict[str, object],
    frame: np.ndarray | None,
    capture: object | None = None,
) -> dict[str, object]:
    output_path = Path(output_path)
    if output_path.suffix.lower() in {".zip", ".json"}:
        out_dir = output_path.with_suffix("")
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = output_path
        out_dir.mkdir(parents=True, exist_ok=True)

    hdr = status.get("hdr_colour_path")
    hdr_dict = hdr if isinstance(hdr, dict) else {}
    capture_colour = build_capture_colour_diagnostics(
        status=status,
        hdr_colour_path=hdr_dict,
        capture=capture,
    )
    zones = list(status.get("_latest_zone_diagnostics") or status.get("zone_diagnostics") or [])
    thumbnail_written = False
    if isinstance(frame, np.ndarray) and frame.ndim == 3 and frame.shape[2] >= 3:
        thumb_path = out_dir / "frame_thumbnail.png"
        write_png(thumb_path, _downscale_thumbnail(frame[:, :, :3]))
        os.chmod(thumb_path, 0o600)
        thumbnail_written = True

    files_written: list[str] = []
    payloads: list[tuple[str, dict[str, Any] | list[Any]]] = [
        ("zones.json", zones),
        ("config_snapshot.json", _config_snapshot(config)),
        (
            "capture_backend_status.json",
            {
                "capture_colour_diagnostics": capture_colour,
                "hdr_colour_path": hdr_dict,
                "capture_backend": status.get("capture_backend"),
                "effective_capture_backend": status.get("effective_capture_backend"),
                "capture_path": status.get("capture_path"),
                "kwin_capture_diagnostics": status.get("kwin_capture_diagnostics"),
                "portal_restore_token_state": status.get("portal_restore_token_state"),
            },
        ),
        (
            "colour_context.json",
            {
                "latest_color_context": status.get("latest_color_context"),
                "latest_frame_context": status.get("latest_frame_context"),
                "latest_capture_source_identity": status.get("latest_capture_source_identity"),
            },
        ),
        (
            "errors_status.json",
            {
                "last_error": status.get("last_error"),
                "last_error_kind": status.get("last_error_kind"),
                "last_error_guidance": status.get("last_error_guidance"),
                "runtime_warnings": status.get("runtime_warnings"),
                "consecutive_errors": status.get("consecutive_errors"),
                "running": status.get("running"),
                "exported_at_unix": time.time(),
            },
        ),
    ]
    for name, payload in payloads:
        path = out_dir / name
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        os.chmod(path, 0o600)
        files_written.append(name)

    return {
        "ok": True,
        "path": str(out_dir),
        "thumbnail_written": thumbnail_written,
        "zone_count": len(zones),
        "files_written": files_written,
        "message": f"Saved colour debug snapshot to {out_dir}",
    }
