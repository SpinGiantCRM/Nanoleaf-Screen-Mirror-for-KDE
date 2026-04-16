from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


def _default_config_path() -> Path:
    # Match the requirement: ~/.config/nanoleaf-kde-sync/config.json
    return Path.home() / ".config" / "nanoleaf-kde-sync" / "config.json"


def _coerce_bool(value: Any, default: bool) -> bool:
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


def _normalize_enum(value: Any, *, allowed: Dict[str, str], default: str) -> str:
    normalized = str(value).strip().lower()
    return allowed.get(normalized, default)


@dataclass
class ZoneConfig:
    """
    Zone rectangles expressed in normalized screen coordinates.

    Values are floats in [0, 1]:
    - x, y: top-left corner
    - w, h: width/height
    """

    x: float
    y: float
    w: float
    h: float


@dataclass
class AppConfig:
    # Capture
    fps: int = 30
    prefer_backend: str = "kmsgrab"  # "kmsgrab" or "kwin-dbus" or "auto" or "replay"
    replay_frames_path: str = ""

    # Color -> device mapping
    brightness: float = 1.0  # [0.0, 1.0]
    smoothing: float = 0.5  # EMA alpha in [0.0, 1.0]; higher = less smoothing

    # Zones
    zones: List[ZoneConfig] = field(default_factory=list)
    # If zones is empty, the service will use a default single full-screen zone.

    # USB / device
    device_vid: int = 0x0
    device_pid: int = 0x0
    # Default to mock device so the app runs without requiring HID hardware/protocol.
    use_mock_device: bool = True

    # Capture backend (development/demo).
    # Default to mock capture so the full pipeline can be tested immediately
    # even before DRM/KWin capture bindings are implemented.
    use_mock_capture: bool = True

    # If true, the kmsgrab-style backend may fall back to KWin D-Bus capture
    # when DRM/KMS bindings are unavailable or fail at runtime.
    allow_capture_fallback: bool = True

    # Device zone calibration (mapping sampled screen zones to physical strip zones)
    # If 0, the service uses `len(zones)` (or 1 if zones are empty).
    device_zone_count: int = 0
    zone_offset: int = 0
    reverse_zones: bool = False
    # Optional explicit mapping: list of screen-zone indices for each device zone.
    # If non-empty, it takes precedence over `zone_offset`/`reverse_zones`.
    explicit_zone_map: List[int] = field(default_factory=list)

    # HDR assumptions / defaults.
    # If a capture backend doesn't provide HDR metadata, these values are used
    # to select transfer function + primaries and for tone mapping scaling.
    hdr_max_nits: float = 1000.0
    hdr_transfer: str = "srgb"  # "srgb" | "pq" | "hlg" | "linear"
    hdr_primaries: str = "bt709"  # "bt709" | "bt2020"

    # Recovery policy
    max_consecutive_errors: int = 5
    reinit_backoff_ms: int = 500

    # Logging / misc
    status_log_interval_s: float = 5.0
    verbose: bool = False


class ConfigManager:
    def __init__(self, path: Optional[os.PathLike[str] | str] = None) -> None:
        self.path = Path(path) if path is not None else _default_config_path()

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()

        raw = self.path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            # Config corruption should not prevent the app from starting.
            return AppConfig()

        # Parse zones (normalized rectangles)
        zones_data = data.get("zones", [])
        zones: List[ZoneConfig] = []
        for z in zones_data:
            try:
                zones.append(
                    ZoneConfig(
                        x=float(z["x"]),
                        y=float(z["y"]),
                        w=float(z["w"]),
                        h=float(z["h"]),
                    )
                )
            except Exception:
                # Ignore malformed zones entries; defaults will apply.
                continue

        # Construct with fallbacks
        cfg = AppConfig(
            fps=int(data.get("fps", AppConfig.fps)),
            prefer_backend=str(data.get("prefer_backend", AppConfig.prefer_backend)),
            replay_frames_path=str(
                data.get("replay_frames_path", AppConfig.replay_frames_path)
            ),
            brightness=float(data.get("brightness", AppConfig.brightness)),
            smoothing=float(data.get("smoothing", AppConfig.smoothing)),
            zones=zones,
            device_vid=int(data.get("device_vid", AppConfig.device_vid)),
            device_pid=int(data.get("device_pid", AppConfig.device_pid)),
            use_mock_device=_coerce_bool(
                data.get("use_mock_device"), AppConfig.use_mock_device
            ),
            use_mock_capture=_coerce_bool(
                data.get("use_mock_capture"), AppConfig.use_mock_capture
            ),
            allow_capture_fallback=_coerce_bool(
                data.get("allow_capture_fallback"), AppConfig.allow_capture_fallback
            ),
            device_zone_count=int(
                data.get("device_zone_count", AppConfig.device_zone_count)
            ),
            zone_offset=int(data.get("zone_offset", AppConfig.zone_offset)),
            reverse_zones=_coerce_bool(
                data.get("reverse_zones"), AppConfig.reverse_zones
            ),
            explicit_zone_map=[
                int(x) for x in data.get("explicit_zone_map", [])
            ],
            hdr_max_nits=float(data.get("hdr_max_nits", AppConfig.hdr_max_nits)),
            hdr_transfer=str(data.get("hdr_transfer", AppConfig.hdr_transfer)),
            hdr_primaries=str(data.get("hdr_primaries", AppConfig.hdr_primaries)),
            max_consecutive_errors=int(
                data.get("max_consecutive_errors", AppConfig.max_consecutive_errors)
            ),
            reinit_backoff_ms=int(
                data.get("reinit_backoff_ms", AppConfig.reinit_backoff_ms)
            ),
            status_log_interval_s=float(
                data.get("status_log_interval_s", AppConfig.status_log_interval_s)
            ),
            verbose=_coerce_bool(data.get("verbose"), AppConfig.verbose),
        )

        return self._validate_config(cfg)

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        cfg = self._validate_config(config)

        # JSON-serialize dataclasses
        payload: Dict[str, Any] = asdict(cfg)
        # Convert ZoneConfig dataclasses into simple dicts
        payload["zones"] = [asdict(z) for z in cfg.zones]

        encoded = json.dumps(payload, indent=2, sort_keys=True)

        # Atomic save: write temp file in same directory and replace.
        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                dir=str(self.path.parent),
                prefix=self.path.name + ".tmp.",
                suffix=".json",
            ) as f:
                tmp_path = Path(f.name)
                f.write(encoded)
                f.flush()
                os.fsync(f.fileno())

            os.replace(str(tmp_path), str(self.path))
        finally:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

    def _validate_config(self, cfg: AppConfig) -> AppConfig:
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

        explicit_zone_map = (
            [int(i) for i in cfg.explicit_zone_map] if cfg.explicit_zone_map else []
        )

        max_consecutive_errors = max(1, int(cfg.max_consecutive_errors))
        reinit_backoff_ms = max(0, int(cfg.reinit_backoff_ms))
        status_log_interval_s = max(0.5, float(cfg.status_log_interval_s))

        prefer_backend = _normalize_enum(
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
        hdr_transfer = _normalize_enum(
            cfg.hdr_transfer,
            allowed={
                "srgb": "srgb",
                "pq": "pq",
                "hlg": "hlg",
                "linear": "linear",
            },
            default=AppConfig.hdr_transfer,
        )
        hdr_primaries = _normalize_enum(
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
