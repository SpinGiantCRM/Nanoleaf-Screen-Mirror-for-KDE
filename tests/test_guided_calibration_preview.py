from nanoleaf_sync.ui.led_color_calibration_dialog import (
    CALIBRATION_STEPS,
    LedColorCalibrationDialog,
)
from tests.qt_headless import load_headless_qt, make_settings_dialog


def test_guided_calibration_dialog_drives_live_preview_hooks(monkeypatch) -> None:
    sent: list[list[tuple[int, int, int]]] = []

    def _sender(colors: list[tuple[int, int, int]]) -> None:
        sent.append(colors)

    _qt, _app, _dialog, widget = make_settings_dialog(
        monkeypatch, calibration_sender=_sender, runtime_status={}
    )
    assert hasattr(widget, "_send_guided_calibration_pattern")
    assert hasattr(widget, "_on_guided_calibration_step_changed")
    assert hasattr(widget, "_on_guided_calibration_opened")
    assert hasattr(widget, "_on_guided_calibration_closed")

    widget._runtime_status["_guided_calibration_step"] = 6
    widget._runtime_status["_guided_locality_marker"] = 0
    widget._send_guided_calibration_pattern()
    assert sent
    assert len(sent[-1]) >= 1


def test_led_dialog_calls_open_close_and_step_callbacks(monkeypatch) -> None:
    qt, app = load_headless_qt(monkeypatch)
    events: list[str] = []
    steps: list[int] = []

    dialog = LedColorCalibrationDialog(
        None,
        on_reset=lambda: None,
        on_helper_adjust=lambda _key: None,
        on_save_profile=lambda: None,
        on_open=lambda: events.append("open"),
        on_step_changed=lambda step: steps.append(step),
        on_close=lambda: events.append("close"),
    )
    widget = dialog._dialog
    widget.show()
    app.processEvents()
    assert events == ["open"]
    assert steps == [0]
    assert CALIBRATION_STEPS[5] == "6. Cyan/Magenta/Yellow secondaries"
    widget.done(0)
    app.processEvents()
    assert events == ["open", "close"]
