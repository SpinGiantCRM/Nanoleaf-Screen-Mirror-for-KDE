from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nanoleaf_sync.compat.kde_version import (
    format_version_tuple,
    get_kwin_version,
    get_plasma_version,
)
from nanoleaf_sync.compat.kwin_probe import get_screenshot2_api_version
from nanoleaf_sync.compat.portal_probe import get_portal_version

logger = logging.getLogger(__name__)

_SNAPSHOT_KEYS = (
    "last_seen_kwin_version",
    "last_seen_kde_plasma_version",
    "last_seen_screenshot2_version",
    "last_seen_portal_version",
    "last_seen_python_version",
)


def default_snapshot_path() -> Path:
    return Path.home() / ".config" / "nanoleaf-kde-sync" / "kde-version-snapshot.json"


def collect_current_versions() -> dict[str, Any]:
    return {
        "last_seen_kwin_version": format_version_tuple(get_kwin_version()),
        "last_seen_kde_plasma_version": format_version_tuple(get_plasma_version()),
        "last_seen_screenshot2_version": int(get_screenshot2_api_version()),
        "last_seen_portal_version": int(get_portal_version()),
        "last_seen_python_version": ".".join(str(part) for part in sys.version_info[:3]),
    }


def _load_snapshot(path: Path | None = None) -> dict[str, Any]:
    snapshot_path = path or default_snapshot_path()
    if not snapshot_path.is_file():
        return {}
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("Failed to read KDE version snapshot at %s", snapshot_path, exc_info=True)
        return {}
    return payload if isinstance(payload, dict) else {}


def check_for_upgrade(*, path: Path | None = None) -> dict[str, Any]:
    """Compare current versions with the last persisted snapshot."""

    snapshot_path = path or default_snapshot_path()
    previous = _load_snapshot(snapshot_path)
    current = collect_current_versions()
    changed: dict[str, dict[str, Any]] = {}
    for key in _SNAPSHOT_KEYS:
        old_value = previous.get(key)
        new_value = current.get(key)
        if old_value is None:
            continue
        if str(old_value) != str(new_value):
            changed[key] = {"previous": old_value, "current": new_value}

    result = {
        "changed": changed,
        "current": current,
        "previous": {key: previous.get(key) for key in _SNAPSHOT_KEYS if key in previous},
        "first_run": not previous,
        "snapshot_path": str(snapshot_path),
    }
    if changed:
        logger.warning(
            "KDE environment version change detected: %s",
            ", ".join(
                f"{key} {item['previous']} -> {item['current']}" for key, item in changed.items()
            ),
        )
    return result


def update_snapshot(*, path: Path | None = None) -> dict[str, Any]:
    snapshot_path = path or default_snapshot_path()
    payload = collect_current_versions()
    payload["last_updated"] = datetime.now(timezone.utc).isoformat()
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info("Updated KDE version snapshot at %s", snapshot_path)
    return payload


def upgrade_notification_message(upgrade_report: dict[str, Any]) -> str | None:
    changed = upgrade_report.get("changed")
    if not isinstance(changed, dict) or not changed:
        return None
    plasma = upgrade_report.get("current", {}).get("last_seen_kde_plasma_version", "unknown")
    if isinstance(changed, dict) and "last_seen_kde_plasma_version" in changed:
        plasma = changed["last_seen_kde_plasma_version"].get("current", plasma)
    return f"KDE updated to {plasma} — run nanoleaf-kde-sync-doctor to verify compatibility"
