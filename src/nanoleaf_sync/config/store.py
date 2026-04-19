from __future__ import annotations

import json
import os
import tempfile
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from dacite import Config as DaciteConfig
from dacite import from_dict

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.normalize import validate_config


def _dump_toml(payload: Dict[str, Any]) -> str:
    try:
        import tomli_w

        return tomli_w.dumps(payload)
    except Exception:
        lines: list[str] = []
        for key, value in payload.items():
            if key == "zones" and isinstance(value, list):
                for zone in value:
                    lines.append("[[zones]]")
                    for zone_k, zone_v in zone.items():
                        lines.append(f"{zone_k} = {float(zone_v)}")
                    lines.append("")
                continue
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            elif isinstance(value, str):
                rendered = json.dumps(value)
            elif isinstance(value, list):
                rendered = "[" + ", ".join(str(int(v)) for v in value) + "]"
            else:
                rendered = str(value)
            lines.append(f"{key} = {rendered}")
        return "\n".join(lines).rstrip() + "\n"


def default_config_path() -> Path:
    # Match the requirement: ~/.config/nanoleaf-kde-sync/config.toml
    return Path.home() / ".config" / "nanoleaf-kde-sync" / "config.toml"


def mode_config(mode: str) -> AppConfig:
    normalized = (mode or "").strip().lower()
    if not normalized:
        raise ValueError("mode cannot be empty. Expected one of: full-real, diagnostic.")
    if normalized in ("full-real", "real", "capture-real"):
        return validate_config(AppConfig(use_mock_capture=False, prefer_backend="auto"))
    if normalized in ("diagnostic", "diag", "full-mock", "mock"):
        return validate_config(AppConfig(use_mock_capture=True, prefer_backend="auto"))
    raise ValueError(
        f"Unsupported mode '{mode}'. Expected one of: full-real, diagnostic."
    )


class ConfigManager:
    def __init__(self, path: Optional[os.PathLike[str] | str] = None) -> None:
        self.path = Path(path) if path is not None else default_config_path()

    def _legacy_json_path(self) -> Path:
        if self.path.suffix.lower() == ".json":
            return self.path
        return self.path.with_name("config.json")

    def _migrate_json_if_present(self) -> None:
        if self.path.exists():
            return
        old_path = self._legacy_json_path()
        if not old_path.exists():
            return

        try:
            raw = old_path.read_text(encoding="utf-8")
            parsed = json.loads(raw) if raw.strip() else {}
            if not isinstance(parsed, dict):
                return
            cfg = validate_config(
                from_dict(data_class=AppConfig, data=parsed, config=DaciteConfig(strict=False, cast=[int, float, str, bool]))
            )
            self.save(cfg)
            old_path.rename(old_path.with_suffix(".json.bak"))
        except Exception:
            # Corrupt migrations should not prevent startup.
            return

    def load(self) -> AppConfig:
        self._migrate_json_if_present()
        if not self.path.exists():
            return AppConfig()

        raw = self.path.read_text(encoding="utf-8")
        try:
            data = tomllib.loads(raw) if raw.strip() else {}
        except tomllib.TOMLDecodeError:
            # Config corruption should not prevent the app from starting.
            return AppConfig()

        if not isinstance(data, dict):
            return AppConfig()

        try:
            cfg = from_dict(
                data_class=AppConfig,
                data=data,
                config=DaciteConfig(strict=False, cast=[int, float, str, bool]),
            )
        except Exception:
            return AppConfig()
        return validate_config(cfg)

    def exists(self) -> bool:
        return self.path.exists()

    def initialize(self, *, mode: str = "full-real", force: bool = False) -> bool:
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

        encoded = _dump_toml(payload)

        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                dir=str(self.path.parent),
                prefix=self.path.name + ".tmp.",
                suffix=".toml",
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
