from __future__ import annotations

from collections.abc import Callable

from nanoleaf_sync.runtime.guided_calibration import GuidedCalibrationSession, GuidedResponse
from nanoleaf_sync.runtime.novel_features import guided_calibration_enabled
from nanoleaf_sync.runtime.pattern_generator import (
    anchor_blip,
    corner_screen_position,
    moving_bar,
    rainbow_sweep,
)


def build_guided_calibration_dialog(qt: object):
    if not guided_calibration_enabled():
        return None
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QImage, QPainter, QPixmap
    from PyQt6.QtWidgets import (
        QDialog,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    class PatternOverlay(QWidget):
        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self._pixmap = QPixmap()
            self.showFullScreen()

        def set_frame(self, image) -> None:
            h, w, _ = image.shape
            qimg = QImage(image.data, w, h, w * 3, QImage.Format.Format_RGB888)
            self._pixmap = QPixmap.fromImage(qimg.copy())
            self.update()

        def paintEvent(self, _event) -> None:  # noqa: N802
            painter = QPainter(self)
            if not self._pixmap.isNull():
                painter.drawPixmap(self.rect(), self._pixmap)

    class GuidedCalibrationDialog(QDialog):
        def __init__(
            self,
            *,
            device_zone_count: int,
            frame_width: int,
            frame_height: int,
            on_save: Callable[[GuidedCalibrationSession], None] | None = None,
            parent: QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self._session = GuidedCalibrationSession(
                device_zone_count=device_zone_count,
                frame_width=frame_width,
                frame_height=frame_height,
            )
            self._on_save = on_save
            self._overlay = PatternOverlay()
            self._t = 0.0
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(33)
            self._status = QLabel("")
            self._yes = QPushButton("Yes")
            self._no = QPushButton("No")
            self._left = QPushButton("Close ←")
            self._right = QPushButton("Close →")
            for button in (self._yes, self._no, self._left, self._right):
                button.clicked.connect(self._make_handler(button.text()))
            layout = QVBoxLayout(self)
            layout.addWidget(self._status)
            row = QHBoxLayout()
            row.addWidget(self._yes)
            row.addWidget(self._no)
            row.addWidget(self._left)
            row.addWidget(self._right)
            layout.addLayout(row)
            self.setWindowTitle("Guided Calibration")
            self._refresh()

        def _make_handler(self, label: str):
            mapping = {
                "Yes": "yes",
                "No": "no",
                "Close ←": "left",
                "Close →": "right",
            }

            def _handler() -> None:
                self._respond(mapping.get(label, "yes"))

            return _handler

        def _respond(self, response: GuidedResponse) -> None:
            self._session.apply_response(response)
            if self._session.is_complete():
                if self._on_save is not None:
                    self._on_save(self._session)
                self._overlay.close()
                self.accept()
                return
            self._refresh()

        def _tick(self) -> None:
            self._t += 0.033
            self._refresh()

        def _refresh(self) -> None:
            w = self._session.frame_width
            h = self._session.frame_height
            if self._session.step_kind == "direction":
                frame = moving_bar(width=w, height=h, t=self._t)
                self._status.setText("Does the light travel left-to-right?")
            elif self._session.step_kind == "corner":
                corner = self._session.current_corner
                est = self._session.corner_estimates[corner]
                cx, cy = corner_screen_position(
                    corner=corner,
                    width=w,
                    height=h,
                    estimate_zone=est,
                    zones_per_side=self._session.zones_per_side,
                )
                frame = anchor_blip(width=w, height=h, center_x=cx, center_y=cy)
                self._status.setText(f"Is this the {corner.replace('_', ' ')}?")
            elif self._session.step_kind == "rainbow":
                frame = rainbow_sweep(
                    width=w,
                    height=h,
                    t=self._t,
                    perimeter_zone_count=self._session.device_zone_count,
                )
                self._status.setText("Does the gradient match the screen perimeter?")
            else:
                frame = moving_bar(width=w, height=h, t=self._t)
                self._status.setText("Calibration complete.")
            self._overlay.set_frame(frame)

        def closeEvent(self, event) -> None:  # noqa: N802
            self._overlay.close()
            super().closeEvent(event)

    return GuidedCalibrationDialog
