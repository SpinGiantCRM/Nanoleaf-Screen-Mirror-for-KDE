from __future__ import annotations

import json
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


def dump_toml(payload: dict[str, Any]) -> str:
    try:
        import tomli_w
    except ImportError:
        lines: list[str] = []
        for key, value in payload.items():
            if key == "sampling_quality":
                value = str(value).strip().lower()
            if key == "zones" and isinstance(value, list):
                for zone in value:
                    lines.append("[[zones]]")
                    for zone_k, zone_v in zone.items():
                        lines.append(f"{zone_k} = {float(zone_v)}")
                    lines.append("")
                continue
            rendered = (
                toml_render_list(value) if isinstance(value, list) else toml_render_scalar(value)
            )
            lines.append(f"{key} = {rendered}")
        return "\n".join(lines).rstrip() + "\n"

    return tomli_w.dumps(payload)
