from __future__ import annotations

import sys
from dataclasses import replace
from typing import List

from config import AppConfig, ConfigManager, ZoneConfig
from service import NanoleafSyncService


def make_horizontal_zones(zone_count: int) -> List[ZoneConfig]:
    """
    Build zone rectangles spanning the screen horizontally.

    All zones cover full height and are equal-width segments.
    """

    count = max(1, int(zone_count))
    zones: List[ZoneConfig] = []
    for i in range(count):
        zones.append(
            ZoneConfig(
                x=i / count,
                y=0.0,
                w=1.0 / count,
                h=1.0,
            )
        )
    return zones


def _load_qt():
    """
    Import Qt modules lazily so non-UI usage doesn't fail if PyQt isn't installed.
    """

    try:
        from PyQt6.QtCore import QTimer, Qt
        from PyQt6.QtGui import QAction, QIcon, QPainter, QPixmap
        from PyQt6.QtWidgets import (
            QApplication,
            QDialog,
            QDialogButtonBox,
            QGridLayout,
            QCheckBox,
            QLabel,
            QMenu,
            QSlider,
            QSystemTrayIcon,
            QVBoxLayout,
        )
    except Exception as e:  # pragma: no cover
        raise RuntimeError("PyQt6 is required for the tray UI. Install `PyQt6`.") from e

    return {
        "QTimer": QTimer,
        "Qt": Qt,
        "QAction": QAction,
        "QIcon": QIcon,
        "QPainter": QPainter,
        "QPixmap": QPixmap,
        "QApplication": QApplication,
        "QDialog": QDialog,
        "QDialogButtonBox": QDialogButtonBox,
        "QGridLayout": QGridLayout,
        "QCheckBox": QCheckBox,
        "QLabel": QLabel,
        "QMenu": QMenu,
        "QSlider": QSlider,
        "QSystemTrayIcon": QSystemTrayIcon,
    }


class SettingsDialog:
    """
    Settings dialog (created dynamically with Qt types).

    Keeping this as a plain Python class allows lazy Qt imports.
    """

    def __init__(self, parent, cfg: AppConfig):
        qt = _load_qt()
        QDialog = qt["QDialog"]
        QDialogButtonBox = qt["QDialogButtonBox"]
        QGridLayout = qt["QGridLayout"]
        QCheckBox = qt["QCheckBox"]
        QLabel = qt["QLabel"]
        QSlider = qt["QSlider"]

        class _Dialog(QDialog):  # type: ignore
            def __init__(self):
                super().__init__(parent)
                self.setWindowTitle("nanoleaf-kde-sync Settings")

                self.brightness_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.brightness_slider.setRange(0, 100)
                self.brightness_slider.setValue(int(round(cfg.brightness * 100)))

                self.smoothing_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.smoothing_slider.setRange(0, 100)
                self.smoothing_slider.setValue(int(round(cfg.smoothing * 100)))

                self.fps_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.fps_slider.setRange(1, 60)
                self.fps_slider.setValue(int(cfg.fps))

                # Derive zone_count from existing zones; if empty, default to 1.
                zone_count = len(cfg.zones) if cfg.zones else 1
                self.zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_count_slider.setRange(1, 24)
                self.zone_count_slider.setValue(int(zone_count))

                # Calibration controls (mapping sampled zones -> physical strip zones)
                self.zone_offset_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.zone_offset_slider.setRange(-20, 20)
                self.zone_offset_slider.setValue(int(getattr(cfg, "zone_offset", 0)))

                self.reverse_checkbox = QCheckBox("Reverse strip orientation")
                self.reverse_checkbox.setChecked(bool(getattr(cfg, "reverse_zones", False)))

                device_zone_count = int(getattr(cfg, "device_zone_count", 0)) or int(zone_count)
                self.device_zone_count_slider = QSlider(qt["Qt"].Orientation.Horizontal)
                self.device_zone_count_slider.setRange(1, 128)
                self.device_zone_count_slider.setValue(device_zone_count)

                self.mock_capture_checkbox = QCheckBox("Mock capture (synthetic)")
                self.mock_capture_checkbox.setChecked(bool(getattr(cfg, "use_mock_capture", True)))

                buttons = QDialogButtonBox(
                    QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                )
                buttons.accepted.connect(self.accept)
                buttons.rejected.connect(self.reject)

                layout = QGridLayout()
                layout.addWidget(QLabel("Brightness"), 0, 0)
                layout.addWidget(self.brightness_slider, 0, 1)
                layout.addWidget(QLabel("Smoothing (EMA alpha)"), 1, 0)
                layout.addWidget(self.smoothing_slider, 1, 1)
                layout.addWidget(QLabel("Capture FPS"), 2, 0)
                layout.addWidget(self.fps_slider, 2, 1)
                layout.addWidget(QLabel("Zone count (horizontal)"), 3, 0)
                layout.addWidget(self.zone_count_slider, 3, 1)
                layout.addWidget(QLabel("Zone offset (calibration)"), 4, 0)
                layout.addWidget(self.zone_offset_slider, 4, 1)
                layout.addWidget(self.reverse_checkbox, 5, 0, 1, 2)
                layout.addWidget(QLabel("Device zone count"), 6, 0)
                layout.addWidget(self.device_zone_count_slider, 6, 1)
                layout.addWidget(self.mock_capture_checkbox, 7, 0, 1, 2)
                layout.addWidget(buttons, 8, 0, 1, 2)
                self.setLayout(layout)

            def updated_config(self) -> AppConfig:
                brightness = self.brightness_slider.value() / 100.0
                smoothing = self.smoothing_slider.value() / 100.0
                fps = int(self.fps_slider.value())
                zone_count = int(self.zone_count_slider.value())
                zone_offset = int(self.zone_offset_slider.value())
                reverse_zones = bool(self.reverse_checkbox.isChecked())
                device_zone_count = int(self.device_zone_count_slider.value())

                # Update zones as normalized equal slices.
                new_zones = make_horizontal_zones(zone_count)
                # Preserve all other config fields; only override what the user changed.
                return replace(
                    cfg,
                    fps=fps,
                    brightness=brightness,
                    smoothing=smoothing,
                    zones=new_zones,
                    device_zone_count=device_zone_count,
                    zone_offset=zone_offset,
                    reverse_zones=reverse_zones,
                    explicit_zone_map=[],
                    use_mock_capture=bool(self.mock_capture_checkbox.isChecked()),
                )

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def updated_config(self) -> AppConfig:
        return self._dialog.updated_config()


class NanoleafTrayApp:
    """
    KDE/Linux system tray UI for starting/stopping the background service.
    """

    def __init__(self) -> None:
        qt = _load_qt()
        self.QApplication = qt["QApplication"]
        self.QSystemTrayIcon = qt["QSystemTrayIcon"]
        self.QIcon = qt["QIcon"]
        self.QPixmap = qt["QPixmap"]
        self.QPainter = qt["QPainter"]
        self.QAction = qt["QAction"]
        self.QMenu = qt["QMenu"]
        self.Qt = qt["Qt"]

        self.app = qt["QApplication"](sys.argv)
        self.cfg_mgr = ConfigManager()
        self.config = self.cfg_mgr.load()
        self.service = NanoleafSyncService(config=self.config)

        self.tray_icon = self._make_tray_icon(running=False)
        self.tray_icon.setContextMenu(self._make_menu())
        self.tray_icon.show()

    def _make_tray_icon(self, running: bool):
        pix = self.QPixmap(16, 16)
        pix.fill(self.Qt.GlobalColor.transparent)
        painter = self.QPainter(pix)
        color = self.Qt.GlobalColor.green if running else self.Qt.GlobalColor.gray
        painter.fillRect(0, 0, 16, 16, color)
        painter.end()
        icon = self.QIcon(pix)
        return self.QSystemTrayIcon(icon)

    def _make_menu(self):
        menu = self.QMenu()
        self.action_start = self.QAction("Start", menu)
        self.action_stop = self.QAction("Stop", menu)
        self.action_settings = self.QAction("Settings", menu)
        self.action_quit = self.QAction("Quit", menu)

        self.action_start.triggered.connect(self.on_start)
        self.action_stop.triggered.connect(self.on_stop)
        self.action_settings.triggered.connect(self.on_settings)
        self.action_quit.triggered.connect(self.on_quit)

        menu.addAction(self.action_start)
        menu.addAction(self.action_stop)
        menu.addSeparator()
        menu.addAction(self.action_settings)
        menu.addAction(self.action_quit)
        return menu

    def on_start(self):
        self.service.start()
        self.tray_icon.setIcon(self._make_tray_icon(running=True).icon())

    def on_stop(self):
        self.service.stop()
        self.service.join(timeout=3.0)
        self.tray_icon.setIcon(self._make_tray_icon(running=False).icon())

    def on_settings(self):
        dlg = SettingsDialog(parent=None, cfg=self.config)
        if dlg.exec() != 1:  # QDialog.Accepted == 1
            return
        new_cfg = dlg.updated_config()
        self.cfg_mgr.save(new_cfg)
        self.config = new_cfg
        # Replace the service with updated config.
        was_running = self.service.is_running()
        if was_running:
            self.on_stop()
        self.service = NanoleafSyncService(config=self.config)

        if was_running:
            self.on_start()

    def on_quit(self):
        try:
            self.on_stop()
        finally:
            self.app.quit()

    def run(self):
        return self.app.exec()


def main() -> None:  # pragma: no cover
    NanoleafTrayApp().run()


if __name__ == "__main__":  # pragma: no cover
    main()

