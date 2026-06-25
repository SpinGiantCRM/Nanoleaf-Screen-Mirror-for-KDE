from __future__ import annotations

import logging
import re
import shutil
import subprocess  # nosec B404
from configparser import ConfigParser
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

_VERSION_RE: Final = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_KWIN_VERSION_RE: Final = re.compile(r"KWin\s+(\d+)\.(\d+)\.(\d+)", re.IGNORECASE)
_PLASMA_VERSION_RE: Final = re.compile(r"Plasma\s+(\d+)\.(\d+)\.(\d+)", re.IGNORECASE)


def format_version_tuple(version: tuple[int, int, int]) -> str:
    major, minor, patch = version
    if major <= 0 and minor <= 0 and patch <= 0:
        return "unknown"
    return f"{major}.{minor}.{patch}"


def _parse_version_text(text: str) -> tuple[int, int, int]:
    normalized = (text or "").strip()
    if not normalized:
        return (0, 0, 0)
    match = _VERSION_RE.search(normalized)
    if match is None:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _run_command(args: list[str]) -> str:
    if not args or shutil.which(args[0]) is None:
        return ""
    try:
        completed = subprocess.run(  # nosec B603
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=3.0,
        )
    except Exception:
        logger.debug("Command failed: %s", " ".join(args), exc_info=True)
        return ""
    return (completed.stdout or completed.stderr or "").strip()


def _version_from_kwin_cli() -> tuple[int, int, int]:
    output = _run_command(["kwin", "--version"])
    if not output:
        return (0, 0, 0)
    match = _KWIN_VERSION_RE.search(output)
    if match is None:
        return _parse_version_text(output)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _version_from_pkg_config() -> tuple[int, int, int]:
    output = _run_command(["pkg-config", "--modversion", "KF6Config"])
    return _parse_version_text(output)


def _version_from_kdeglobals() -> tuple[int, int, int]:
    path = Path.home() / ".config" / "kdeglobals"
    if not path.is_file():
        return (0, 0, 0)
    parser = ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except Exception:
        logger.debug("Failed to parse kdeglobals at %s", path, exc_info=True)
        return (0, 0, 0)
    for section in ("General", "KDE"):
        if parser.has_option(section, "Version"):
            return _parse_version_text(parser.get(section, "Version"))
    return (0, 0, 0)


async def _version_from_kwin_dbus_async() -> tuple[int, int, int]:
    from dbus_next import Message, MessageType
    from dbus_next.aio import MessageBus

    bus = await MessageBus().connect()
    reply = await bus.call(
        Message(
            destination="org.kde.KWin",
            path="/org/kde/KWin",
            interface="org.freedesktop.DBus.Properties",
            member="Get",
            signature="ss",
            body=["org.kde.KWin", "version"],
        )
    )
    if reply is None or reply.message_type == MessageType.ERROR:
        return (0, 0, 0)
    value = reply.body[0]
    return _parse_version_text(str(getattr(value, "value", value)))


def _version_from_kwin_dbus() -> tuple[int, int, int]:
    import asyncio
    import threading

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(_version_from_kwin_dbus_async())
        except Exception:
            logger.debug("KWin D-Bus version probe failed", exc_info=True)
            return (0, 0, 0)

    result: list[tuple[int, int, int]] = []

    def _worker() -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result.append(loop.run_until_complete(_version_from_kwin_dbus_async()))
        except Exception:
            result.append((0, 0, 0))
        finally:
            loop.close()

    thread = threading.Thread(target=_worker, name="kwin-version-probe", daemon=True)
    thread.start()
    thread.join()
    return result[0] if result else (0, 0, 0)


def get_kwin_version() -> tuple[int, int, int]:
    for resolver in (_version_from_kwin_cli, _version_from_kwin_dbus):
        version = resolver()
        if version != (0, 0, 0):
            return version
    return (0, 0, 0)


def get_plasma_version() -> tuple[int, int, int]:
    output = _run_command(["plasmashell", "--version"])
    if output:
        match = _PLASMA_VERSION_RE.search(output)
        if match is not None:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        parsed = _parse_version_text(output)
        if parsed != (0, 0, 0):
            return parsed

    for resolver in (_version_from_pkg_config, _version_from_kdeglobals, get_kwin_version):
        version = resolver()
        if version != (0, 0, 0):
            return version
    return (0, 0, 0)
