from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


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


def _dump_toml_fallback(payload: dict[str, Any]) -> str:
    lines: list[str] = []

    def render_table(table: dict[str, Any], prefix: str = "") -> None:
        scalar_items: list[tuple[str, Any]] = []
        nested_items: list[tuple[str, dict[str, Any]]] = []
        for key, value in table.items():
            if isinstance(value, dict):
                nested_items.append((key, value))
                continue
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                if lines and lines[-1] != "":
                    lines.append("")
                section = f"{prefix}.{key}" if prefix else key
                for item in value:
                    lines.append(f"[[{section}]]")
                    for item_key, item_value in item.items():
                        item_rendered = toml_render_scalar(item_value)
                        lines.append(f"{item_key} = {item_rendered}")
                    lines.append("")
                continue
            if key == "sampling_quality":
                value = str(value).strip().lower()
            scalar_items.append((key, value))

        for key, value in scalar_items:
            rendered = (
                toml_render_list(value) if isinstance(value, list) else toml_render_scalar(value)
            )
            lines.append(f"{key} = {rendered}")

        for key, value in nested_items:
            section = f"{prefix}.{key}" if prefix else key
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[{section}]")
            render_table(value, section)

    render_table(payload)
    return "\n".join(lines).rstrip() + "\n"


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
    try:
        import tomli_w
    except ImportError:
        return _dump_toml_fallback(prepared_payload)

    return tomli_w.dumps(prepared_payload)
