"""Tests for runtime/errors.py uncovered paths."""

from __future__ import annotations

import pytest

from nanoleaf_sync.runtime.errors import (
    UserFacingError,
    translate_runtime_error,
)


def test_translate_unsupported_model() -> None:
    result = translate_runtime_error(RuntimeError("Unsupported Nanoleaf model 'NONE'"))
    assert result.kind == "unsupported-model"
    assert "NONE" in result.summary


def test_translate_device_not_found() -> None:
    result = translate_runtime_error(RuntimeError("Device not found VID=0x37fa"))
    assert result.kind == "device-not-found"
    assert "USB device" in result.guidance


def test_translate_hid_permission() -> None:
    result = translate_runtime_error(RuntimeError("Failed to open Nanoleaf HID device: permission denied"))
    assert result.kind == "hid-permission"
    assert "udev" in result.guidance


def test_translate_kwin_authorization() -> None:
    result = translate_runtime_error(RuntimeError("Screen access denied: NotAuthorized"))
    assert result.kind == "kwin-authorization"
    assert "ScreenShot2" in result.guidance


def test_translate_kwin_policy_screenshot() -> None:
    result = translate_runtime_error(RuntimeError("KDE policy denied screenshot access"))
    assert result.kind == "kwin-authorization"


def test_translate_kwin_signature_mismatch() -> None:
    result = translate_runtime_error(RuntimeError("D-Bus error: method/signature is incompatible"))
    assert result.kind == "kwin-signature-mismatch"
    assert "method signatures" in result.guidance


def test_translate_kwin_invalid_args() -> None:
    result = translate_runtime_error(RuntimeError("org.freedesktop.DBus.Error.InvalidArgs"))
    assert result.kind == "kwin-signature-mismatch"


def test_translate_kwin_unknown_method() -> None:
    result = translate_runtime_error(RuntimeError("org.freedesktop.DBus.Error.UnknownMethod"))
    assert result.kind == "kwin-signature-mismatch"


def test_translate_kwin_no_api() -> None:
    result = translate_runtime_error(RuntimeError("No usable KWin screenshot API found"))
    assert result.kind == "kwin-no-api"


def test_translate_kwin_decode() -> None:
    result = translate_runtime_error(RuntimeError("Payload decode failed in kwin capture"))
    assert result.kind == "kwin-decode"


def test_translate_session_bus() -> None:
    result = translate_runtime_error(RuntimeError("session bus unavailable"))
    assert result.kind == "kwin-session-bus"


def test_translate_kwin_unavailable() -> None:
    result = translate_runtime_error(RuntimeError("all known KWin screenshot interfaces unreachable"))
    assert result.kind == "kwin-unavailable"


def test_translate_screen_selection_cancelled() -> None:
    result = translate_runtime_error(RuntimeError("start denied (response=1)"))
    assert result.kind == "screen-selection-cancelled"


def test_translate_portal_backend() -> None:
    result = translate_runtime_error(RuntimeError("portal negotiation failed"))
    assert result.kind == "portal-backend"


def test_translate_unknown_error() -> None:
    result = translate_runtime_error(RuntimeError("some random error"))
    assert result.kind == "runtime"
    assert "nanoleaf-kde-sync-doctor" in result.guidance


def test_translate_none_error() -> None:
    """None error fallback."""
    result = translate_runtime_error(RuntimeError())  # type: ignore[arg-type]
    assert result.kind == "runtime"


def test_user_facing_error_dataclass() -> None:
    err = UserFacingError(kind="test", summary="sum", guidance="guide")
    assert err.kind == "test"
    assert err.summary == "sum"
    assert err.guidance == "guide"
