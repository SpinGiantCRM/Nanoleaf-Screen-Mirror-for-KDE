from __future__ import annotations

from nanoleaf_sync.runtime.errors import translate_runtime_error
from nanoleaf_sync.runtime.state import RuntimeState


def test_translate_hid_permission_error() -> None:
    translated = translate_runtime_error(
        RuntimeError("Failed to open Nanoleaf HID device. Check Linux HID permissions")
    )
    assert translated.kind == "hid-permission"
    assert "udev" in translated.guidance


def test_runtime_state_records_translated_error() -> None:
    state = RuntimeState()
    state.record_error(RuntimeError("Nanoleaf device not found VID=0x37fa PID=0x8202"))
    assert state.last_error_kind == "device-not-found"
    assert "VID=0x37fa" in (state.last_error or "")
    assert state.last_error_guidance is not None


def test_translate_kwin_signature_mismatch_error() -> None:
    translated = translate_runtime_error(
        RuntimeError("KWin ScreenShot2 interface is present but method/signature is incompatible with this Plasma version.")
    )
    assert translated.kind == "kwin-signature-mismatch"


def test_translate_kwin_decode_error() -> None:
    translated = translate_runtime_error(
        RuntimeError("KWin screenshot payload decode failed for byte payload.")
    )
    assert translated.kind == "kwin-decode"


def test_translate_portal_cancelled_start_error() -> None:
    translated = translate_runtime_error(
        RuntimeError("Portal negotiation failed: Start denied (response=1).")
    )
    assert translated.kind == "screen-selection-cancelled"
    assert translated.summary == "Screen selection cancelled."
