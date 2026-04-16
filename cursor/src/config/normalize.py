from __future__ import annotations

from typing import Any, Dict, List

from config.model import AppConfig, ZoneConfig


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
    # Clamp core performance/brightness knobs to keep behavior predictable.
    brightness = float(cfg.brightness)
    brightness = max(0.0, min(1.0, brightness))

    smoothing = float(cfg.smoothing)
    smoothing = max(0.0, min(1.0, smoothing))

    fps = int(cfg.fps)
    fps = max(1, min(60, fps))

    zones: List[ZoneConfig] = []
    for z in cfg.zones:
        x = max(0.0, min(1.0, float(z.x)))
        y = max(0.0, min(1.0, float(z.y)))
        w = max(0.0, min(1.0, float(z.w)))
        h = max(0.0, min(1.0, float(z.h)))
        # If w/h clamp to 0, drop zones to avoid empty rectangles.
        if w <= 0.0 or h <= 0.0:
            continue
        zones.append(ZoneConfig(x=x, y=y, w=w, h=h))

    device_zone_count = int(cfg.device_zone_count)
    if device_zone_count < 0:
        device_zone_count = 0

    zone_offset = int(cfg.zone_offset)

    # Clamp HDR defaults to plausible ranges.
    hdr_max_nits = float(cfg.hdr_max_nits)
    hdr_max_nits = max(1.0, min(10_000.0, hdr_max_nits))

    explicit_zone_map = [int(i) for i in cfg.explicit_zone_map] if cfg.explicit_zone_map else []

    max_consecutive_errors = max(1, int(cfg.max_consecutive_errors))
    reinit_backoff_ms = max(0, int(cfg.reinit_backoff_ms))
    status_log_interval_s = max(0.5, float(cfg.status_log_interval_s))

    prefer_backend = normalize_enum(
        cfg.prefer_backend,
        allowed={
            "auto": "auto",
            "kmsgrab": "kmsgrab",
            "kwin-dbus": "kwin-dbus",
            "kwin_dbus": "kwin-dbus",
            "kwin-dbus-screenshot": "kwin-dbus-screenshot",
            "replay": "replay",
        },
        default=AppConfig.prefer_backend,
    )
    hdr_transfer = normalize_enum(
        cfg.hdr_transfer,
        allowed={
            "srgb": "srgb",
            "pq": "pq",
            "hlg": "hlg",
            "linear": "linear",
        },
        default=AppConfig.hdr_transfer,
    )
    hdr_primaries = normalize_enum(
        cfg.hdr_primaries,
        allowed={
            "bt709": "bt709",
            "bt2020": "bt2020",
        },
        default=AppConfig.hdr_primaries,
    )

    return AppConfig(
        fps=fps,
        prefer_backend=prefer_backend,
        replay_frames_path=str(cfg.replay_frames_path or ""),
        brightness=brightness,
        smoothing=smoothing,
        zones=zones,
        device_vid=cfg.device_vid,
        device_pid=cfg.device_pid,
        use_mock_device=cfg.use_mock_device,
        use_mock_capture=cfg.use_mock_capture,
        allow_capture_fallback=cfg.allow_capture_fallback,
        device_zone_count=device_zone_count,
        zone_offset=zone_offset,
        reverse_zones=cfg.reverse_zones,
        explicit_zone_map=explicit_zone_map,
        hdr_max_nits=hdr_max_nits,
        hdr_transfer=hdr_transfer,
        hdr_primaries=hdr_primaries,
        max_consecutive_errors=max_consecutive_errors,
        reinit_backoff_ms=reinit_backoff_ms,
        status_log_interval_s=status_log_interval_s,
        verbose=cfg.verbose,
    )
