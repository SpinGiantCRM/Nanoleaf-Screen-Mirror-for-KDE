from __future__ import annotations

__all__ = ["NanoleafTrayApp", "tray_main"]


def __getattr__(name: str):
    if name in {"NanoleafTrayApp", "tray_main"}:
        from nanoleaf_sync.ui.tray_app import NanoleafTrayApp, main

        return {"NanoleafTrayApp": NanoleafTrayApp, "tray_main": main}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
