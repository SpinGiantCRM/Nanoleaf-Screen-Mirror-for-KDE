"""Export/import helpers for measured LED calibration profiles."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from nanoleaf_sync.config.model import AppConfig, LedCalibrationProfile

PROFILE_SCHEMA_VERSION = 1
PROFILE_KIND = "nanoleaf-kde-sync-led-calibration-profile"


def led_calibration_profile_to_dict(profile: LedCalibrationProfile) -> dict[str, Any]:
    payload = asdict(profile)
    payload["schema_version"] = PROFILE_SCHEMA_VERSION
    payload["profile_kind"] = PROFILE_KIND
    return payload


def led_calibration_profile_from_dict(data: dict[str, Any]) -> LedCalibrationProfile:
    if str(data.get("profile_kind", "")) != PROFILE_KIND:
        raise ValueError("Unrecognized LED calibration profile file.")
    schema_version = int(data.get("schema_version", 0) or 0)
    if schema_version != PROFILE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported LED calibration profile schema version: {schema_version}")
    fields = {
        name: data[name] for name in LedCalibrationProfile.__dataclass_fields__ if name in data
    }
    return LedCalibrationProfile(**fields)


def export_measured_led_calibration_profile(
    *,
    profile: LedCalibrationProfile,
    display_preset: str,
) -> str:
    payload = {
        "display_preset": str(display_preset or "sdr").strip().lower(),
        "profile": led_calibration_profile_to_dict(profile),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def import_measured_led_calibration_profile(raw: str) -> tuple[str, LedCalibrationProfile]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("LED calibration profile JSON must be an object.")
    preset = str(data.get("display_preset", "sdr") or "sdr").strip().lower()
    profile_payload = data.get("profile")
    if not isinstance(profile_payload, dict):
        raise ValueError("LED calibration profile JSON is missing a profile object.")
    return preset, led_calibration_profile_from_dict(profile_payload)


def apply_imported_profile_to_config(
    cfg: AppConfig,
    *,
    display_preset: str,
    profile: LedCalibrationProfile,
) -> AppConfig:
    preset = str(display_preset or "sdr").strip().lower()
    if preset == "hdr":
        cfg.led_calibration_profile_hdr = profile
    else:
        cfg.led_calibration_profile_sdr = profile
    return cfg
