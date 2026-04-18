from __future__ import annotations

from typing import Any, Dict, List

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
    zone_offset = int(cfg.zone_offset)
    explicit_zone_map = [int(i) for i in cfg.explicit_zone_map] if cfg.explicit_zone_map else []

    max_consecutive_errors = max(1, int(cfg.max_consecutive_errors))
    reinit_backoff_ms = max(0, int(cfg.reinit_backoff_ms))
    status_log_interval_s = max(0.5, float(cfg.status_log_interval_s))

    prefer_backend = normalize_enum(
        cfg.prefer_backend,
        allowed={
            "kwin-dbus": "kwin-dbus",
            "kwin_dbus": "kwin-dbus",
            "kwin-dbus-screenshot": "kwin-dbus",
        },
        default=AppConfig.prefer_backend,
    )

    return AppConfig(
        fps=fps,
        prefer_backend=prefer_backend,
        brightness=brightness,
        smoothing=smoothing,
        zones=zones,
        zone_sampling_stride=zone_sampling_stride,
        device_vid=cfg.device_vid,
        device_pid=cfg.device_pid,
        use_mock_device=cfg.use_mock_device,
        use_mock_capture=cfg.use_mock_capture,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=cfg.reverse_zones,
        explicit_zone_map=explicit_zone_map,
        max_consecutive_errors=max_consecutive_errors,
        reinit_backoff_ms=reinit_backoff_ms,
        status_log_interval_s=status_log_interval_s,
        verbose=cfg.verbose,
    )
