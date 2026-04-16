from __future__ import annotations

import sys

from config import ConfigManager
from service import NanoleafSyncService

from .qt_lazy import load_qt
from .settings_dialog import SettingsDialog


class NanoleafTrayApp:
    """
    KDE/Linux system tray UI for starting/stopping the background service.
    """

    def __init__(self) -> None:
        qt = load_qt()
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
        self.action_status = self.QAction("Diagnostics", menu)
        self.action_quit = self.QAction("Quit", menu)

        self.action_start.triggered.connect(self.on_start)
        self.action_stop.triggered.connect(self.on_stop)
        self.action_settings.triggered.connect(self.on_settings)
        self.action_status.triggered.connect(self.on_status)
        self.action_quit.triggered.connect(self.on_quit)

        menu.addAction(self.action_start)
        menu.addAction(self.action_stop)
        menu.addSeparator()
        menu.addAction(self.action_settings)
        menu.addAction(self.action_status)
        menu.addAction(self.action_quit)
        return menu

    def on_start(self):
        started = self.service.start()
        running = started and self.service.is_running()
        self.tray_icon.setIcon(self._make_tray_icon(running=running).icon())
        if not running:
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                f"Start failed: {self.service.last_error or 'unknown error'}",
                self.QSystemTrayIcon.MessageIcon.Warning,
                4000,
            )

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

    def on_status(self):
        status = self.service.get_status()
        summary = (
            f"running={status.get('running')} "
            + f"backend={status.get('capture_backend')} "
            + f"mode={status.get('capture_mode')} "
            + f"frames={status.get('frames_sent')} "
            + f"errors={status.get('consecutive_errors')}"
        )
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync diagnostics",
            summary,
            self.QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

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
