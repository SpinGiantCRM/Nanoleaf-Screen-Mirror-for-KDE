from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from nanoleaf_sync.config.model import AppConfig, ZoneConfig
from nanoleaf_sync.config.normalize import coerce_bool, validate_config


def default_config_path() -> Path:
    # Match the requirement: ~/.config/nanoleaf-kde-sync/config.json
    return Path.home() / ".config" / "nanoleaf-kde-sync" / "config.json"


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

        cfg = AppConfig(
            fps=int(data.get("fps", AppConfig.fps)),
            prefer_backend=str(data.get("prefer_backend", AppConfig.prefer_backend)),
            replay_frames_path=str(data.get("replay_frames_path", AppConfig.replay_frames_path)),
            brightness=float(data.get("brightness", AppConfig.brightness)),
            smoothing=float(data.get("smoothing", AppConfig.smoothing)),
            zones=zones,
            device_vid=int(data.get("device_vid", AppConfig.device_vid)),
            device_pid=int(data.get("device_pid", AppConfig.device_pid)),
            use_mock_device=coerce_bool(data.get("use_mock_device"), AppConfig.use_mock_device),
            use_mock_capture=coerce_bool(data.get("use_mock_capture"), AppConfig.use_mock_capture),
            allow_capture_fallback=coerce_bool(
                data.get("allow_capture_fallback"), AppConfig.allow_capture_fallback
            ),
            device_zone_count=int(data.get("device_zone_count", AppConfig.device_zone_count)),
            zone_offset=int(data.get("zone_offset", AppConfig.zone_offset)),
            reverse_zones=coerce_bool(data.get("reverse_zones"), AppConfig.reverse_zones),
            explicit_zone_map=[int(x) for x in data.get("explicit_zone_map", [])],
            hdr_max_nits=float(data.get("hdr_max_nits", AppConfig.hdr_max_nits)),
            hdr_transfer=str(data.get("hdr_transfer", AppConfig.hdr_transfer)),
            hdr_primaries=str(data.get("hdr_primaries", AppConfig.hdr_primaries)),
            max_consecutive_errors=int(
                data.get("max_consecutive_errors", AppConfig.max_consecutive_errors)
            ),
            reinit_backoff_ms=int(data.get("reinit_backoff_ms", AppConfig.reinit_backoff_ms)),
            status_log_interval_s=float(
                data.get("status_log_interval_s", AppConfig.status_log_interval_s)
            ),
            verbose=coerce_bool(data.get("verbose"), AppConfig.verbose),
        )

        return validate_config(cfg)

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        cfg = validate_config(config)

        payload: Dict[str, Any] = asdict(cfg)
        payload["zones"] = [asdict(z) for z in cfg.zones]

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
