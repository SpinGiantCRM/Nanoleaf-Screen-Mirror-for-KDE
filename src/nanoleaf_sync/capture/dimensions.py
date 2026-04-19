from __future__ import annotations

from typing import Optional, Tuple

from nanoleaf_sync.config.model import AppConfig


DEFAULT_CAPTURE_WIDTH = 1920
DEFAULT_CAPTURE_HEIGHT = 1080


def detect_primary_screen_dims(*, qt_widgets_module=None) -> Optional[Tuple[int, int]]:
    """Best-effort primary-screen detection via PyQt6."""
    qt_widgets = qt_widgets_module
    if qt_widgets is None:
        try:
            from PyQt6 import QtWidgets as qt_widgets  # type: ignore
        except Exception:
            return None

    app = qt_widgets.QApplication.instance()
    created_app = False
    if app is None:
        try:
            app = qt_widgets.QApplication([])
            created_app = True
        except Exception:
            return None

    try:
        screen = app.primaryScreen()
        if screen is None:
            return None
        geometry = screen.geometry()
        width = int(geometry.width())
        height = int(geometry.height())
        if width <= 0 or height <= 0:
            return None
        return width, height
    except Exception:
        return None
    finally:
        if created_app:
            app.quit()


def resolve_capture_dims(_config: AppConfig) -> Tuple[int, int]:
    """Return ``(width, height)`` for capture initialization."""
    detected = detect_primary_screen_dims()
    if detected is not None:
        return detected
    return DEFAULT_CAPTURE_WIDTH, DEFAULT_CAPTURE_HEIGHT
