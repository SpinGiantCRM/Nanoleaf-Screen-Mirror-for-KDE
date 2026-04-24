from __future__ import annotations

from typing import Callable


class SimpleCalibrationWidget:
    """Reusable simple corner-assignment calibration controls.

    Parent surfaces own calibration state and wire callbacks to these controls.
    """

    def __init__(self, *, qt: dict[str, object], title: str = "Calibration") -> None:
        QLabel = qt["QLabel"]
        QPushButton = qt["QPushButton"]
        QCheckBox = qt["QCheckBox"]

        self.title = title
        self.header_label = QLabel(title)
        self.preview_text_label = QLabel("")
        self.preview_visual_label = QLabel("")
        self.current_zone_label = QLabel("")
        self.step_index_label = QLabel("")

        self.next_zone_button = QPushButton("Next zone")
        self.prev_zone_button = QPushButton("Previous zone")

        self.assign_top_left_button = QPushButton("Assign → Top-left")
        self.assign_top_right_button = QPushButton("Assign → Top-right")
        self.assign_bottom_right_button = QPushButton("Assign → Bottom-right")
        self.assign_bottom_left_button = QPushButton("Assign → Bottom-left")
        self.reset_anchors_button = QPushButton("Reset anchors")

        self.reverse_orientation_checkbox = QCheckBox("Reverse orientation")

        self.apply_button = QPushButton("Apply")
        self.save_button = QPushButton("Save")
        self._set_visible(self.apply_button, False)
        self._set_visible(self.save_button, False)

    def bind_callbacks(
        self,
        *,
        on_prev_zone: Callable[[], None],
        on_next_zone: Callable[[], None],
        on_assign_top_left: Callable[[], None],
        on_assign_top_right: Callable[[], None],
        on_assign_bottom_right: Callable[[], None],
        on_assign_bottom_left: Callable[[], None],
        on_reset_anchors: Callable[[], None],
        on_reverse_orientation_changed: Callable[[], None],
        on_apply: Callable[[], None] | None = None,
        on_save: Callable[[], None] | None = None,
    ) -> None:
        self.prev_zone_button.clicked.connect(on_prev_zone)
        self.next_zone_button.clicked.connect(on_next_zone)
        self.assign_top_left_button.clicked.connect(on_assign_top_left)
        self.assign_top_right_button.clicked.connect(on_assign_top_right)
        self.assign_bottom_right_button.clicked.connect(on_assign_bottom_right)
        self.assign_bottom_left_button.clicked.connect(on_assign_bottom_left)
        self.reset_anchors_button.clicked.connect(on_reset_anchors)
        self.reverse_orientation_checkbox.stateChanged.connect(on_reverse_orientation_changed)
        if on_apply is not None:
            self.apply_button.clicked.connect(on_apply)
            self._set_visible(self.apply_button, True)
        if on_save is not None:
            self.save_button.clicked.connect(on_save)
            self._set_visible(self.save_button, True)

    def add_to_layout(self, layout, *, row: int = 0, include_header: bool = True) -> int:
        current_row = int(row)
        if include_header:
            layout.addWidget(self.header_label, current_row, 0, 1, 3)
            current_row += 1
        layout.addWidget(self.preview_text_label, current_row, 0, 1, 3)
        current_row += 1
        layout.addWidget(self.prev_zone_button, current_row, 0)
        layout.addWidget(self.next_zone_button, current_row, 1, 1, 2)
        current_row += 1
        layout.addWidget(self.step_index_label, current_row, 0, 1, 3)
        current_row += 1
        layout.addWidget(self.current_zone_label, current_row, 0, 1, 3)
        current_row += 1
        layout.addWidget(self.assign_top_left_button, current_row, 0, 1, 3)
        current_row += 1
        layout.addWidget(self.assign_top_right_button, current_row, 0, 1, 3)
        current_row += 1
        layout.addWidget(self.assign_bottom_right_button, current_row, 0, 1, 3)
        current_row += 1
        layout.addWidget(self.assign_bottom_left_button, current_row, 0, 1, 3)
        current_row += 1
        layout.addWidget(self.reset_anchors_button, current_row, 0, 1, 2)
        layout.addWidget(self.reverse_orientation_checkbox, current_row, 2)
        current_row += 1
        layout.addWidget(self.preview_visual_label, current_row, 0, 1, 3)
        current_row += 1
        layout.addWidget(self.apply_button, current_row, 0)
        layout.addWidget(self.save_button, current_row, 1)
        return current_row + 1

    def set_step_status(self, *, step_index: int, step_total: int, active_zone: int, normalized_offset: int) -> None:
        self.step_index_label.setText(f"Zone step: {int(step_index) + 1}/{max(1, int(step_total))}")
        self.current_zone_label.setText(
            f"Active strip zone: {int(active_zone)} | Offset: {int(normalized_offset):+d}"
        )

    def set_preview(self, *, text: str, visual: str) -> None:
        self.preview_text_label.setText(str(text))
        self.preview_visual_label.setText(str(visual))

    def set_reverse_orientation(self, checked: bool) -> None:
        self.reverse_orientation_checkbox.setChecked(bool(checked))

    @staticmethod
    def _set_visible(widget, visible: bool) -> None:
        setter = getattr(widget, "setVisible", None)
        if callable(setter):
            setter(bool(visible))
