from __future__ import annotations

from pathlib import Path

import pytest

from nanoleaf_sync.capture.kwin_dbus import (
    KWinDBusCaptureError,
    _allowed_screenshot_path,
    _validate_capture_byte_size,
    _validate_capture_dimensions,
)


def test_validate_capture_dimensions_rejects_oversized_frame() -> None:
    with pytest.raises(KWinDBusCaptureError, match="width out of bounds"):
        _validate_capture_dimensions(width=20000, height=1080)


def test_validate_capture_byte_size_rejects_huge_payload() -> None:
    with pytest.raises(KWinDBusCaptureError, match="payload size out of bounds"):
        _validate_capture_byte_size(128 * 1024 * 1024)


def test_allowed_screenshot_path_rejects_outside_tmp_and_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = Path("/var/nanoleaf-kde-sync-test-shot.ppm")
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    with pytest.raises(KWinDBusCaptureError, match="outside allowed"):
        _allowed_screenshot_path(outside)


def test_allowed_screenshot_path_allows_file_under_tmp(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    allowed = tmp_path / "shot.ppm"
    allowed.write_bytes(b"P6\n1 1\n255\n\x00\x00\x00")
    resolved = _allowed_screenshot_path(allowed)
    assert resolved.name == "shot.ppm"
