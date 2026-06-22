from __future__ import annotations

import json
import logging
import os
import platform
import re
import sys
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.tools.doctor import collect_kde_compatibility_report, format_report, run_doctor

_log = logging.getLogger(__name__)

_REDACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"/home/[^/\s]+"), "/home/<redacted>"),
    (re.compile(r"/Users/[^/\s]+"), "/Users/<redacted>"),
    (re.compile(r"restore_token[=:]\s*\S+", re.I), "restore_token=<redacted>"),
    (re.compile(r"activation_token[=:]\s*\S+", re.I), "activation_token=<redacted>"),
    (re.compile(r"DESKTOP_STARTUP_ID=\S+"), "DESKTOP_STARTUP_ID=<redacted>"),
    (re.compile(r"XDG_ACTIVATION_TOKEN=\S+"), "XDG_ACTIVATION_TOKEN=<redacted>"),
)


def redact_text(value: str) -> str:
    redacted = str(value)
    for pattern, replacement in _REDACT_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_object(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): redact_object(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_object(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _system_info_redacted() -> dict[str, Any]:
    return redact_object(
        {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cwd": str(Path.cwd()),
            "xdg_session_type": os.environ.get("XDG_SESSION_TYPE", ""),
            "wayland_display": os.environ.get("WAYLAND_DISPLAY", ""),
            "kde_session_version": os.environ.get("KDE_SESSION_VERSION", ""),
        }
    )


def _config_redacted() -> dict[str, Any]:
    try:
        config = ConfigManager().load()
        payload = {
            "device_zone_count": int(getattr(config, "device_zone_count", 0) or 0),
            "prefer_backend": str(getattr(config, "prefer_backend", "")),
            "display_preset": str(getattr(config, "display_preset", "")),
            "capture_monitor": str(getattr(config, "capture_monitor", "")),
            "fps": int(getattr(config, "fps", 0) or 0),
            "sync_mode": str(getattr(config, "sync_mode", "")),
            "wizard_completed": bool(getattr(config, "wizard_completed", False)),
        }
        return redact_object(payload)
    except Exception as exc:
        return {"error": redact_text(str(exc))}


def build_issue_template(*, bundle_meta: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Backend: {bundle_meta.get('backend', 'unknown')}",
            f"Method: {bundle_meta.get('capture_method', 'unknown')}",
            f"Monitor: {bundle_meta.get('monitor', 'unknown')}",
            f"Frame size: {bundle_meta.get('frame_size', 'unknown')}",
            f"Display preset: {bundle_meta.get('display_preset', 'unknown')}",
            f"HDR metadata confidence: {bundle_meta.get('hdr_confidence', 'unknown')}",
            f"Device zones detected/configured: "
            f"{bundle_meta.get('detected_zones', 'unknown')}/"
            f"{bundle_meta.get('configured_zones', 'unknown')}",
            f"Startup blocked: {bundle_meta.get('startup_blocked', 'unknown')}",
        ]
    )


def create_diagnostic_bundle(
    output_path: Path,
    *,
    include_device_probe: bool = False,
    include_capture_probe: bool = False,
    runtime_status: dict[str, Any] | None = None,
) -> Path:
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    checks = run_doctor(
        include_device_probe=include_device_probe,
        include_capture_probe=include_capture_probe,
    )
    doctor_report = format_report(checks)
    status = redact_object(runtime_status or {})
    config = _config_redacted()
    bundle_meta = {
        "created_at": datetime.now(UTC).isoformat(),
        "backend": status.get("effective_capture_backend") or status.get("capture_backend"),
        "capture_method": (
            (status.get("latest_frame_context") or {}).get("capture_method")
            if isinstance(status.get("latest_frame_context"), dict)
            else status.get("capture_path")
        ),
        "monitor": (
            (status.get("latest_frame_context") or {}).get("source", {}).get("monitor_id")
            if isinstance(status.get("latest_frame_context"), dict)
            else status.get("capture_monitor")
        ),
        "frame_size": (
            (status.get("latest_frame_context") or {}).get("frame_size")
            if isinstance(status.get("latest_frame_context"), dict)
            else None
        ),
        "display_preset": config.get("display_preset"),
        "hdr_confidence": (
            (status.get("latest_color_context") or {}).get("confidence")
            if isinstance(status.get("latest_color_context"), dict)
            else None
        ),
        "detected_zones": status.get("detected_device_zone_count"),
        "configured_zones": status.get("configured_device_zone_count"),
        "startup_blocked": status.get("calibration_status") or status.get("lifecycle_state"),
        "capture_source_identity": status.get("latest_capture_source_identity"),
        "usb_transport_profile": status.get("usb_transport_profile"),
        "runtime_warnings": status.get("runtime_warnings"),
    }
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bundle.json", json.dumps(bundle_meta, indent=2, sort_keys=True))
        archive.writestr("runtime_status.json", json.dumps(status, indent=2, sort_keys=True))
        if status.get("usb_transport_profile") is not None:
            archive.writestr(
                "usb_transport_profile.json",
                json.dumps(status.get("usb_transport_profile"), indent=2, sort_keys=True),
            )
        if status.get("latest_capture_source_identity") is not None:
            archive.writestr(
                "capture_source_identity.json",
                json.dumps(status.get("latest_capture_source_identity"), indent=2, sort_keys=True),
            )
        archive.writestr(
            "backend_probe.json",
            json.dumps(redact_object(checks_to_dict(checks)), indent=2),
        )
        archive.writestr("config_redacted.json", json.dumps(config, indent=2, sort_keys=True))
        archive.writestr(
            "system_info_redacted.json",
            json.dumps(_system_info_redacted(), indent=2, sort_keys=True),
        )
        archive.writestr(
            "kwin_diagnostic.json",
            json.dumps(redact_object(collect_kde_compat_dict()), indent=2),
        )
        archive.writestr("doctor_report.txt", redact_text(doctor_report))
        archive.writestr("issue_template.txt", build_issue_template(bundle_meta=bundle_meta))
    return output_path


def checks_to_dict(checks: Sequence[object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for check in checks:
        rows.append(
            {
                "name": str(getattr(check, "name", "")),
                "status": str(getattr(check, "status", "")),
                "message": redact_text(str(getattr(check, "message", ""))),
                "action": redact_text(str(getattr(check, "action", "") or "")),
            }
        )
    return rows


def collect_kde_compat_dict() -> dict[str, Any]:
    lines = collect_kde_compatibility_report()
    return {"lines": [redact_text(line) for line in lines]}
