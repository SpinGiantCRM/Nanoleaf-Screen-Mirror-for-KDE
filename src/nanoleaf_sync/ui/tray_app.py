from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading

from nanoleaf_sync.config.store import ConfigManager, mode_config
from nanoleaf_sync.desktop_entry import (
    QT_DESKTOP_FILE_NAME,
    disable_autostart,
    ensure_user_launcher_entry,
    enable_autostart,
    launch_context_snapshot,
    redact_launch_token,
    user_autostart_path,
)
from nanoleaf_sync.service import NanoleafSyncService

from nanoleaf_sync.tools.output_format import describe_mode, summarize_command_output
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.settings_dialog import SettingsDialog


SELF_CHECK_IMPORTS: tuple[str, ...] = (
    "nanoleaf_sync.config.store",
    "nanoleaf_sync.service",
    "nanoleaf_sync.ui.tray_app",
)
_log = logging.getLogger(__name__)


def _run_self_check() -> int:
    checks: list[dict[str, str]] = []
    diagnostics: dict[str, object] = {
        "kind": "nanoleaf-kde-sync-self-check",
        "status": "ok",
        "pid": os.getpid(),
        "checks": checks,
    }

    try:
        for module_name in SELF_CHECK_IMPORTS:
            importlib.import_module(module_name)
            checks.append({"check": f"import:{module_name}", "status": "ok"})
        load_qt()
        checks.append({"check": "qt:load_qt", "status": "ok"})
    except Exception as exc:
        diagnostics["status"] = "error"
        diagnostics["error"] = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }
        checks.append({"check": "self-check", "status": "failed"})
        print(json.dumps(diagnostics, sort_keys=True), flush=True)
        return 1

    print(json.dumps(diagnostics, sort_keys=True), flush=True)
    return 0


def first_run_message(mode: str) -> str:
    normalized = (mode or "").strip().lower()
    if normalized == "full-real":
        return (
            "Real hardware mode is now selected.\n"
            "If the light is not detected, open Help → Troubleshooting from the tray menu."
        )
    return (
        "Mock (no hardware) mode is enabled. You can switch to Real hardware mode any time in Settings.\n"
        "Start the app from the tray menu when ready."
    )


class NanoleafTrayApp:
    """
    KDE/Linux system tray UI for starting/stopping the background service.
    """

    def __init__(self) -> None:
        qt = load_qt()
        self.QApplication = qt["QApplication"]
        self.QSystemTrayIcon = qt["QSystemTrayIcon"]
        self.QIcon = qt["QIcon"]
        self.QAction = qt["QAction"]
        self.QMenu = qt["QMenu"]
        self.QDialog = qt["QDialog"]
        self.QLabel = qt["QLabel"]
        self.QPushButton = qt["QPushButton"]
        self.QVBoxLayout = qt["QVBoxLayout"]
        self.QTimer = qt["QTimer"]
        self.Qt = qt["Qt"]
        self._set_qt_desktop_identity()

        self.app = qt["QApplication"](sys.argv)
        self.app.setApplicationName(QT_DESKTOP_FILE_NAME)
        self.app.setDesktopFileName(QT_DESKTOP_FILE_NAME)
        try:
            ensure_user_launcher_entry()
        except Exception as exc:
            # Keep startup resilient even if desktop entry patching fails.
            _log.warning("Failed to ensure user launcher entry: %s", exc, exc_info=True)
        self.cfg_mgr = ConfigManager()
        self._startup_warning: str | None = None
        try:
            self._config_created = self.cfg_mgr.initialize(mode="full-real", force=False)
            self.config = self.cfg_mgr.load()
            self.service = NanoleafSyncService(config=self.config)
        except Exception as exc:
            self._startup_warning = (
                f"Failed to load config/service: {exc}. "
                "Using safe defaults; open Settings and save to repair your config."
            )
            self._config_created = False
            self.config = mode_config("diagnostic")
            self.service = NanoleafSyncService(config=self.config)

        self._idle_icon, self._running_icon = self._load_tray_icons()
        self.tray_icon = self.QSystemTrayIcon(self._idle_icon)
        self.tray_icon.setContextMenu(self._make_menu())
        self._refresh_mode_labels()
        self.tray_icon.show()
        self._show_startup_launch_diagnostic()
        if self._config_created:
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                (
                    "First launch setup is ready.\n"
                    "Choose diagnostics mode or real capture mode in the welcome dialog."
                ),
                self.QSystemTrayIcon.MessageIcon.Information,
                7000,
            )
        if self._startup_warning:
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                self._startup_warning,
                self.QSystemTrayIcon.MessageIcon.Warning,
                10000,
            )
        if not self._config_created and bool(getattr(self.config, "start_on_launch", False)):
            self.QTimer.singleShot(0, self._start_after_launch)

    def _set_qt_desktop_identity(self) -> None:
        for method_name in ("setDesktopFileName", "setApplicationName"):
            method = getattr(self.QApplication, method_name, None)
            if callable(method):
                method(QT_DESKTOP_FILE_NAME)

    def _show_startup_launch_diagnostic(self) -> None:
        context = launch_context_snapshot()
        startup_id = redact_launch_token(context.get("DESKTOP_STARTUP_ID"))
        activation = redact_launch_token(context.get("XDG_ACTIVATION_TOKEN"))
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync startup context",
            (
                f"Qt desktop file name: {self.app.desktopFileName() or 'unset'}\n"
                f"Desktop startup ID: {startup_id}\n"
                f"Activation token: {activation}"
            ),
            self.QSystemTrayIcon.MessageIcon.Information,
            6000,
        )

    def _load_tray_icons(self):
        themed_idle = self.QIcon.fromTheme("nanoleaf-kde-sync")
        if themed_idle.isNull():
            themed_idle = self.QIcon.fromTheme("preferences-desktop-color")
        themed_running = self.QIcon.fromTheme("media-playback-start")
        if themed_running.isNull():
            themed_running = self.QIcon.fromTheme("nanoleaf-kde-sync")

        fallback_icon = self.QIcon()
        for candidate in (
            Path(__file__).resolve().parents[3] / "assets" / "icons" / "hicolor" / "scalable" / "apps" / "nanoleaf-kde-sync.svg",
            Path(sys.prefix) / "share" / "icons" / "hicolor" / "scalable" / "apps" / "nanoleaf-kde-sync.svg",
        ):
            if candidate.exists():
                fallback_icon = self.QIcon(str(candidate))
                break

        idle_icon = themed_idle if not themed_idle.isNull() else fallback_icon
        running_icon = themed_running if not themed_running.isNull() else idle_icon
        return idle_icon, running_icon

    def _make_menu(self):
        menu = self.QMenu()
        self.action_start = self.QAction("Start", menu)
        self.action_stop = self.QAction("Stop", menu)
        self.action_settings = self.QAction("Settings", menu)
        self.action_troubleshooting = self.QAction("Help / Troubleshooting", menu)
        self.action_mode = self.QAction("Mode: --", menu)
        self.action_mode.setEnabled(False)
        self.action_device = self.QAction("Device: --", menu)
        self.action_device.setEnabled(False)
        self.action_status = self.QAction("Status", menu)
        self.action_enable_autostart = self.QAction("Enable autostart", menu)
        self.action_disable_autostart = self.QAction("Disable autostart", menu)
        self.action_doctor = self.QAction("Run Doctor", menu)
        self.action_smoke = self.QAction("Run Smoke Test", menu)
        self.action_quit = self.QAction("Quit", menu)

        self.action_start.triggered.connect(self.on_start)
        self.action_stop.triggered.connect(self.on_stop)
        self.action_settings.triggered.connect(self.on_settings)
        self.action_troubleshooting.triggered.connect(self.on_troubleshooting)
        self.action_status.triggered.connect(self.on_status)
        self.action_enable_autostart.triggered.connect(self.on_enable_autostart)
        self.action_disable_autostart.triggered.connect(self.on_disable_autostart)
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
        menu.addAction(self.action_troubleshooting)
        menu.addAction(self.action_status)
        menu.addAction(self.action_enable_autostart)
        menu.addAction(self.action_disable_autostart)
        menu.addAction(self.action_doctor)
        menu.addAction(self.action_smoke)
        menu.addAction(self.action_quit)
        return menu

    def _refresh_mode_labels(self) -> None:
        capture_mode, device_mode = describe_mode(self.config.use_mock_capture, self.config.prefer_backend)
        self.action_mode.setText(f"Mode: {capture_mode}")
        self.action_device.setText(f"Device: {device_mode}")

    def on_start(self):
        started = self.service.start()
        running = started and self.service.is_running()
        self.tray_icon.setIcon(self._running_icon if running else self._idle_icon)
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
        self.service.join(timeout=0.5)
        self.tray_icon.setIcon(self._idle_icon)
        self._refresh_mode_labels()

    def _start_after_launch(self) -> None:
        def worker() -> None:
            started = self.service.start()
            running = started and self.service.is_running()
            self.QTimer.singleShot(0, lambda: self._handle_auto_start_result(running))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_auto_start_result(self, running: bool) -> None:
        self.tray_icon.setIcon(self._running_icon if running else self._idle_icon)
        if running:
            return
        status = self.service.get_status()
        guidance = status.get("last_error_guidance") or "Run nanoleaf-kde-sync-doctor for diagnostics."
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync",
            f"Auto-start failed: {self.service.last_error or 'unknown error'}\n{guidance}",
            self.QSystemTrayIcon.MessageIcon.Warning,
            7000,
        )

    def on_settings(self):
        dlg = SettingsDialog(parent=None, cfg=self.config)
        if dlg.exec() != self.QDialog.DialogCode.Accepted:
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
            else "not connected"
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

    def on_enable_autostart(self) -> None:
        try:
            path = enable_autostart()
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                f"Autostart enabled.\nDesktop file: {path}",
                self.QSystemTrayIcon.MessageIcon.Information,
                6000,
            )
        except Exception as exc:
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                f"Unable to enable autostart: {exc}",
                self.QSystemTrayIcon.MessageIcon.Warning,
                7000,
            )

    def on_disable_autostart(self) -> None:
        try:
            removed = disable_autostart()
            text = (
                f"Autostart disabled.\nRemoved: {user_autostart_path()}"
                if removed
                else f"Autostart already disabled.\nPath: {user_autostart_path()}"
            )
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                text,
                self.QSystemTrayIcon.MessageIcon.Information,
                6000,
            )
        except Exception as exc:
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                f"Unable to disable autostart: {exc}",
                self.QSystemTrayIcon.MessageIcon.Warning,
                7000,
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
                self.QTimer.singleShot(
                    0,
                    lambda exc=exc: self._handle_tool_error(label=label, error=exc),
                )

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

    def _show_first_run_dialog(self) -> None:
        qdialog = self.QDialog()
        qdialog.setWindowTitle("Welcome to nanoleaf-kde-sync")
        layout = self.QVBoxLayout()
        layout.addWidget(
            self.QLabel(
                (
                    "Choose how you want to start:\n\n"
                    "• Diagnostics mode: synthetic capture for setup checks.\n"
                    "• Real Nanoleaf mode: use your connected USB light strip."
                )
            )
        )
        demo_button = self.QPushButton("Start in Diagnostics mode")
        real_button = self.QPushButton("Use Real Nanoleaf mode")
        layout.addWidget(demo_button)
        layout.addWidget(real_button)
        qdialog.setLayout(layout)

        def apply_mode(mode: str) -> None:
            self.config = mode_config(mode)
            self.cfg_mgr.save(self.config)
            self.service = NanoleafSyncService(config=self.config)
            self._refresh_mode_labels()
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                first_run_message(mode),
                self.QSystemTrayIcon.MessageIcon.Information,
                8000,
            )
            qdialog.accept()

        demo_button.clicked.connect(lambda: apply_mode("diagnostic"))
        real_button.clicked.connect(lambda: apply_mode("full-real"))
        qdialog.exec()

    def on_troubleshooting(self) -> None:
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync help",
            (
                "Need help?\n"
                "1) Try Diagnostics mode from first-run setup.\n"
                "2) For real USB mode, run: nanoleaf-kde-sync-doctor --device\n"
                "3) Full guide: docs/TROUBLESHOOTING.md"
            ),
            self.QSystemTrayIcon.MessageIcon.Information,
            10000,
        )

    def run(self):
        if self._config_created:
            self._show_first_run_dialog()
        return self.app.exec()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description="nanoleaf-kde-sync tray entry point")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="run non-interactive startup/import checks and exit",
    )
    args = parser.parse_args(argv)
    if args.self_check:
        return _run_self_check()
    NanoleafTrayApp().run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
