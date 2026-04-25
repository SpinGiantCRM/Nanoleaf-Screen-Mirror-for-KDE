def test_guided_calibration_dialog_drives_live_preview_hooks() -> None:
    text = open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()
    assert "on_step_changed=self._on_guided_calibration_step_changed" in text
    assert "on_open=self._on_guided_calibration_opened" in text
    assert "on_close=self._on_guided_calibration_closed" in text
    assert "def _send_guided_calibration_pattern(self) -> None:" in text
    assert "apply_led_calibration(" in text


def test_led_dialog_calls_open_close_and_step_callbacks() -> None:
    text = open("src/nanoleaf_sync/ui/led_color_calibration_dialog.py", "r", encoding="utf-8").read()
    assert "if callable(on_open):" in text
    assert "if callable(on_step_changed):" in text
    assert "def done(self, result: int) -> None:" in text
