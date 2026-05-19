from __future__ import annotations

from typing import Callable

from nanoleaf_sync.ui.qt_lazy import load_qt


CALIBRATION_STEPS: tuple[str, ...] = (
    "1. Black / near-black cutoff",
    "2. Grey ramp + white",
    "3. Red primary",
    "4. Green primary",
    "5. Blue primary",
    "6. Cyan/Magenta/Yellow secondaries",
    "7. Moving locality marker",
    "8. Final neutral confirmation",
)


class LedColorCalibrationDialog:
    def __init__(
        self,
        parent,
        *,
        on_reset: Callable[[], None],
        on_helper_adjust: Callable[[str], None],
        on_save_profile: Callable[[], None],
        on_step_changed: Callable[[int], None] | None = None,
        on_open: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        qt = load_qt()
        QDialog = qt["QDialog"]
        QVBoxLayout = qt["QVBoxLayout"]
        QLabel = qt["QLabel"]
        QPushButton = qt["QPushButton"]
        QHBoxLayout = qt["QHBoxLayout"]

        class _Dialog(QDialog):
            def __init__(self) -> None:
                super().__init__(parent)
                self.setWindowTitle("Calibrate LED colour")
                self._step = 0

                self.step_label = QLabel("")
                self.hint_label = QLabel(
                    "Reference mode is used for calibration because it avoids saturation boost."
                )
                self.pattern_label = QLabel(
                    "Use visual patterns: black, near-black, dark grey, 10/25/50/75% grey, white, primary/secondary colours, and locality checks."
                )
                self.pattern_label.setWordWrap(True)

                prev_button = QPushButton("Previous")
                next_button = QPushButton("Next")
                reset_button = QPushButton("Reset calibration values")
                save_button = QPushButton("Save profile")

                helper_row = QHBoxLayout()
                for label in (
                    "Too blue",
                    "Too green",
                    "Too red/pink",
                    "Too yellow/warm",
                    "Looks neutral",
                ):
                    button = QPushButton(label)
                    button.clicked.connect(lambda _checked=False, key=label: on_helper_adjust(key))
                    helper_row.addWidget(button)

                nav_row = QHBoxLayout()
                nav_row.addWidget(prev_button)
                nav_row.addWidget(next_button)
                nav_row.addWidget(reset_button)
                nav_row.addWidget(save_button)

                root = QVBoxLayout()
                root.addWidget(self.step_label)
                root.addWidget(self.hint_label)
                root.addWidget(self.pattern_label)
                root.addLayout(helper_row)
                root.addLayout(nav_row)
                self.setLayout(root)

                prev_button.clicked.connect(self._prev)
                next_button.clicked.connect(self._next)
                reset_button.clicked.connect(on_reset)
                save_button.clicked.connect(on_save_profile)
                self._refresh()
                if callable(on_open):
                    on_open()

            def _refresh(self) -> None:
                self.step_label.setText(CALIBRATION_STEPS[self._step])
                if callable(on_step_changed):
                    on_step_changed(self._step)

            def _next(self) -> None:
                self._step = min(len(CALIBRATION_STEPS) - 1, self._step + 1)
                self._refresh()

            def _prev(self) -> None:
                self._step = max(0, self._step - 1)
                self._refresh()

            def done(self, result: int) -> None:
                if callable(on_close):
                    on_close()
                super().done(result)

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()
