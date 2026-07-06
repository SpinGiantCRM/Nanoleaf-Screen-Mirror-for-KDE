from __future__ import annotations

import pytest

from tests.qt_headless import load_headless_qt


def _make_dialog(monkeypatch: pytest.MonkeyPatch, **overrides):
    _qt, app = load_headless_qt(monkeypatch)
    from nanoleaf_sync.ui.diagnostic_hub_dialog import DiagnosticHubDialog

    callbacks = {
        "status_fn": lambda: {"running": False, "capture_backend": "kwin-dbus"},
        "forget_portal_token_fn": lambda: {"ok": True, "message": "forgotten"},
        "colour_probe_fn": lambda **_kwargs: {"ok": True, "message": "probe ok"},
        "flicker_lab_fn": lambda **_kwargs: {"ok": True, "scenarios": []},
        "portal_pick_fn": lambda: {"ok": True, "message": "picked", "rgb": (1, 2, 3)},
        "export_bundle_fn": lambda _path: {"ok": True, "message": "exported"},
        "open_live_diagnostics_fn": lambda: None,
    }
    callbacks.update(overrides)
    dialog = DiagnosticHubDialog(parent=None, **callbacks)
    dialog.show()
    app.processEvents()
    dialog._timer.stop()
    return app, dialog


def test_diagnostic_hub_reports_unavailable_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _status() -> dict:
        raise RuntimeError("status unavailable")

    app, dialog = _make_dialog(monkeypatch, status_fn=_status)
    app.processEvents()

    assert dialog._warnings_banner.isVisible()
    assert "status unavailable" in dialog._warnings_banner.text()
    assert dialog._overview_labels["running"].text() == "Unavailable"
    assert "Runtime status is unavailable" in dialog._overview_status.toPlainText()


def test_diagnostic_hub_action_failures_stay_in_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _status() -> dict:
        raise RuntimeError("usb busy")

    def _probe(**_kwargs) -> dict:
        raise RuntimeError("capture unavailable")

    def _pick() -> dict:
        raise RuntimeError("portal denied")

    def _flicker(**_kwargs) -> dict:
        raise RuntimeError("profile invalid")

    _app, dialog = _make_dialog(
        monkeypatch,
        status_fn=lambda: {"running": True},
        colour_probe_fn=_probe,
        portal_pick_fn=_pick,
        flicker_lab_fn=_flicker,
    )

    dialog._status_fn = _status
    dialog._refresh_usb_profile()
    assert "USB profile unavailable: usb busy" in dialog._usb_message.toPlainText()

    dialog._run_colour_probe()
    assert "Colour path probe failed: capture unavailable" in (dialog._colour_output.toPlainText())

    dialog._run_portal_pick()
    assert "Portal colour pick failed: portal denied" in dialog._colour_output.toPlainText()

    dialog._run_flicker_lab()
    assert "Flicker lab failed: profile invalid" in dialog._colour_output.toPlainText()
