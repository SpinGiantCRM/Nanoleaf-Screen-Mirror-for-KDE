from __future__ import annotations

import logging
from typing import Any, Dict, List

from nanoleaf_sync.capture.backend_selection import (
    normalize_backend_preference,
    normalize_cached_backend,
)
from nanoleaf_sync.config.model import AppConfig, ZoneConfig

logger = logging.getLogger(__name__)

SAMPLING_QUALITY_TO_ZONE_STRIDE: dict[str, int] = {
    "low": 4,
    "balanced": 2,
    "high": 1,
}


def sampling_quality_to_zone_stride(quality: str) -> int:
    return SAMPLING_QUALITY_TO_ZONE_STRIDE.get(str(quality).strip().lower(), 2)


def coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
        return default
    return default


def normalize_enum(value: Any, *, allowed: Dict[str, str], default: str) -> str:
    normalized = str(value).strip().lower()
    return allowed.get(normalized, default)


def validate_config(cfg: AppConfig) -> AppConfig:
    brightness = max(0.0, min(1.0, float(cfg.brightness)))
    smoothing = max(0.0, min(1.0, float(cfg.smoothing)))
    smoothing_speed = max(0.0, min(4.0, float(cfg.smoothing_speed)))
    led_gamma = max(1.0, min(4.0, float(cfg.led_gamma)))
    fps = max(1, min(120, int(cfg.fps)))
    sampling_quality = normalize_enum(
        getattr(cfg, "sampling_quality", AppConfig.sampling_quality),
        allowed={
            "low": "low",
            "balanced": "balanced",
            "high": "high",
            "performance": "low",
            "default": "balanced",
            "quality": "high",
        },
        default=AppConfig.sampling_quality,
    )
    zone_sampling_stride = sampling_quality_to_zone_stride(sampling_quality)

    zones: List[ZoneConfig] = []
    for z in cfg.zones:
        x = max(0.0, min(1.0, float(z.x)))
        y = max(0.0, min(1.0, float(z.y)))
        w = max(0.0, min(1.0, float(z.w)))
        h = max(0.0, min(1.0, float(z.h)))
        if w <= 0.0 or h <= 0.0:
            continue
        zones.append(ZoneConfig(x=x, y=y, w=w, h=h))

    raw_device_zone_count = int(cfg.device_zone_count)
    if raw_device_zone_count > 0:
        device_zone_count = raw_device_zone_count
    else:
        device_zone_count = len(zones) if zones else 8
    output_channel_order = normalize_enum(
        getattr(cfg, "output_channel_order", "grb"),
        allowed={
            "rgb": "rgb",
            "rbg": "rbg",
            "grb": "grb",
            "gbr": "gbr",
            "brg": "brg",
            "bgr": "bgr",
        },
        default="grb",
    )
    zone_offset = int(cfg.zone_offset)
    manual_mapping_enabled = coerce_bool(
        getattr(cfg, "manual_mapping_enabled", AppConfig.manual_mapping_enabled),
        AppConfig.manual_mapping_enabled,
    )
    calibration_model = normalize_enum(
        getattr(cfg, "calibration_model", AppConfig.calibration_model),
        allowed={
            "offset_direction": "offset_direction",
            "offset-direction": "offset_direction",
            "corner_anchored": "corner_anchored",
            "corner-anchored": "corner_anchored",
        },
        default=AppConfig.calibration_model,
    )
    explicit_zone_map = [int(i) for i in cfg.explicit_zone_map] if cfg.explicit_zone_map else []
    corner_anchor_top_left = int(getattr(cfg, "corner_anchor_top_left", -1))
    corner_anchor_top_right = int(getattr(cfg, "corner_anchor_top_right", -1))
    corner_anchor_bottom_right = int(getattr(cfg, "corner_anchor_bottom_right", -1))
    corner_anchor_bottom_left = int(getattr(cfg, "corner_anchor_bottom_left", -1))
    corner_start_anchor = int(getattr(cfg, "corner_start_anchor", -1))
    corner_offsets_enabled = coerce_bool(
        getattr(cfg, "corner_offsets_enabled", AppConfig.corner_offsets_enabled),
        AppConfig.corner_offsets_enabled,
    )
    raw_corner_offsets = getattr(cfg, "corner_zone_offsets", []) or []
    corner_zone_offsets = [int(i) for i in list(raw_corner_offsets)[:4]]
    while len(corner_zone_offsets) < 4:
        corner_zone_offsets.append(0)

    max_consecutive_errors = max(1, int(cfg.max_consecutive_errors))
    reinit_backoff_ms = max(0, int(cfg.reinit_backoff_ms))
    status_log_interval_s = max(0.5, float(cfg.status_log_interval_s))

    prefer_backend = normalize_backend_preference(cfg.prefer_backend)
    auto_probe_policy = normalize_enum(
        getattr(cfg, "auto_probe_policy", AppConfig.auto_probe_policy),
        allowed={
            "first-run": "first-run",
            "first_run": "first-run",
            "each-boot": "each-boot",
            "each_boot": "each-boot",
            "on-change": "on-change",
            "on_change": "on-change",
        },
        default=AppConfig.auto_probe_policy,
    )
    auto_selected_backend = normalize_cached_backend(getattr(cfg, "auto_selected_backend", ""))
    auto_probe_signature = str(getattr(cfg, "auto_probe_signature", "") or "").strip()
    auto_probe_timestamp = str(getattr(cfg, "auto_probe_timestamp", "") or "").strip()
    auto_latency_policy = normalize_enum(
        getattr(cfg, "auto_latency_policy", "manual"),
        allowed={
            "manual": "manual",
            "on-open": "on-open",
            "on_open": "on-open",
            "on-open-once-per-backend": "on-open-once-per-backend",
            "on_open_once_per_backend": "on-open-once-per-backend",
        },
        default="manual",
    )
    latency_last_backend = str(getattr(cfg, "latency_last_backend", "") or "").strip()
    latency_last_value_ms = max(0.0, float(getattr(cfg, "latency_last_value_ms", 0.0) or 0.0))
    latency_last_trigger = str(getattr(cfg, "latency_last_trigger", "") or "").strip()
    latency_last_timestamp = str(getattr(cfg, "latency_last_timestamp", "") or "").strip()
    calibration_validation_confidence = max(
        0.0,
        min(1.0, float(getattr(cfg, "calibration_validation_confidence", 0.0) or 0.0)),
    )
    calibration_validation_summary = str(getattr(cfg, "calibration_validation_summary", "") or "").strip()

    zone_preset = normalize_enum(
        cfg.zone_preset,
        allowed={
            "horizontal": "horizontal",
            "edge": "edge-weighted",
            "edge-weighted": "edge-weighted",
        },
        default=AppConfig.zone_preset,
    )
    edge_sampling_thickness = max(
        0.01,
        min(
            0.5,
            float(getattr(cfg, "edge_sampling_thickness", AppConfig.edge_sampling_thickness)),
        ),
    )
    raw_color_mode = getattr(cfg, "color_mode", AppConfig.color_mode)
    normalized_color_mode = str(raw_color_mode).strip().lower()
    color_mode_allowed = {
        "default": "default",
        "balanced": "balanced",
        "dynamic": "dynamic",
        "hyper": "hyper",
    }
    color_mode = color_mode_allowed.get(normalized_color_mode, AppConfig.color_mode)
    if normalized_color_mode not in color_mode_allowed:
        logger.warning(
            "Unrecognized color_mode=%r; falling back to %r.",
            raw_color_mode,
            AppConfig.color_mode,
        )

    hdr_max_nits = max(80.0, min(10000.0, float(cfg.hdr_max_nits)))
    sdr_boost_nits = max(80.0, min(1000.0, float(getattr(cfg, "sdr_boost_nits", 80.0))))
    hdr_transfer = normalize_enum(
        cfg.hdr_transfer,
        allowed={
            "srgb": "srgb",
            "pq": "pq",
            "st2084": "pq",
        },
        default=AppConfig.hdr_transfer,
    )
    hdr_primaries = normalize_enum(
        cfg.hdr_primaries,
        allowed={
            "bt709": "bt709",
            "srgb": "bt709",
            "bt2020": "bt2020",
        },
        default=AppConfig.hdr_primaries,
    )


    return AppConfig(
        fps=fps,
        prefer_backend=prefer_backend,
        brightness=brightness,
        smoothing=smoothing,
        smoothing_speed=smoothing_speed,
        led_gamma=led_gamma,
        zones=zones,
        zone_sampling_stride=zone_sampling_stride,
        sampling_quality=sampling_quality,
        edge_sampling_thickness=edge_sampling_thickness,
        zone_preset=zone_preset,
        color_mode=color_mode,
        wizard_completed=coerce_bool(getattr(cfg, "wizard_completed", False), False),
        wizard_in_progress_state=str(getattr(cfg, "wizard_in_progress_state", "") or "").strip(),
        hdr_enabled=coerce_bool(getattr(cfg, "hdr_enabled", False), False),
        start_on_launch=coerce_bool(getattr(cfg, "start_on_launch", False), False),
        device_vid=cfg.device_vid,
        device_pid=cfg.device_pid,
        use_mock_capture=coerce_bool(
            getattr(cfg, "use_mock_capture", AppConfig.use_mock_capture), AppConfig.use_mock_capture
        ),
        auto_probe_enabled=coerce_bool(
            getattr(cfg, "auto_probe_enabled", AppConfig.auto_probe_enabled),
            AppConfig.auto_probe_enabled,
        ),
        auto_probe_policy=auto_probe_policy,
        auto_selected_backend=auto_selected_backend,
        auto_probe_signature=auto_probe_signature,
        auto_probe_timestamp=auto_probe_timestamp,
        hdr_max_nits=hdr_max_nits,
        compositor_hdr_mode=coerce_bool(getattr(cfg, "compositor_hdr_mode", False), False),
        sdr_boost_nits=sdr_boost_nits,
        hdr_transfer=hdr_transfer,
        hdr_primaries=hdr_primaries,
        device_zone_count=device_zone_count,
        output_channel_order=output_channel_order,
        zone_offset=zone_offset,
        reverse_zones=coerce_bool(getattr(cfg, "reverse_zones", False), False),
        manual_mapping_enabled=manual_mapping_enabled,
        calibration_model=calibration_model,
        explicit_zone_map=explicit_zone_map,
        corner_anchor_top_left=corner_anchor_top_left,
        corner_anchor_top_right=corner_anchor_top_right,
        corner_anchor_bottom_right=corner_anchor_bottom_right,
        corner_anchor_bottom_left=corner_anchor_bottom_left,
        corner_start_anchor=corner_start_anchor,
        corner_offsets_enabled=corner_offsets_enabled,
        corner_zone_offsets=corner_zone_offsets,
        auto_latency_policy=auto_latency_policy,
        latency_last_backend=latency_last_backend,
        latency_last_value_ms=latency_last_value_ms,
        latency_last_trigger=latency_last_trigger,
        latency_last_timestamp=latency_last_timestamp,
        calibration_validation_confidence=calibration_validation_confidence,
        calibration_validation_summary=calibration_validation_summary,
        max_consecutive_errors=max_consecutive_errors,
        reinit_backoff_ms=reinit_backoff_ms,
        status_log_interval_s=status_log_interval_s,
        verbose=coerce_bool(getattr(cfg, "verbose", False), False),
    )
