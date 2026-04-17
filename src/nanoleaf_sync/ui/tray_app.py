from __future__ import annotations

import sys

from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.service import NanoleafSyncService

from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.settings_dialog import SettingsDialog
from nanoleaf_sync.tools.doctor import format_report, run_doctor


def describe_mode(use_mock_capture: bool, use_mock_device: bool, prefer_backend: str) -> tuple[str, str]:
    capture_mode = "Mock capture" if use_mock_capture else f"Capture: {prefer_backend}"
    device_mode = "Mock device" if use_mock_device else "Real USB device"
    return capture_mode, device_mode


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
        self._config_created = self.cfg_mgr.initialize(mode="full-mock", force=False)
        self.config = self.cfg_mgr.load()
        self.service = NanoleafSyncService(config=self.config)

        self.tray_icon = self._make_tray_icon(running=False)
        self.tray_icon.setContextMenu(self._make_menu())
        self._refresh_mode_labels()
        self.tray_icon.show()
        if self._config_created:
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                (
                    "Created first-run config in safe full-mock mode.\n"
                    "Use Settings to switch mode, then run Doctor/Smoke Test."
                ),
                self.QSystemTrayIcon.MessageIcon.Information,
                7000,
            )

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
        self.action_mode = self.QAction("Mode: --", menu)
        self.action_mode.setEnabled(False)
        self.action_device = self.QAction("Device: --", menu)
        self.action_device.setEnabled(False)
        self.action_status = self.QAction("Status", menu)
        self.action_doctor = self.QAction("Run Doctor", menu)
        self.action_smoke = self.QAction("Run Smoke Test", menu)
        self.action_quit = self.QAction("Quit", menu)

        self.action_start.triggered.connect(self.on_start)
        self.action_stop.triggered.connect(self.on_stop)
        self.action_settings.triggered.connect(self.on_settings)
        self.action_status.triggered.connect(self.on_status)
        self.action_doctor.triggered.connect(self.on_doctor)
        self.action_smoke.triggered.connect(self.on_smoke_test)
        self.action_quit.triggered.connect(self.on_quit)

        menu.addAction(self.action_start)
        menu.addAction(self.action_stop)
        menu.addSeparator()
        menu.addAction(self.action_mode)
        menu.addAction(self.action_device)
        menu.addSeparator()
        menu.addAction(self.action_settings)
        menu.addAction(self.action_status)
        menu.addAction(self.action_doctor)
        menu.addAction(self.action_smoke)
        menu.addAction(self.action_quit)
        return menu

    def _refresh_mode_labels(self) -> None:
        capture_mode, device_mode = describe_mode(
            self.config.use_mock_capture,
            self.config.use_mock_device,
            self.config.prefer_backend,
        )
        self.action_mode.setText(f"Mode: {capture_mode}")
        self.action_device.setText(f"Device: {device_mode}")

    def on_start(self):
        started = self.service.start()
        running = started and self.service.is_running()
        self.tray_icon.setIcon(self._make_tray_icon(running=running).icon())
        self._refresh_mode_labels()
        if not running:
            status = self.service.get_status()
            guidance = status.get("last_error_guidance") or "Run nanoleaf-kde-sync-doctor for diagnostics."
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                f"Start failed: {self.service.last_error or 'unknown error'}\n{guidance}",
                self.QSystemTrayIcon.MessageIcon.Warning,
                7000,
            )

    def on_stop(self):
        self.service.stop()
        self.service.join(timeout=3.0)
        self.tray_icon.setIcon(self._make_tray_icon(running=False).icon())
        self._refresh_mode_labels()

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
        self._refresh_mode_labels()

        if was_running:
            self.on_start()

    def on_status(self):
        status = self.service.get_status()
        connection_text = (
            "connected"
            if status.get("device_discovered")
            else ("mock device" if status.get("device_mode") == "mock" else "not connected")
        )
        summary = "\n".join(
            [
                f"Running: {status.get('running')} | Capture: {status.get('capture_mode')} ({status.get('capture_backend') or 'not-started'})",
                f"Requested backend: {status.get('requested_capture_backend')} | Device mode: {status.get('device_mode')}",
                f"Device: {connection_text} | model={status.get('device_model') or 'unknown'} zones={status.get('device_zone_count')}",
                f"frames={status.get('frames_sent')} errors={status.get('consecutive_errors')} kind={status.get('last_error_kind')}",
                f"last_error={status.get('last_error') or 'none'}",
                f"guidance={status.get('last_error_guidance') or 'none'}",
            ]
        )
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync status",
            summary,
            self.QSystemTrayIcon.MessageIcon.Information,
            9000,
        )

    def on_doctor(self):
        checks = run_doctor(include_device_probe=False)
        report = format_report(checks)
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync doctor",
            report[:800],
            self.QSystemTrayIcon.MessageIcon.Information,
            9000,
        )

    def on_smoke_test(self):
        try:
            from nanoleaf_sync.tools.smoke_test import main as smoke_main

            rc = smoke_main([])
            if rc == 0:
                title = "nanoleaf-kde-sync smoke test"
                msg = "Smoke test completed. See terminal output for details."
                icon = self.QSystemTrayIcon.MessageIcon.Information
            else:
                title = "nanoleaf-kde-sync smoke test"
                msg = f"Smoke test exited with code {rc}."
                icon = self.QSystemTrayIcon.MessageIcon.Warning
        except Exception as exc:
            title = "nanoleaf-kde-sync smoke test"
            msg = f"Smoke test failed to run: {exc}"
            icon = self.QSystemTrayIcon.MessageIcon.Warning

        self.tray_icon.showMessage(title, msg, icon, 8000)

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
