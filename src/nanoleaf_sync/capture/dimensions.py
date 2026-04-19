from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from nanoleaf_sync.config.model import AppConfig


DEFAULT_CAPTURE_WIDTH = 1920
DEFAULT_CAPTURE_HEIGHT = 1080


def _parse_mode_line(line: str) -> Optional[Tuple[int, int]]:
    # Typical modes: "3840x2160" or "3840x2160@60"
    head = line.strip().split("@", 1)[0]
    if "x" not in head:
        return None
    try:
        width_s, height_s = head.split("x", 1)
        width = int(width_s)
        height = int(height_s)
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _detect_primary_screen_dims_sysfs() -> Optional[Tuple[int, int]]:
    drm_root = Path("/sys/class/drm")
    if not drm_root.exists():
        return None

    best: Optional[Tuple[int, int]] = None
    for connector in sorted(drm_root.iterdir()):
        status_path = connector / "status"
        modes_path = connector / "modes"
        if not status_path.exists() or not modes_path.exists():
            continue

        try:
            status = status_path.read_text(encoding="utf-8", errors="ignore").strip().lower()
        except Exception:
            continue
        if status != "connected":
            continue

        try:
            mode_lines = modes_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue

        for line in mode_lines:
            dims = _parse_mode_line(line)
            if dims is None:
                continue
            if best is None or (dims[0] * dims[1]) > (best[0] * best[1]):
                best = dims
    return best


def detect_primary_screen_dims(*, qt_widgets_module=None) -> Optional[Tuple[int, int]]:
    """Best-effort primary-screen detection via sysfs/DRM first, Qt fallback."""
    detected = _detect_primary_screen_dims_sysfs()
    if detected is not None:
        return detected

    qt_widgets = qt_widgets_module
    if qt_widgets is None:
        try:
            from PyQt6 import QtWidgets as qt_widgets  # type: ignore
        except Exception:
            return None

    try:
        qapplication = qt_widgets.QApplication
        app = qapplication.instance()
    except Exception:
        return None

    created_app = False
    if app is None:
        try:
            app = qapplication([])
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
