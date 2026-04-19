"""Desktop-entry discovery and autostart file management helpers.

KDE ScreenShot2 access can depend on launch context, so this module ensures
desktop entries and autostart files carry the required restricted-interface
marker used by diagnostics and first-run tooling.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path


AUTOSTART_DESKTOP_NAME = "nanoleaf-kde-sync.desktop"
QT_DESKTOP_FILE_NAME = AUTOSTART_DESKTOP_NAME.removesuffix(".desktop")
RESTRICTED_IFACE_MARKER = "X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2"
_DESKTOP_ENTRY_HEADER = "[Desktop Entry]"


def project_root() -> Path:
    # src/nanoleaf_sync/desktop_entry.py -> repo root
    return Path(__file__).resolve().parents[2]


def source_desktop_template_path() -> Path:
    return project_root() / "docs" / AUTOSTART_DESKTOP_NAME


def _xdg_data_home() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if data_home:
        return Path(data_home)
    return Path.home() / ".local" / "share"


def user_autostart_path() -> Path:
    return Path.home() / ".config" / "autostart" / AUTOSTART_DESKTOP_NAME


def installed_desktop_entry_candidates() -> list[Path]:
    candidates: list[Path] = []

    candidates.append(_xdg_data_home() / "applications" / AUTOSTART_DESKTOP_NAME)

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


def launch_context_snapshot() -> dict[str, str]:
    """
    Return launch-context fields useful for diagnosing KDE ScreenShot2 policy checks.
    """
    keys = (
        "DESKTOP_STARTUP_ID",
        "XDG_ACTIVATION_TOKEN",
        "XDG_CURRENT_DESKTOP",
        "XDG_SESSION_DESKTOP",
        "KDE_SESSION_VERSION",
        "DBUS_SESSION_BUS_ADDRESS",
    )
    return {key: os.environ.get(key, "").strip() for key in keys}


def preferred_user_desktop_entry_path() -> Path:
    return _xdg_data_home() / "applications" / AUTOSTART_DESKTOP_NAME


def runtime_exec_command() -> str:
    executable = Path(sys.executable).resolve()
    executable_token = shlex.quote(str(executable))
    if getattr(sys, "frozen", False):
        return executable_token
    return f"{executable_token} -m nanoleaf_sync.ui.tray"


def _upsert_desktop_key(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    replacement = f"{key}={value}"

    section_start = next((idx for idx, line in enumerate(lines) if line.strip() == _DESKTOP_ENTRY_HEADER), None)
    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(_DESKTOP_ENTRY_HEADER)
        section_start = len(lines) - 1
        section_end = len(lines)
    else:
        section_end = len(lines)
        for idx in range(section_start + 1, len(lines)):
            if lines[idx].lstrip().startswith("["):
                section_end = idx
                break

    for idx in range(section_start + 1, section_end):
        if lines[idx].startswith(f"{key}="):
            lines[idx] = replacement
            break
    else:
        lines.insert(section_end, replacement)
    return "\n".join(lines).rstrip() + "\n"


def _prepare_desktop_entry_text(text: str, *, exec_command: str | None = None) -> str:
    out = text
    if _DESKTOP_ENTRY_HEADER not in out:
        out = _DESKTOP_ENTRY_HEADER + "\n" + out
    if exec_command:
        out = _upsert_desktop_key(out, "Exec", exec_command)
    if RESTRICTED_IFACE_MARKER not in out:
        out = out.rstrip() + f"\n{RESTRICTED_IFACE_MARKER}\n"
    return out


def ensure_user_launcher_entry(*, exec_command: str | None = None) -> Path:
    """Create or update the user launcher desktop entry.

    Unlike enable_autostart(), this helper self-heals missing source templates
    by generating a minimal desktop entry from _DESKTOP_ENTRY_HEADER and a
    default Type/Name stanza, then normalizing it with runtime_exec_command().
    """
    source = _resolved_desktop_source()
    text = (
        source.read_text(encoding="utf-8", errors="ignore")
        if source is not None
        else f"{_DESKTOP_ENTRY_HEADER}\nType=Application\nName={QT_DESKTOP_FILE_NAME}\n"
    )
    final_text = _prepare_desktop_entry_text(
        text,
        exec_command=exec_command or runtime_exec_command(),
    )
    destination = preferred_user_desktop_entry_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(final_text, encoding="utf-8")
    return destination


def redact_launch_token(value: str | None) -> str:
    """
    Return a non-sensitive summary for launch/auth tokens used in diagnostics.
    """
    token = (value or "").strip()
    if not token:
        return "unset"
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}…{token[-4:]}"


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
    text = _prepare_desktop_entry_text(text, exec_command=runtime_exec_command())
    destination.write_text(text, encoding="utf-8")
    return destination


def disable_autostart() -> bool:
    path = user_autostart_path()
    if not path.exists():
        return False
    path.unlink()
    return True
