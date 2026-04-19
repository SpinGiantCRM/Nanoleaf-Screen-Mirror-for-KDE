from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.service import (
    _DEFAULT_CAPTURE_HEIGHT,
    _DEFAULT_CAPTURE_WIDTH,
    _detect_primary_screen_dims,
    _resolve_capture_dims,
)


class _FakeGeometry:
    def __init__(self, w: int, h: int) -> None:
        self._w = w
        self._h = h

    def width(self) -> int:
        return self._w

    def height(self) -> int:
        return self._h


class _FakeScreen:
    def __init__(self, w: int, h: int) -> None:
        self._g = _FakeGeometry(w, h)

    def geometry(self):
        return self._g


class _FakeQApplication:
    _instance = None
    created_count = 0
    quit_count = 0

    def __init__(self, _argv) -> None:
        type(self)._instance = self
        type(self).created_count += 1

    @classmethod
    def instance(cls):
        return cls._instance

    def primaryScreen(self):
        return _FakeScreen(3440, 1440)

    def quit(self):
        type(self).quit_count += 1


class _FakeQtWidgets:
    QApplication = _FakeQApplication


class _InvalidQtWidgets:
    pass


def test_detect_primary_screen_dims_uses_existing_qt_app() -> None:
    app = _FakeQApplication([])
    dims = _detect_primary_screen_dims(qt_widgets_module=_FakeQtWidgets)

    assert dims == (3440, 1440)
    assert _FakeQApplication.created_count == 1
    assert _FakeQApplication.quit_count == 0


def test_detect_primary_screen_dims_creates_app_when_missing() -> None:
    _FakeQApplication._instance = None
    _FakeQApplication.created_count = 0
    _FakeQApplication.quit_count = 0

    dims = _detect_primary_screen_dims(qt_widgets_module=_FakeQtWidgets)

    assert dims == (3440, 1440)
    assert _FakeQApplication.created_count == 1
    assert _FakeQApplication.quit_count == 1


def test_resolve_capture_dims_falls_back_to_defaults(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.capture.dimensions.detect_primary_screen_dims", lambda: None)

    w, h = _resolve_capture_dims(AppConfig())

    assert w == _DEFAULT_CAPTURE_WIDTH
    assert h == _DEFAULT_CAPTURE_HEIGHT


def test_detect_primary_screen_dims_returns_none_for_invalid_qt_module() -> None:
    dims = _detect_primary_screen_dims(qt_widgets_module=_InvalidQtWidgets)

    assert dims is None
