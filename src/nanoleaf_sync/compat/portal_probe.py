from __future__ import annotations

import asyncio
import logging
import threading
from typing import Final

logger = logging.getLogger(__name__)

_PORTAL_BUS: Final = "org.freedesktop.portal.Desktop"
_PORTAL_PATH: Final = "/org/freedesktop/portal/desktop"
_PORTAL_IFACE: Final = "org.freedesktop.portal.ScreenCast"

_cache_lock = threading.Lock()
_cached_version: int | None = None


def reset_portal_probe_cache() -> None:
    global _cached_version

    with _cache_lock:
        _cached_version = None


async def _query_portal_version_async() -> int:
    from dbus_next import Message, MessageType
    from dbus_next.aio import MessageBus

    bus = await MessageBus().connect()
    reply = await bus.call(
        Message(
            destination=_PORTAL_BUS,
            path=_PORTAL_PATH,
            interface=_PORTAL_IFACE,
            member="GetVersion",
            signature="",
            body=[],
        )
    )
    if reply is None or reply.message_type == MessageType.ERROR:
        error_name = getattr(reply, "error_name", "unknown")
        raise RuntimeError(f"Portal GetVersion failed: {error_name}")
    if not reply.body:
        raise RuntimeError("Portal GetVersion returned empty body")
    return int(reply.body[0])


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

    thread = threading.Thread(target=_worker, name="portal-version-probe", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    if not result:
        raise RuntimeError("Portal version probe returned no result")
    return result[0]


def get_portal_version(*, force_refresh: bool = False) -> int:
    """Return XDG ScreenCast portal version, or 0 when unavailable."""

    global _cached_version

    with _cache_lock:
        if not force_refresh and _cached_version is not None:
            return _cached_version

    try:
        version = _run_async_probe(_query_portal_version_async())
    except Exception as exc:
        logger.debug("Portal version probe failed: %s", exc, exc_info=True)
        with _cache_lock:
            _cached_version = 0
        return 0

    if version >= 7:
        logger.warning(
            "XDG ScreenCast portal version %d is newer than tested range; "
            "portal capture may need an app update",
            version,
        )

    with _cache_lock:
        _cached_version = version
    return version


def supports_pipewire_serial(*, force_refresh: bool = False) -> bool:
    return get_portal_version(force_refresh=force_refresh) >= 6


def supports_persist_mode(*, force_refresh: bool = False) -> bool:
    return get_portal_version(force_refresh=force_refresh) >= 4


def supports_source_type(*, force_refresh: bool = False) -> bool:
    return get_portal_version(force_refresh=force_refresh) >= 3


def get_portal_capabilities(*, force_refresh: bool = False) -> set[str]:
    version = get_portal_version(force_refresh=force_refresh)
    if version <= 0:
        return set()
    capabilities = {"screencast"}
    if version >= 3:
        capabilities.add("source_type")
    if version >= 4:
        capabilities.update({"persist_mode", "restore_token"})
    if version >= 6:
        capabilities.add("pipewire-serial")
    return capabilities


def log_portal_probe_results() -> dict[str, object]:
    version = get_portal_version()
    capabilities = sorted(get_portal_capabilities())
    payload = {
        "portal_version": version,
        "portal_capabilities": capabilities,
        "supports_pipewire_serial": supports_pipewire_serial(),
    }
    logger.info(
        "XDG portal probe version=%s capabilities=%s pipewire_serial=%s",
        version or "unavailable",
        ", ".join(capabilities) or "none",
        payload["supports_pipewire_serial"],
    )
    return payload
