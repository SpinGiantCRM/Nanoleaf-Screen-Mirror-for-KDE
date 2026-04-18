from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.config.normalize import coerce_bool, validate_config


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_str(value: Any, default: str) -> str:
    if value is None:
        return default
    return str(value)


def _to_int_list(value: Any, default: list[int]) -> list[int]:
    if value is None:
        return default
    if not isinstance(value, list):
        return default
    converted: list[int] = []
    for item in value:
        try:
            converted.append(int(item))
        except (TypeError, ValueError):
            continue
    return converted


def default_config_path() -> Path:
    # Match the requirement: ~/.config/nanoleaf-kde-sync/config.json
    return Path.home() / ".config" / "nanoleaf-kde-sync" / "config.json"


def mode_config(mode: str) -> AppConfig:
    normalized = (mode or "").strip().lower()
    if normalized in ("capture-real", "real-capture-mock-device", ""):
        return validate_config(
            AppConfig(
                use_mock_capture=False,
                use_mock_device=True,
                prefer_backend="kwin-dbus",
            )
        )
    if normalized in ("full-mock", "mock"):
        return validate_config(AppConfig(use_mock_capture=True, use_mock_device=True))
    if normalized in ("full-real", "real"):
        return validate_config(
            AppConfig(
                use_mock_capture=False,
                use_mock_device=False,
                prefer_backend="kwin-dbus",
                device_vid=0x37FA,
                device_pid=0x8202,
            )
        )
    raise ValueError(
        f"Unsupported mode '{mode}'. Expected one of: full-mock, capture-real, full-real."
    )


class ConfigManager:
    def __init__(self, path: Optional[os.PathLike[str] | str] = None) -> None:
        self.path = Path(path) if path is not None else default_config_path()

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()

        raw = self.path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            # Config corruption should not prevent the app from starting.
            return AppConfig()

        if not isinstance(data, dict):
            return AppConfig()

        zones_data = data.get("zones", [])
        zones: List[ZoneConfig] = []
        for z in zones_data if isinstance(zones_data, list) else []:
            try:
                zones.append(
                    ZoneConfig(
                        x=_to_float(z["x"], 0.0),
                        y=_to_float(z["y"], 0.0),
                        w=_to_float(z["w"], 0.0),
                        h=_to_float(z["h"], 0.0),
                    )
                )
            except Exception:
                # Ignore malformed zones entries; defaults will apply.
                continue

        cfg = AppConfig(
            fps=_to_int(data.get("fps"), AppConfig.fps),
            prefer_backend=_to_str(data.get("prefer_backend"), AppConfig.prefer_backend),
            brightness=_to_float(data.get("brightness"), AppConfig.brightness),
            smoothing=_to_float(data.get("smoothing"), AppConfig.smoothing),
            zones=zones,
            zone_sampling_stride=_to_int(
                data.get("zone_sampling_stride"), AppConfig.zone_sampling_stride
            ),
            device_vid=_to_int(data.get("device_vid"), AppConfig.device_vid),
            device_pid=_to_int(data.get("device_pid"), AppConfig.device_pid),
            use_mock_device=coerce_bool(data.get("use_mock_device"), AppConfig.use_mock_device),
            use_mock_capture=coerce_bool(data.get("use_mock_capture"), AppConfig.use_mock_capture),
            hdr_max_nits=_to_float(data.get("hdr_max_nits"), AppConfig.hdr_max_nits),
            hdr_transfer=_to_str(data.get("hdr_transfer"), AppConfig.hdr_transfer),
            hdr_primaries=_to_str(data.get("hdr_primaries"), AppConfig.hdr_primaries),
            device_zone_count=_to_int(data.get("device_zone_count"), AppConfig.device_zone_count),
            zone_offset=_to_int(data.get("zone_offset"), AppConfig.zone_offset),
            reverse_zones=coerce_bool(data.get("reverse_zones"), AppConfig.reverse_zones),
            explicit_zone_map=_to_int_list(data.get("explicit_zone_map"), []),
            max_consecutive_errors=_to_int(
                data.get("max_consecutive_errors"), AppConfig.max_consecutive_errors
            ),
            reinit_backoff_ms=_to_int(data.get("reinit_backoff_ms"), AppConfig.reinit_backoff_ms),
            status_log_interval_s=_to_float(
                data.get("status_log_interval_s"), AppConfig.status_log_interval_s
            ),
            verbose=coerce_bool(data.get("verbose"), AppConfig.verbose),
        )

        return validate_config(cfg)

    def exists(self) -> bool:
        return self.path.exists()

    def initialize(self, *, mode: str = "capture-real", force: bool = False) -> bool:
        if self.path.exists() and not force:
            return False
        self.save(mode_config(mode))
        return True

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        cfg = validate_config(config)

        payload: Dict[str, Any] = asdict(cfg)
        payload["zones"] = [asdict(z) for z in cfg.zones]
        payload["zone_sampling_stride"] = int(cfg.zone_sampling_stride)

        encoded = json.dumps(payload, indent=2, sort_keys=True)

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
