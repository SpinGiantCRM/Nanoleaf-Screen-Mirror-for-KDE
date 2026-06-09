from __future__ import annotations

import asyncio
import logging
import threading
from typing import Final

logger = logging.getLogger(__name__)

_SCREENSHOT2_BUS: Final = "org.kde.KWin"
_SCREENSHOT2_PATH: Final = "/org/kde/KWin/ScreenShot2"
_SCREENSHOT2_IFACE: Final = "org.kde.KWin.ScreenShot2"
_PROPERTIES_IFACE: Final = "org.freedesktop.DBus.Properties"

_KNOWN_MAX_VERSION = 5

_VERSION_CAPABILITIES: dict[int, frozenset[str]] = {
    1: frozenset({"CaptureWindow", "CaptureActiveWindow"}),
    2: frozenset({"CaptureWindow", "CaptureActiveWindow", "CaptureActiveScreen"}),
    3: frozenset(
        {"CaptureWindow", "CaptureActiveWindow", "CaptureActiveScreen", "CaptureWorkspace"}
    ),
    4: frozenset(
        {
            "CaptureWindow",
            "CaptureActiveWindow",
            "CaptureActiveScreen",
            "CaptureWorkspace",
            "result-scale",
            "result-windowId",
            "result-screen",
        }
    ),
    5: frozenset(
        {
            "CaptureWindow",
            "CaptureActiveWindow",
            "CaptureActiveScreen",
            "CaptureWorkspace",
            "result-scale",
            "result-windowId",
            "result-screen",
            "hide-caller-windows",
        }
    ),
}

_cache_lock = threading.Lock()
_cached_version: int | None = None
_cached_capabilities: frozenset[str] | None = None


def reset_kwin_probe_cache() -> None:
    global _cached_version, _cached_capabilities

    with _cache_lock:
        _cached_version = None
        _cached_capabilities = None


def _capabilities_for_version(version: int) -> frozenset[str]:
    if version <= 0:
        return frozenset()
    if version > _KNOWN_MAX_VERSION:
        return _VERSION_CAPABILITIES[_KNOWN_MAX_VERSION]
    return _VERSION_CAPABILITIES.get(version, frozenset())


async def _query_screenshot2_version_async() -> int:
    from dbus_next import Message, MessageType
    from dbus_next.aio import MessageBus

    bus = await MessageBus().connect()
    reply = await bus.call(
        Message(
            destination=_SCREENSHOT2_BUS,
            path=_SCREENSHOT2_PATH,
            interface=_PROPERTIES_IFACE,
            member="Get",
            signature="ss",
            body=[_SCREENSHOT2_IFACE, "version"],
        )
    )
    if reply is None or reply.message_type == MessageType.ERROR:
        error_name = getattr(reply, "error_name", "unknown")
        raise RuntimeError(f"ScreenShot2 version query failed: {error_name}")
    value = reply.body[0]
    version = int(getattr(value, "value", value))
    if version < 1:
        raise RuntimeError(f"ScreenShot2 reported invalid version: {version}")
    return version


def _run_async_probe(coro) -> int:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[int] = []
    error: list[BaseException] = []

    def _worker() -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result.append(loop.run_until_complete(coro))
        except BaseException as exc:  # pragma: no cover - thread handoff
            error.append(exc)
        finally:
            loop.close()

    thread = threading.Thread(target=_worker, name="kwin-screenshot2-probe", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    if not result:
        raise RuntimeError("ScreenShot2 version probe returned no result")
    return result[0]


def get_screenshot2_api_version(*, force_refresh: bool = False) -> int:
    """Return KWin ScreenShot2 API version, or 0 when unavailable."""

    global _cached_version, _cached_capabilities

    with _cache_lock:
        if not force_refresh and _cached_version is not None:
            return _cached_version

    try:
        version = _run_async_probe(_query_screenshot2_version_async())
    except Exception as exc:
        logger.debug("ScreenShot2 version probe failed: %s", exc, exc_info=True)
        with _cache_lock:
            _cached_version = 0
            _cached_capabilities = frozenset()
        return 0

    if version > _KNOWN_MAX_VERSION:
        logger.warning(
            "KWin ScreenShot2 API version %d is newer than known max v%d; "
            "assuming v%d compatibility",
            version,
            _KNOWN_MAX_VERSION,
            _KNOWN_MAX_VERSION,
        )

    capabilities = _capabilities_for_version(version)
    with _cache_lock:
        _cached_version = version
        _cached_capabilities = capabilities
    return version


def get_screenshot2_capabilities(*, force_refresh: bool = False) -> set[str]:
    version = get_screenshot2_api_version(force_refresh=force_refresh)
    with _cache_lock:
        if _cached_capabilities is not None and not force_refresh:
            return set(_cached_capabilities)
    return set(_capabilities_for_version(version))


def log_kwin_probe_results() -> dict[str, object]:
    version = get_screenshot2_api_version()
    capabilities = sorted(get_screenshot2_capabilities())
    status = "unknown"
    if version > 0:
        status = "known" if version <= _KNOWN_MAX_VERSION else "assumed-v5-compat"
    payload = {
        "screenshot2_api_version": version,
        "screenshot2_capabilities": capabilities,
        "screenshot2_status": status,
    }
    logger.info(
        "KWin ScreenShot2 probe version=%s status=%s capabilities=%s",
        version or "unavailable",
        status,
        ", ".join(capabilities) or "none",
    )
    return payload
