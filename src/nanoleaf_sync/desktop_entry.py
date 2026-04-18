from __future__ import annotations

import os
from pathlib import Path


AUTOSTART_DESKTOP_NAME = "nanoleaf-kde-sync.desktop"
RESTRICTED_IFACE_MARKER = "X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2"


def project_root() -> Path:
    # src/nanoleaf_sync/desktop_entry.py -> repo root
    return Path(__file__).resolve().parents[2]


def source_desktop_template_path() -> Path:
    return project_root() / "docs" / AUTOSTART_DESKTOP_NAME


def user_autostart_path() -> Path:
    return Path.home() / ".config" / "autostart" / AUTOSTART_DESKTOP_NAME


def installed_desktop_entry_candidates() -> list[Path]:
    candidates: list[Path] = []

    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if data_home:
        candidates.append(Path(data_home) / "applications" / AUTOSTART_DESKTOP_NAME)
    else:
        candidates.append(Path.home() / ".local" / "share" / "applications" / AUTOSTART_DESKTOP_NAME)

    data_dirs = os.environ.get("XDG_DATA_DIRS", "").strip()
    if data_dirs:
        for entry in data_dirs.split(":"):
            entry = entry.strip()
            if not entry:
                continue
            candidates.append(Path(entry) / "applications" / AUTOSTART_DESKTOP_NAME)
    else:
        candidates.extend(
            [
                Path("/usr/local/share/applications") / AUTOSTART_DESKTOP_NAME,
                Path("/usr/share/applications") / AUTOSTART_DESKTOP_NAME,
            ]
        )

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        deduped.append(candidate)
        seen.add(candidate)
    return deduped


def desktop_entry_has_restricted_marker(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    return RESTRICTED_IFACE_MARKER in text


def _resolved_desktop_source() -> Path | None:
    template = source_desktop_template_path()
    if template.exists():
        return template
    for installed in installed_desktop_entry_candidates():
        if installed.exists():
            return installed
    return None


def enable_autostart() -> Path:
    source = _resolved_desktop_source()
    if source is None:
        raise FileNotFoundError(
            "Unable to find nanoleaf-kde-sync.desktop in source docs/ or installed desktop-entry locations."
        )

    destination = user_autostart_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8", errors="ignore")
    if RESTRICTED_IFACE_MARKER not in text:
        text = text.rstrip() + f"\n{RESTRICTED_IFACE_MARKER}\n"
    destination.write_text(text, encoding="utf-8")
    return destination


def disable_autostart() -> bool:
    path = user_autostart_path()
    if not path.exists():
        return False
    path.unlink()
    return True
