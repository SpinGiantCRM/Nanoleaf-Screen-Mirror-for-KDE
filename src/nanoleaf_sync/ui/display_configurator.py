from __future__ import annotations

from dataclasses import replace

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.zone_calibration import mapping_preview_text, mapping_preview_visual
from nanoleaf_sync.ui.zone_presets import make_edge_weighted_zones, make_horizontal_zones


class DisplayConfiguratorDialog:
    """First-run display processing wizard.

    This intentionally stays as a lightweight QDialog-based wizard so it can be
    reused from startup and from Settings without changing app architecture.
    """

    def __init__(self, parent, cfg: AppConfig):
        qt = load_qt()
        QDialog = qt["QDialog"]
        QLabel = qt["QLabel"]
        QVBoxLayout = qt["QVBoxLayout"]
        QGridLayout = qt["QGridLayout"]
        QComboBox = qt["QComboBox"]
        QSlider = qt["QSlider"]
        QPushButton = qt["QPushButton"]

        class _Dialog(QDialog):  # type: ignore
            def __init__(self):
                super().__init__(parent)
                self.setWindowTitle("Display Configurator")

                self.display_mode_combo = QComboBox()
                self.display_mode_combo.addItems(["sdr", "hdr"])
                display_mode_idx = self.display_mode_combo.findText(
                    "hdr" if bool(getattr(cfg, "hdr_enabled", False)) else "sdr"
                )
                self.display_mode_combo.setCurrentIndex(max(0, display_mode_idx))
                self.display_mode_combo.setToolTip(
                    "SDR is safest for standard content. HDR can look better with a true HDR signal path."
                )

                self.color_mode_combo = QComboBox()
                self.color_mode_combo.addItems(["default", "balanced", "dynamic", "hyper"])
                color_mode_idx = self.color_mode_combo.findText(str(getattr(cfg, "color_mode", "default")))
                self.color_mode_combo.setCurrentIndex(max(0, color_mode_idx))
                self.color_mode_combo.setToolTip(
                    "Default is recommended. Balanced is calmer. Dynamic/Hyper are more vivid and reactive."
                )

                self.hdr_transfer_combo = QComboBox()
                self.hdr_transfer_combo.addItems(["srgb", "pq"])
                transfer_idx = self.hdr_transfer_combo.findText(str(getattr(cfg, "hdr_transfer", "srgb")))
                self.hdr_transfer_combo.setCurrentIndex(max(0, transfer_idx))
                self.hdr_transfer_combo.setToolTip(
                    "sRGB is safer for SDR-style workflows. PQ is the HDR transfer curve for HDR content."
                )

                self.hdr_primaries_combo = QComboBox()
                self.hdr_primaries_combo.addItems(["bt709", "bt2020"])
                primaries_idx = self.hdr_primaries_combo.findText(str(getattr(cfg, "hdr_primaries", "bt709")))
                self.hdr_primaries_combo.setCurrentIndex(max(0, primaries_idx))
                self.hdr_primaries_combo.setToolTip(
                    "BT.709 is safer/standard. BT.2020 is wider gamut and best when the full HDR path supports it."
                )

                self.hdr_max_nits_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.hdr_max_nits_slider.setRange(80, 10000)
                self.hdr_max_nits_slider.setValue(
                    min(int(getattr(cfg, "hdr_max_nits", 1000.0)), self.hdr_max_nits_slider.maximum())
                )
                self.hdr_max_nits_value = QLabel("")

                self.cancel_button = QPushButton("Cancel")
                self.save_button = QPushButton("Save Display Setup")
                self.cancel_button.clicked.connect(self.reject)
                self.save_button.clicked.connect(self.accept)

                self.hdr_help = QLabel(
                    "Step 3 (HDR only): HDR transfer/primaries/max nits shape tone mapping. "
                    "Values that are too high/low can look dull, clipped, or wrong."
                )
                initial_zone_count = len(cfg.zones) if cfg.zones else (int(getattr(cfg, "device_zone_count", 0)) or 8)
                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_count_slider.setRange(1, 24)
                self.zone_count_slider.setValue(int(initial_zone_count))
                self.zone_count_value = QLabel("")
                self.zone_preset_combo = QComboBox()
                self.zone_preset_combo.addItems(["edge-weighted", "horizontal"])
                self.zone_preset_combo.setCurrentIndex(
                    max(0, self.zone_preset_combo.findText(str(getattr(cfg, "zone_preset", "edge-weighted"))))
                )
                self.reverse_checkbox = qt["QCheckBox"]("Reverse strip orientation")
                self.reverse_checkbox.setChecked(bool(getattr(cfg, "reverse_zones", False)))
                self.zone_offset_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_offset_slider.setRange(-20, 20)
                self.zone_offset_slider.setValue(int(getattr(cfg, "zone_offset", 0)))
                self.zone_offset_value = QLabel("")
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.device_zone_count_slider.setRange(1, 128)
                self.device_zone_count_slider.setValue(int(getattr(cfg, "device_zone_count", 0)) or int(initial_zone_count))
                self.device_zone_count_auto_checkbox = qt["QCheckBox"]("Auto-detect strip zone count")
                self.device_zone_count_auto_checkbox.setChecked(int(getattr(cfg, "device_zone_count", 0)) == 0)
                self.preview_text = QLabel("")
                self.preview_visual = QLabel("")

                self._refresh_numeric_labels()
                self.hdr_max_nits_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.zone_count_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.zone_offset_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.display_mode_combo.currentIndexChanged.connect(self._refresh_visibility)
                self.zone_count_slider.valueChanged.connect(self._refresh_mapping_preview)
                self.zone_offset_slider.valueChanged.connect(self._refresh_mapping_preview)
                self.zone_preset_combo.currentIndexChanged.connect(self._refresh_mapping_preview)
                self.reverse_checkbox.stateChanged.connect(self._refresh_mapping_preview)
                self.device_zone_count_slider.valueChanged.connect(self._refresh_mapping_preview)
                self.device_zone_count_auto_checkbox.stateChanged.connect(self._refresh_mapping_preview)

                layout = QVBoxLayout()
                layout.addWidget(
                    QLabel(
                        "Step 1: Choose your main display path\n"
                        "• SDR: safest and simplest; best for standard content.\n"
                        "• HDR: best when your display/content path is truly HDR and configured correctly."
                    )
                )
                step1 = QGridLayout()
                step1.addWidget(QLabel("SDR/HDR mode"), 0, 0)
                step1.addWidget(self.display_mode_combo, 0, 1)
                layout.addLayout(step1)

                layout.addWidget(
                    QLabel(
                        "Step 2: Choose colour behaviour\n"
                        "• Default (recommended): tuned look for everyday use.\n"
                        "• Balanced: safer, steadier, less aggressive.\n"
                        "• Dynamic: more responsive to vivid/changing colours.\n"
                        "• Hyper: strongest, most boosted, highest overreaction risk."
                    )
                )
                step2 = QGridLayout()
                step2.addWidget(QLabel("Colour behaviour"), 0, 0)
                step2.addWidget(self.color_mode_combo, 0, 1)
                layout.addLayout(step2)

                layout.addWidget(self.hdr_help)
                step3 = QGridLayout()
                self.hdr_transfer_label = QLabel("HDR transfer")
                self.hdr_transfer_help_label = QLabel(
                    "sRGB = safer SDR-style response | PQ = HDR transfer curve for HDR tone mapping"
                )
                self.hdr_primaries_label = QLabel("HDR primaries")
                self.hdr_primaries_help_label = QLabel(
                    "BT.709 = standard/smaller gamut | BT.2020 = wider gamut for HDR-capable paths"
                )
                self.hdr_max_nits_label = QLabel("HDR max brightness")

                step3.addWidget(self.hdr_transfer_label, 0, 0)
                step3.addWidget(self.hdr_transfer_combo, 0, 1)
                step3.addWidget(self.hdr_transfer_help_label, 1, 0, 1, 2)
                step3.addWidget(self.hdr_primaries_label, 2, 0)
                step3.addWidget(self.hdr_primaries_combo, 2, 1)
                step3.addWidget(self.hdr_primaries_help_label, 3, 0, 1, 2)
                step3.addWidget(self.hdr_max_nits_label, 4, 0)
                step3.addWidget(self.hdr_max_nits_slider, 4, 1)
                step3.addWidget(self.hdr_max_nits_value, 4, 2)
                layout.addLayout(step3)
                layout.addWidget(
                    QLabel(
                        "Step 4: Strip / Zone calibration\n"
                        "Choose zone count + layout, then adjust reverse/offset until your strip order matches."
                    )
                )
                step4 = QGridLayout()
                step4.addWidget(QLabel("Zone count"), 0, 0)
                step4.addWidget(self.zone_count_slider, 0, 1)
                step4.addWidget(self.zone_count_value, 0, 2)
                step4.addWidget(QLabel("Zone layout preset"), 1, 0)
                step4.addWidget(self.zone_preset_combo, 1, 1)
                step4.addWidget(QLabel("Zone offset"), 2, 0)
                step4.addWidget(self.zone_offset_slider, 2, 1)
                step4.addWidget(self.zone_offset_value, 2, 2)
                step4.addWidget(self.reverse_checkbox, 3, 0, 1, 2)
                step4.addWidget(QLabel("Device zone count"), 4, 0)
                step4.addWidget(self.device_zone_count_slider, 4, 1)
                step4.addWidget(self.device_zone_count_auto_checkbox, 5, 0, 1, 2)
                step4.addWidget(self.preview_text, 6, 0, 1, 3)
                step4.addWidget(self.preview_visual, 7, 0, 1, 3)
                layout.addLayout(step4)

                actions = QGridLayout()
                actions.addWidget(self.cancel_button, 0, 0)
                actions.addWidget(self.save_button, 0, 1)
                layout.addLayout(actions)

                self.setLayout(layout)
                self._refresh_visibility()
                self._refresh_mapping_preview()

            def _refresh_visibility(self) -> None:
                hdr_mode = str(self.display_mode_combo.currentText()) == "hdr"
                for widget in (
                    self.hdr_help,
                    self.hdr_transfer_label,
                    self.hdr_transfer_help_label,
                    self.hdr_transfer_combo,
                    self.hdr_primaries_label,
                    self.hdr_primaries_help_label,
                    self.hdr_primaries_combo,
                    self.hdr_max_nits_label,
                    self.hdr_max_nits_slider,
                    self.hdr_max_nits_value,
                ):
                    widget.setVisible(hdr_mode)

            def _refresh_numeric_labels(self) -> None:
                self.hdr_max_nits_value.setText(f"{self.hdr_max_nits_slider.value()} nits")
                self.zone_count_value.setText(str(self.zone_count_slider.value()))
                self.zone_offset_value.setText(str(self.zone_offset_slider.value()))
                self.device_zone_count_slider.setEnabled(not self.device_zone_count_auto_checkbox.isChecked())

            def _effective_device_zone_count(self) -> int:
                if self.device_zone_count_auto_checkbox.isChecked():
                    return int(self.zone_count_slider.value())
                return int(self.device_zone_count_slider.value())

            def _refresh_mapping_preview(self) -> None:
                self.preview_text.setText(
                    mapping_preview_text(
                        zone_count=int(self.zone_count_slider.value()),
                        device_zone_count=self._effective_device_zone_count(),
                        zone_offset=int(self.zone_offset_slider.value()),
                        reverse_zones=bool(self.reverse_checkbox.isChecked()),
                    )
                )
                self.preview_visual.setText(
                    mapping_preview_visual(
                        zone_count=int(self.zone_count_slider.value()),
                        device_zone_count=self._effective_device_zone_count(),
                        zone_offset=int(self.zone_offset_slider.value()),
                        reverse_zones=bool(self.reverse_checkbox.isChecked()),
                    )
                )

            def updated_config(self) -> AppConfig:
                zone_count = int(self.zone_count_slider.value())
                zone_preset = str(self.zone_preset_combo.currentText())
                new_zones = make_edge_weighted_zones(zone_count) if zone_preset == "edge-weighted" else make_horizontal_zones(zone_count)
                return replace(
                    cfg,
                    hdr_enabled=str(self.display_mode_combo.currentText()) == "hdr",
                    color_mode=str(self.color_mode_combo.currentText()),
                    hdr_transfer=str(self.hdr_transfer_combo.currentText()),
                    hdr_primaries=str(self.hdr_primaries_combo.currentText()),
                    hdr_max_nits=float(self.hdr_max_nits_slider.value()),
                    zones=new_zones,
                    zone_preset=zone_preset,
                    device_zone_count=0 if self.device_zone_count_auto_checkbox.isChecked() else int(self.device_zone_count_slider.value()),
                    reverse_zones=bool(self.reverse_checkbox.isChecked()),
                    zone_offset=int(self.zone_offset_slider.value()),
                    wizard_completed=True,
                )

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def updated_config(self) -> AppConfig:
        return self._dialog.updated_config()
