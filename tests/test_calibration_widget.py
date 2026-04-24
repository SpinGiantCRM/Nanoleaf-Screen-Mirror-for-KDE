from __future__ import annotations

import types

from nanoleaf_sync.ui.calibration_widget import SimpleCalibrationWidget


def _qt_stub() -> dict[str, object]:
    class _Signal:
        def __init__(self):
            self._callbacks = []

        def connect(self, callback):
            self._callbacks.append(callback)

        def emit(self):
            for callback in self._callbacks:
                callback()

    class _Button:
        def __init__(self, _text):
            self.clicked = _Signal()
            self._visible = True

        def setVisible(self, visible):
            self._visible = bool(visible)

    class _Check:
        def __init__(self, _text):
            self.stateChanged = _Signal()
            self._checked = False

        def setChecked(self, checked):
            self._checked = bool(checked)

    class _Label:
        def __init__(self, text=""):
            self.text = text

        def setText(self, text):
            self.text = text

    return {
        "QLabel": _Label,
        "QPushButton": _Button,
        "QCheckBox": _Check,
        "Qt": types.SimpleNamespace(),
    }


def test_simple_calibration_widget_exposes_expected_controls_and_callbacks() -> None:
    qt = _qt_stub()
    widget = SimpleCalibrationWidget(qt=qt)
    calls: list[str] = []
    widget.bind_callbacks(
        on_prev_zone=lambda: calls.append("prev"),
        on_next_zone=lambda: calls.append("next"),
        on_assign_top_left=lambda: calls.append("tl"),
        on_assign_top_right=lambda: calls.append("tr"),
        on_assign_bottom_right=lambda: calls.append("br"),
        on_assign_bottom_left=lambda: calls.append("bl"),
        on_reset_anchors=lambda: calls.append("reset"),
        on_reverse_orientation_changed=lambda: calls.append("reverse"),
    )

    widget.prev_zone_button.clicked.emit()
    widget.next_zone_button.clicked.emit()
    widget.assign_top_left_button.clicked.emit()
    widget.assign_top_right_button.clicked.emit()
    widget.assign_bottom_right_button.clicked.emit()
    widget.assign_bottom_left_button.clicked.emit()
    widget.reset_anchors_button.clicked.emit()
    widget.reverse_orientation_checkbox.stateChanged.emit()

    assert calls == ["prev", "next", "tl", "tr", "br", "bl", "reset", "reverse"]


def test_simple_calibration_widget_preview_and_status_helpers() -> None:
    widget = SimpleCalibrationWidget(qt=_qt_stub())
    widget.set_step_status(step_index=1, step_total=8, active_zone=3, normalized_offset=-2)
    widget.set_preview(text="preview text", visual="preview visual")

    assert "2/8" in widget.step_index_label.text
    assert "Active strip zone: 3" in widget.current_zone_label.text
    assert widget.preview_text_label.text == "preview text"
    assert widget.preview_visual_label.text == "preview visual"
