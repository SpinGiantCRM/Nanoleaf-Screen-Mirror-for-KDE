from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.zone_presets import _adaptive_edge_thickness

logger = logging.getLogger(__name__)

DEFAULT_CAPTURE_WIDTH = 480
DEFAULT_CAPTURE_HEIGHT = 270
_MIN_EDGE_PIXELS = 6


def _parse_mode_line(line: str) -> tuple[int, int] | None:
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


def _detect_primary_screen_dims_sysfs() -> tuple[int, int] | None:
    drm_root = Path("/sys/class/drm")
    if not drm_root.exists():
        return None

    best: tuple[int, int] | None = None
    for connector in sorted(drm_root.iterdir()):
        status_path = connector / "status"
        modes_path = connector / "modes"
        if not status_path.exists() or not modes_path.exists():
            continue

        try:
            status = status_path.read_text(encoding="utf-8", errors="ignore").strip().lower()
        except Exception:
            logger.debug("Unable to read DRM connector status from %s", status_path, exc_info=True)
            continue
        if status != "connected":
            continue

        try:
            mode_lines = modes_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            logger.debug("Unable to read DRM connector modes from %s", modes_path, exc_info=True)
            continue

        for line in mode_lines:
            dims = _parse_mode_line(line)
            if dims is None:
                continue
            if best is None or (dims[0] * dims[1]) > (best[0] * best[1]):
                best = dims
    return best


def detect_primary_screen_dims(
    *, qt_widgets_module: object | None = None
) -> tuple[int, int] | None:
    """Best-effort primary-screen detection via sysfs/DRM first, Qt fallback."""
    if qt_widgets_module is None:
        detected = _detect_primary_screen_dims_sysfs()
        if detected is not None:
            return detected

    qt_widgets = qt_widgets_module
    if qt_widgets is None:
        try:
            from PyQt6 import QtWidgets

            qt_widgets = QtWidgets
        except Exception:
            logger.debug("PyQt6 unavailable for screen dimension detection", exc_info=True)
            return None

    try:
        qt_mod = cast(Any, qt_widgets)
        qapplication = qt_mod.QApplication
        app = qapplication.instance()
    except Exception:
        logger.debug("Unable to access Qt QApplication for screen detection", exc_info=True)
        return None

    created_app = False
    if app is None:
        try:
            app = qapplication([])
            created_app = True
        except Exception:
            logger.debug("Unable to create Qt QApplication for screen detection", exc_info=True)
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
        logger.debug("Unable to read primary screen geometry from Qt", exc_info=True)
        return None
    finally:
        if created_app:
            app.quit()


def resolve_capture_dims(config: AppConfig) -> tuple[int, int]:
    """Return ``(width, height)`` for capture initialization."""
    zone_count = max(
        1,
        len(getattr(config, "zones", ()) or ()),
        int(getattr(config, "device_zone_count", 0) or 0),
    )
    edge_locality = str(getattr(config, "edge_locality", "balanced"))
    edge_thickness = _adaptive_edge_thickness(zone_count, edge_locality=edge_locality)
    min_height_for_edge = max(
        DEFAULT_CAPTURE_HEIGHT,
        int(round((DEFAULT_CAPTURE_HEIGHT / max(edge_thickness, 0.05)) * edge_thickness)),
        _MIN_EDGE_PIXELS * 3,
    )
    target_w = max(DEFAULT_CAPTURE_WIDTH, zone_count * 4, 160)
    target_h = max(min_height_for_edge, (target_w * 9) // 16, 90)

    detected = detect_primary_screen_dims()
    if detected is not None:
        return min(target_w, int(detected[0])), min(target_h, int(detected[1]))
    return target_w, target_h
