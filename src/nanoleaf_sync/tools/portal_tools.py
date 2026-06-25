from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from nanoleaf_sync.capture.portal_helpers import unwrap_variant

_DEFAULT_TOKEN_PATH = Path.home() / ".config" / "nanoleaf-kde-sync" / "portal_token"


def default_portal_restore_token_path() -> Path:
    return _DEFAULT_TOKEN_PATH


def portal_restore_token_info(*, token_path: Path | None = None) -> dict[str, Any]:
    path = token_path or _DEFAULT_TOKEN_PATH
    exists = path.is_file()
    size = int(path.stat().st_size) if exists else 0
    return {
        "path": str(path),
        "exists": exists,
        "size_bytes": size,
        "has_token": exists and size > 0,
    }


def forget_portal_restore_token(*, token_path: Path | None = None) -> dict[str, Any]:
    path = token_path or _DEFAULT_TOKEN_PATH
    try:
        if path.is_file():
            path.unlink()
            return {"ok": True, "message": "Saved portal screen choice was cleared."}
        return {"ok": True, "message": "No saved portal screen choice was on disk."}
    except OSError as exc:
        return {"ok": False, "message": f"Could not clear portal token: {exc}"}


def request_portal_pick_color(*, timeout_s: float = 45.0) -> dict[str, Any]:
    try:
        rgb = _run_portal_pick_color(timeout_s=float(timeout_s))
    except TimeoutError:
        return {
            "ok": False,
            "message": "Portal colour pick timed out. Try again or use zone colour compare.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Portal colour pick unavailable: {exc}",
        }
    if rgb is None:
        return {"ok": False, "message": "Portal colour pick was cancelled."}
    return {"ok": True, "rgb": rgb, "message": "Picked colour from screen."}


def _run_portal_pick_color(timeout_s: float) -> tuple[int, int, int] | None:
    return asyncio.run(_pick_color_async(timeout_s=timeout_s))


async def _pick_color_async(*, timeout_s: float) -> tuple[int, int, int] | None:
    from dbus_next import Variant
    from dbus_next.aio import MessageBus
    from dbus_next.constants import BusType

    bus = await MessageBus(bus_type=BusType.SESSION).connect()
    try:
        introspection = await bus.introspect(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
        )
        portal = bus.get_proxy_object(
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            introspection,
        )
        screenshot = portal.get_interface("org.freedesktop.portal.Screenshot")
        loop = asyncio.get_running_loop()
        done: asyncio.Future[tuple[int, int, int] | None] = loop.create_future()

        def _on_response(response: int, results: dict[str, Variant]) -> None:
            if done.done():
                return
            if int(response) != 0:
                done.set_result(None)
                return
            color = results.get("color")
            if color is None:
                done.set_result(None)
                return
            rgba = unwrap_variant(color)
            if not isinstance(rgba, tuple) or len(rgba) < 3:
                done.set_result(None)
                return
            done.set_result(
                (
                    int(round(float(rgba[0]) * 255.0)),
                    int(round(float(rgba[1]) * 255.0)),
                    int(round(float(rgba[2]) * 255.0)),
                )
            )

        req_path = await screenshot.call_pick_color("", {"interactive": Variant("b", True)})
        req_intro = await bus.introspect("org.freedesktop.portal.Desktop", str(req_path))
        request_obj = bus.get_proxy_object(
            "org.freedesktop.portal.Desktop",
            str(req_path),
            req_intro,
        )
        req_iface = request_obj.get_interface("org.freedesktop.portal.Request")
        req_iface.on_Response(_on_response)
        return await asyncio.wait_for(done, timeout=timeout_s)
    finally:
        with contextlib.suppress(Exception):
            bus.disconnect()
