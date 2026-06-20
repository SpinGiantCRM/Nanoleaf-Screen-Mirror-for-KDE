from __future__ import annotations

import fcntl
import logging
import os
import tempfile
import tomllib
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from dacite import Config as DaciteConfig
from dacite import from_dict

from nanoleaf_sync.config.model import AppConfig, CalibrationConfig
from nanoleaf_sync.config.normalize import (
    migrate_config_dict,
    validate_config,
    validate_raw_config_values,
)
from nanoleaf_sync.config.serialization import dump_toml


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
    raise ValueError(f"Unsupported mode '{mode}'. Expected one of: full-real, diagnostic.")


class ConfigManager:
    def __init__(self, path: os.PathLike[str] | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_config_path()
        self._config: AppConfig | None = None

    def _migrate_json_if_present(self) -> None:
        return

    def load(self) -> AppConfig:
        self._migrate_json_if_present()
        if not self.path.exists():
            self._config = AppConfig()
            return self._config

        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(
                "Config file unreadable at %s; using defaults: %s",
                self.path,
                exc,
            )
            self._config = AppConfig()
            return self._config
        try:
            data = tomllib.loads(raw) if raw.strip() else {}
        except tomllib.TOMLDecodeError as exc:
            logger.warning(
                "Config file corrupted at %s; using defaults: %s",
                self.path,
                exc,
            )
            self._config = AppConfig()
            return self._config

        if not isinstance(data, dict):
            logger.warning(
                "Config file has invalid top-level structure at %s; using defaults",
                self.path,
            )
            self._config = AppConfig()
            return self._config

        validate_raw_config_values(data)
        raw_use_mock_capture = bool(data.get("use_mock_capture", False))
        migrated_data = migrate_config_dict(data)
        try:
            cfg = from_dict(
                data_class=AppConfig,
                data=migrated_data,
                config=DaciteConfig(strict=False, cast=[int, float, str, bool]),
            )
        except Exception:
            logger.exception("Failed to deserialize config; using defaults")
            self._config = AppConfig()
            return self._config
        loaded_device_zone_count = int(data.get("device_zone_count") or 0)
        loaded_zones = data.get("zones")
        has_legacy_zones = isinstance(loaded_zones, list) and len(loaded_zones) > 0
        should_persist_migration = (
            "calibration_schema_version" not in data or "calibration" not in data
        )
        self._config = validate_config(cfg)
        if raw_use_mock_capture and not self._config.use_mock_capture:
            self.save(self._config)
        should_persist_legacy_auto_zone_count = (
            loaded_device_zone_count <= 0
            and self._config.device_zone_count > 0
            and has_legacy_zones
        )
        if should_persist_legacy_auto_zone_count or should_persist_migration:
            self.save(self._config)
        return self._config

    def exists(self) -> bool:
        return self.path.exists()

    def initialize(self, *, mode: str = "full-real", force: bool = False) -> bool:
        if self.path.exists() and not force:
            return False
        self.save(mode_config(mode))
        return True

    def reset_auto_probe_cache(self) -> AppConfig:
        cfg = self.load()
        updated_cfg = replace(
            cfg,
            auto_selected_backend="",
            auto_probe_signature="",
            auto_probe_timestamp="",
        )
        self.save(updated_cfg)
        return updated_cfg

    def reset_calibration_only(self) -> AppConfig:
        cfg = self.load()
        updated_cfg = replace(
            cfg,
            device_zone_count=0,
            calibration_schema_version=1,
            calibration=CalibrationConfig(),
            reverse_zones=False,
            corner_anchor_top_left=-1,
            corner_anchor_top_right=-1,
            corner_anchor_bottom_right=-1,
            corner_anchor_bottom_left=-1,
        )
        self.save(updated_cfg)
        return updated_cfg

    def reset_diagnostics_cache_only(self) -> AppConfig:
        cfg = self.load()
        updated_cfg = replace(
            cfg,
            auto_selected_backend="",
            auto_probe_signature="",
            auto_probe_timestamp="",
            latency_last_backend="",
            latency_last_value_ms=0.0,
            latency_last_trigger="",
            latency_last_timestamp="",
            wizard_in_progress_state="",
        )
        self.save(updated_cfg)
        return updated_cfg

    def reset_all_config(self) -> AppConfig:
        updated_cfg = AppConfig()
        self.save(updated_cfg)
        return updated_cfg

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        cfg = validate_config(config)
        self._config = cfg

        payload: dict[str, Any] = asdict(cfg)
        payload["zones"] = [asdict(z) for z in cfg.zones]
        payload["zone_sampling_stride"] = int(cfg.zone_sampling_stride)
        payload["sampling_quality"] = str(cfg.sampling_quality)

        encoded = dump_toml(payload)

        # Use advisory file locking to prevent concurrent saves from corrupting
        # the config (e.g., tray app + settings dialog racing on save).
        lock_fd: int | None = None
        tmp_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.with_suffix(self.path.suffix + ".lock")
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            except OSError:
                logger.warning("Config save: flock not supported; proceeding without locking")

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
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except Exception:
                    logger.debug("Failed to release config file lock", exc_info=True)
                try:
                    os.close(lock_fd)
                except Exception:
                    logger.debug("Failed to close config lock fd", exc_info=True)
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    logger.debug("Failed to unlink temp config file", exc_info=True)
