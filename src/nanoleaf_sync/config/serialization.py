from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import tomli_w


def toml_render_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return '""'
    return json.dumps(str(value))


def toml_render_list(values: list[Any]) -> str:
    return "[" + ", ".join(toml_render_scalar(v) for v in values) + "]"


def _prepare_payload_for_round_trip(payload: dict[str, Any]) -> dict[str, Any]:
    prepared = deepcopy(payload)
    calibration = prepared.get("calibration")
    if isinstance(calibration, dict):
        schema_version = calibration.get(
            "calibration_schema_version",
            calibration.get("schema_version", prepared.get("calibration_schema_version", 1)),
        )
        calibration["schema_version"] = schema_version
        calibration["calibration_schema_version"] = schema_version
        prepared["calibration_schema_version"] = schema_version
    return prepared


def dump_toml(payload: dict[str, Any]) -> str:
    prepared_payload = _prepare_payload_for_round_trip(payload)
    return tomli_w.dumps(prepared_payload)
