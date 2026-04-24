from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from nanoleaf_sync.capture.backend_selection import normalize_backend_preference, normalize_cached_backend
from nanoleaf_sync.config.model import AppConfig, CalibrationConfig, ZoneConfig
from nanoleaf_sync.config.presets import (
    COLOR_STYLE_PRESETS,
    DISPLAY_PRESETS,
    EDGE_LOCALITY_PRESETS,
    LAYOUT_PRESETS,
    MOTION_PRESETS,
    SAMPLING_QUALITY_PRESETS,
    normalize_layout_preset,
    normalize_preset,
    sampling_quality_to_zone_stride as sampling_quality_to_zone_stride_impl,
)

logger = logging.getLogger(__name__)
CURRENT_CALIBRATION_SCHEMA_VERSION = 1


def sampling_quality_to_zone_stride(quality: str) -> int:
    return sampling_quality_to_zone_stride_impl(quality)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


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


def normalize_wizard_in_progress_state(raw_value: Any) -> str:
    raw_text = str(raw_value or "").strip()
    if not raw_text:
        return ""
    try:
        payload = json.loads(raw_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return raw_text
    if not isinstance(payload, dict):
        return raw_text
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def migrate_config_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    migrated: Dict[str, Any] = dict(data)
    calibration_payload = migrated.get("calibration")
    calibration = dict(calibration_payload) if isinstance(calibration_payload, dict) else {}

    calibration_schema_version = _coerce_int(
        migrated.get("calibration_schema_version", calibration.get("schema_version", CURRENT_CALIBRATION_SCHEMA_VERSION)),
        CURRENT_CALIBRATION_SCHEMA_VERSION,
    )
    calibration_schema_version = max(1, calibration_schema_version)
    calibration["calibration_model"] = "corner_anchored"
    migrated["calibration_model"] = "corner_anchored"
    calibration["schema_version"] = calibration_schema_version
    calibration["calibration_schema_version"] = calibration_schema_version
    migrated["calibration_schema_version"] = calibration_schema_version
    migrated["calibration"] = calibration
    return migrated


def validate_config(cfg: AppConfig) -> AppConfig:
    brightness = max(0.0, min(1.0, float(cfg.brightness)))
    smoothing = max(0.0, min(1.0, float(cfg.smoothing)))
    smoothing_speed = max(0.0, min(4.0, float(cfg.smoothing_speed)))
    led_gamma = max(1.0, min(4.0, float(cfg.led_gamma)))
    fps = max(1, min(120, int(cfg.fps)))

    sampling_quality = normalize_preset(getattr(cfg, "sampling_quality", AppConfig.sampling_quality), allowed=SAMPLING_QUALITY_PRESETS, default=AppConfig.sampling_quality)
    zone_sampling_stride = sampling_quality_to_zone_stride(sampling_quality)
    layout_preset = normalize_layout_preset(getattr(cfg, "layout_preset", AppConfig.layout_preset))
    edge_locality = normalize_preset(getattr(cfg, "edge_locality", AppConfig.edge_locality), allowed=EDGE_LOCALITY_PRESETS, default=AppConfig.edge_locality)
    motion_preset = normalize_preset(getattr(cfg, "motion_preset", AppConfig.motion_preset), allowed=MOTION_PRESETS, default=AppConfig.motion_preset)
    color_style = normalize_preset(getattr(cfg, "color_style", AppConfig.color_style), allowed=COLOR_STYLE_PRESETS, default=AppConfig.color_style)
    display_preset = normalize_preset(getattr(cfg, "display_preset", AppConfig.display_preset), allowed=DISPLAY_PRESETS, default=AppConfig.display_preset)

    zones: List[ZoneConfig] = []
    for z in cfg.zones:
        x = max(0.0, min(1.0, float(z.x)))
        y = max(0.0, min(1.0, float(z.y)))
        w = max(0.0, min(1.0, float(z.w)))
        h = max(0.0, min(1.0, float(z.h)))
        if w <= 0.0 or h <= 0.0:
            continue
        zones.append(ZoneConfig(x=x, y=y, w=w, h=h))

    raw_calibration = cfg.calibration or CalibrationConfig()
    calibration_schema_version = max(1, _coerce_int(getattr(cfg, "calibration_schema_version", getattr(raw_calibration, "schema_version", 1)), 1))
    raw_device_zone_count = int(getattr(raw_calibration, "device_zone_count", 0))
    device_zone_count = raw_device_zone_count if raw_device_zone_count > 0 else (len(zones) if zones else 0)

    output_channel_order = normalize_enum(getattr(raw_calibration, "output_channel_order", "grb"), allowed={"rgb": "rgb", "rbg": "rbg", "grb": "grb", "gbr": "gbr", "brg": "brg", "bgr": "bgr"}, default="grb")
    calibration_model = "corner_anchored"
    corner_anchor_top_left = int(getattr(raw_calibration, "corner_anchor_top_left", -1))
    corner_anchor_top_right = int(getattr(raw_calibration, "corner_anchor_top_right", -1))
    corner_anchor_bottom_right = int(getattr(raw_calibration, "corner_anchor_bottom_right", -1))
    corner_anchor_bottom_left = int(getattr(raw_calibration, "corner_anchor_bottom_left", -1))
    normalized_corner_anchors = [int(i) for i in list(getattr(raw_calibration, "normalized_corner_anchors", []) or [])[:4]]
    while len(normalized_corner_anchors) < 4:
        normalized_corner_anchors.append(-1)
    normalized_reverse_zones = coerce_bool(getattr(raw_calibration, "normalized_reverse_zones", coerce_bool(getattr(raw_calibration, "reverse_zones", False), False)), coerce_bool(getattr(raw_calibration, "reverse_zones", False), False))

    normalized_calibration = CalibrationConfig(
        schema_version=calibration_schema_version,
        calibration_schema_version=calibration_schema_version,
        calibration_model=calibration_model,
        device_zone_count=device_zone_count,
        output_channel_order=output_channel_order,
        normalized_reverse_zones=normalized_reverse_zones,
        normalized_corner_anchors=normalized_corner_anchors,
        reverse_zones=coerce_bool(getattr(raw_calibration, "reverse_zones", False), False),
        corner_anchor_top_left=corner_anchor_top_left,
        corner_anchor_top_right=corner_anchor_top_right,
        corner_anchor_bottom_right=corner_anchor_bottom_right,
        corner_anchor_bottom_left=corner_anchor_bottom_left,
    )

    prefer_backend = normalize_backend_preference(cfg.prefer_backend)
    auto_probe_policy = normalize_enum(getattr(cfg, "auto_probe_policy", AppConfig.auto_probe_policy), allowed={"first-run": "first-run", "first_run": "first-run", "each-boot": "each-boot", "each_boot": "each-boot", "on-change": "on-change", "on_change": "on-change"}, default=AppConfig.auto_probe_policy)

    return AppConfig(
        fps=fps,
        prefer_backend=prefer_backend,
        brightness=brightness,
        smoothing=smoothing,
        smoothing_speed=smoothing_speed,
        led_gamma=led_gamma,
        zones=zones,
        zone_sampling_stride=zone_sampling_stride,
        layout_preset=layout_preset,
        edge_locality=edge_locality,
        sampling_quality=sampling_quality,
        motion_preset=motion_preset,
        color_style=color_style,
        display_preset=display_preset,
        wizard_completed=coerce_bool(getattr(cfg, "wizard_completed", False), False),
        wizard_in_progress_state=normalize_wizard_in_progress_state(getattr(cfg, "wizard_in_progress_state", "")),
        start_on_launch=coerce_bool(getattr(cfg, "start_on_launch", False), False),
        device_vid=cfg.device_vid,
        device_pid=cfg.device_pid,
        use_mock_capture=coerce_bool(getattr(cfg, "use_mock_capture", AppConfig.use_mock_capture), AppConfig.use_mock_capture),
        auto_probe_enabled=coerce_bool(getattr(cfg, "auto_probe_enabled", AppConfig.auto_probe_enabled), AppConfig.auto_probe_enabled),
        auto_probe_policy=auto_probe_policy,
        auto_selected_backend=normalize_cached_backend(getattr(cfg, "auto_selected_backend", "")),
        auto_probe_signature=str(getattr(cfg, "auto_probe_signature", "") or "").strip(),
        auto_probe_timestamp=str(getattr(cfg, "auto_probe_timestamp", "") or "").strip(),
        hdr_max_nits=max(80.0, min(10000.0, float(cfg.hdr_max_nits))),
        compositor_hdr_mode=coerce_bool(getattr(cfg, "compositor_hdr_mode", False), False),
        sdr_boost_nits=max(80.0, min(1000.0, float(getattr(cfg, "sdr_boost_nits", 80.0)))),
        hdr_transfer=normalize_enum(cfg.hdr_transfer, allowed={"srgb": "srgb", "pq": "pq", "st2084": "pq"}, default=AppConfig.hdr_transfer),
        hdr_primaries=normalize_enum(cfg.hdr_primaries, allowed={"bt709": "bt709", "srgb": "bt709", "bt2020": "bt2020"}, default=AppConfig.hdr_primaries),
        calibration_schema_version=calibration_schema_version,
        calibration=normalized_calibration,
        device_zone_count=device_zone_count,
        output_channel_order=output_channel_order,
        reverse_zones=normalized_calibration.reverse_zones,
        calibration_model=calibration_model,
        corner_anchor_top_left=corner_anchor_top_left,
        corner_anchor_top_right=corner_anchor_top_right,
        corner_anchor_bottom_right=corner_anchor_bottom_right,
        corner_anchor_bottom_left=corner_anchor_bottom_left,
        auto_latency_policy=normalize_enum(getattr(cfg, "auto_latency_policy", "manual"), allowed={"manual": "manual", "on-open": "on-open", "on_open": "on-open", "on-open-once-per-backend": "on-open-once-per-backend", "on_open_once_per_backend": "on-open-once-per-backend"}, default="manual"),
        latency_last_backend=str(getattr(cfg, "latency_last_backend", "") or "").strip(),
        latency_last_value_ms=max(0.0, float(getattr(cfg, "latency_last_value_ms", 0.0) or 0.0)),
        latency_last_trigger=str(getattr(cfg, "latency_last_trigger", "") or "").strip(),
        latency_last_timestamp=str(getattr(cfg, "latency_last_timestamp", "") or "").strip(),
        max_consecutive_errors=max(1, int(cfg.max_consecutive_errors)),
        reinit_backoff_ms=max(0, int(cfg.reinit_backoff_ms)),
        status_log_interval_s=max(0.5, float(cfg.status_log_interval_s)),
        verbose=coerce_bool(getattr(cfg, "verbose", False), False),
    )
