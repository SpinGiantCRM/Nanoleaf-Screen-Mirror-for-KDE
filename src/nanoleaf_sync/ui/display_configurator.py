from __future__ import annotations

from dataclasses import replace

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.qt_lazy import load_qt


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

                self._refresh_numeric_labels()
                self.hdr_max_nits_slider.valueChanged.connect(self._refresh_numeric_labels)
                self.display_mode_combo.currentIndexChanged.connect(self._refresh_visibility)

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

                actions = QGridLayout()
                actions.addWidget(self.cancel_button, 0, 0)
                actions.addWidget(self.save_button, 0, 1)
                layout.addLayout(actions)

                self.setLayout(layout)
                self._refresh_visibility()

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

            def updated_config(self) -> AppConfig:
                return replace(
                    cfg,
                    hdr_enabled=str(self.display_mode_combo.currentText()) == "hdr",
                    color_mode=str(self.color_mode_combo.currentText()),
                    hdr_transfer=str(self.hdr_transfer_combo.currentText()),
                    hdr_primaries=str(self.hdr_primaries_combo.currentText()),
                    hdr_max_nits=float(self.hdr_max_nits_slider.value()),
                    wizard_completed=True,
                )

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def updated_config(self) -> AppConfig:
        return self._dialog.updated_config()
