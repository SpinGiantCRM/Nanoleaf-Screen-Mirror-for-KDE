from __future__ import annotations

from typing import Any, Dict, List

from nanoleaf_sync.capture.backend_normalization import normalize_capture_backend
from nanoleaf_sync.config.model import AppConfig, ZoneConfig


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
    zone_sampling_stride = max(1, int(cfg.zone_sampling_stride))

    zones: List[ZoneConfig] = []
    for z in cfg.zones:
        x = max(0.0, min(1.0, float(z.x)))
        y = max(0.0, min(1.0, float(z.y)))
        w = max(0.0, min(1.0, float(z.w)))
        h = max(0.0, min(1.0, float(z.h)))
        if w <= 0.0 or h <= 0.0:
            continue
        zones.append(ZoneConfig(x=x, y=y, w=w, h=h))

    device_zone_count = max(0, int(cfg.device_zone_count))
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
    explicit_zone_map = [int(i) for i in cfg.explicit_zone_map] if cfg.explicit_zone_map else []

    max_consecutive_errors = max(1, int(cfg.max_consecutive_errors))
    reinit_backoff_ms = max(0, int(cfg.reinit_backoff_ms))
    status_log_interval_s = max(0.5, float(cfg.status_log_interval_s))

    prefer_backend = normalize_capture_backend(
        cfg.prefer_backend,
        default=AppConfig.prefer_backend,
    )
    zone_preset = normalize_enum(
        cfg.zone_preset,
        allowed={
            "horizontal": "horizontal",
            "edge": "edge-weighted",
            "edge-weighted": "edge-weighted",
        },
        default=AppConfig.zone_preset,
    )
    color_mode = normalize_enum(
        getattr(cfg, "color_mode", AppConfig.color_mode),
        allowed={
            "default": "default",
            "balanced": "balanced",
            "dynamic": "dynamic",
            "hyper": "hyper",
            "vibrant": "dynamic",
        },
        default=AppConfig.color_mode,
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
        zone_preset=zone_preset,
        color_mode=color_mode,
        wizard_completed=coerce_bool(getattr(cfg, "wizard_completed", False), False),
        hdr_enabled=coerce_bool(getattr(cfg, "hdr_enabled", False), False),
        start_on_launch=coerce_bool(getattr(cfg, "start_on_launch", False), False),
        device_vid=cfg.device_vid,
        device_pid=cfg.device_pid,
        use_mock_capture=coerce_bool(getattr(cfg, "use_mock_capture", AppConfig.use_mock_capture), AppConfig.use_mock_capture),
        hdr_max_nits=hdr_max_nits,
        compositor_hdr_mode=coerce_bool(getattr(cfg, "compositor_hdr_mode", False), False),
        sdr_boost_nits=sdr_boost_nits,
        hdr_transfer=hdr_transfer,
        hdr_primaries=hdr_primaries,
        device_zone_count=device_zone_count,
        output_channel_order=output_channel_order,
        zone_offset=zone_offset,
        reverse_zones=coerce_bool(getattr(cfg, "reverse_zones", False), False),
        explicit_zone_map=explicit_zone_map,
        max_consecutive_errors=max_consecutive_errors,
        reinit_backoff_ms=reinit_backoff_ms,
        status_log_interval_s=status_log_interval_s,
        verbose=coerce_bool(getattr(cfg, "verbose", False), False),
    )
