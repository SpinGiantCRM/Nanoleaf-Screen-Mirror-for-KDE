from __future__ import annotations

import subprocess
import sys
import threading

from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.service import NanoleafSyncService

from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.settings_dialog import SettingsDialog


def describe_mode(use_mock_capture: bool, use_mock_device: bool, prefer_backend: str) -> tuple[str, str]:
    capture_mode = "Mock capture" if use_mock_capture else f"Capture: {prefer_backend}"
    device_mode = "Mock device" if use_mock_device else "Real USB device"
    return capture_mode, device_mode


def summarize_command_output(stdout: str, stderr: str, returncode: int) -> tuple[str, int]:
    combined = (stdout or "").strip()
    err = (stderr or "").strip()
    if err:
        combined = f"{combined}\n{err}".strip() if combined else err

    if not combined:
        combined = "No command output captured."

    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    preview = " | ".join(lines[:3])[:700]
    return preview, returncode


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
        self.QTimer = qt["QTimer"]
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
        self._run_command_async(
            label="doctor",
            argv=[sys.executable, "-m", "nanoleaf_sync.tools.doctor"],
        )

    def on_smoke_test(self):
        self._run_command_async(
            label="smoke test",
            argv=[sys.executable, "-m", "nanoleaf_sync.tools.smoke_test"],
        )

    def _run_command_async(self, label: str, argv: list[str]) -> None:
        self.action_doctor.setEnabled(False)
        self.action_smoke.setEnabled(False)
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync",
            f"Running {label} in background…",
            self.QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

        def worker() -> None:
            try:
                result = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                preview, rc = summarize_command_output(result.stdout, result.stderr, result.returncode)
                self.QTimer.singleShot(0, lambda: self._handle_tool_result(label=label, preview=preview, rc=rc))
            except Exception as exc:
                self.QTimer.singleShot(0, lambda: self._handle_tool_error(label=label, error=exc))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_tool_result(self, label: str, preview: str, rc: int) -> None:
        self.action_doctor.setEnabled(True)
        self.action_smoke.setEnabled(True)
        is_ok = rc == 0
        self.tray_icon.showMessage(
            f"nanoleaf-kde-sync {label}",
            f"{'Completed successfully' if is_ok else f'Finished with exit code {rc}'}.\n{preview}",
            self.QSystemTrayIcon.MessageIcon.Information if is_ok else self.QSystemTrayIcon.MessageIcon.Warning,
            10000,
        )

    def _handle_tool_error(self, label: str, error: Exception) -> None:
        self.action_doctor.setEnabled(True)
        self.action_smoke.setEnabled(True)
        self.tray_icon.showMessage(
            f"nanoleaf-kde-sync {label}",
            f"Failed to launch: {error}",
            self.QSystemTrayIcon.MessageIcon.Warning,
            8000,
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
