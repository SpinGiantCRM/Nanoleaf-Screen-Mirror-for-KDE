from __future__ import annotations

import argparse
import importlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import threading
import traceback

from nanoleaf_sync.config.store import ConfigManager, mode_config
from nanoleaf_sync.desktop_entry import (
    QT_DESKTOP_FILE_NAME,
    disable_autostart,
    enable_autostart,
    ensure_user_launcher_entry,
    launch_context_snapshot,
    redact_launch_token,
    user_autostart_path,
)
from nanoleaf_sync.service import NanoleafSyncService
from nanoleaf_sync.tools.output_format import describe_mode, summarize_command_output
from nanoleaf_sync.ui.display_configurator import DisplayConfiguratorDialog
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.settings_dialog import SettingsDialog

SELF_CHECK_IMPORTS: tuple[str, ...] = (
    "nanoleaf_sync.config.store",
    "nanoleaf_sync.service",
    "nanoleaf_sync.ui.tray_app",
)
_log = logging.getLogger(__name__)


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


def _configure_startup_logging() -> Path:
    log_dir = Path.home() / ".cache" / "nanoleaf-kde-sync"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "tray-startup.log"
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == str(log_path) for h in root.handlers):
        return log_path

    handler = RotatingFileHandler(log_path, maxBytes=512_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return log_path


def _show_gui_startup_error(message: str) -> None:
    try:
        qt = load_qt()
        app = qt["QApplication"].instance() or qt["QApplication"](sys.argv)
        qt["QMessageBox"].critical(None, "nanoleaf-kde-sync startup error", message)
        app.processEvents()
    except Exception:
        print(message, file=sys.stderr, flush=True)


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


def _build_auto_start_bridge(qt: dict[str, object], callback):
    class _AutoStartBridge(qt["QObject"]):
        result_ready = qt["pyqtSignal"](bool)

        def __init__(self):
            super().__init__()
            self.result_ready.connect(
                self._deliver_result,
                qt["Qt"].ConnectionType.QueuedConnection,
            )

        def _deliver_result(self, running: bool) -> None:
            callback(bool(running))

    return _AutoStartBridge()


class NanoleafTrayApp:
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
        self.QMessageBox = qt["QMessageBox"]
        self.Qt = qt["Qt"]
        self._auto_start_bridge = _build_auto_start_bridge(qt, self._handle_auto_start_result)
        self._set_qt_desktop_identity()

        self.app = qt["QApplication"](sys.argv)
        self.app.setApplicationName(QT_DESKTOP_FILE_NAME)
        self.app.setDesktopFileName(QT_DESKTOP_FILE_NAME)

        self.startup_log_path = _configure_startup_logging()
        _log.info("Startup log initialized at %s", self.startup_log_path)

        if not self.QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError(
                "System tray is unavailable in this session. Ensure KDE tray/StatusNotifier is enabled. "
                f"Diagnostics log: {self.startup_log_path}"
            )

        try:
            ensure_user_launcher_entry()
        except Exception as exc:
            _log.warning("Failed to ensure user launcher entry: %s", exc, exc_info=True)

        self.cfg_mgr = ConfigManager()
        self._startup_warning: str | None = None
        try:
            self._config_created = self.cfg_mgr.initialize(mode="full-real", force=False)
            self.config = self.cfg_mgr.load()
            self.service = NanoleafSyncService(config=self.config)
        except Exception as exc:
            self._startup_warning = (
                f"Failed to load config/service: {exc}. Using safe defaults; open Settings and save to repair your config."
            )
            self._config_created = False
            self.config = mode_config("diagnostic")
            self.service = NanoleafSyncService(config=self.config)

        self._idle_icon, self._running_icon = self._load_tray_icons()
        self.tray_icon = self.QSystemTrayIcon(self._idle_icon)
        self.tray_icon.setToolTip("nanoleaf-kde-sync")
        self.tray_icon.setContextMenu(self._make_menu())
        self._refresh_mode_labels()
        self.tray_icon.show()
        if not self.QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError(
                "System tray became unavailable during tray_icon registration. "
                f"Check StatusNotifier settings and startup log at {self.startup_log_path}."
            )

        self._show_startup_launch_diagnostic()
        if self._startup_warning:
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                self._startup_warning,
                self.QSystemTrayIcon.MessageIcon.Warning,
                10000,
            )
        if not self._config_created and bool(getattr(self.config, "start_on_launch", False)):
            self.QTimer.singleShot(0, self._start_after_launch)

    def _send_calibration_preview(self, colors: list[tuple[int, int, int]]) -> None:
        driver = None
        try:
            driver = self._make_preview_driver()
            driver.initialize()
            driver.send_frame(colors)
        except Exception as exc:
            _log.warning("Calibration preview send failed: %s", exc, exc_info=True)
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                f"Calibration test pattern failed: {exc}",
                self.QSystemTrayIcon.MessageIcon.Warning,
                5000,
            )
        finally:
            if driver is not None:
                try:
                    driver.close()
                except Exception as exc:
                    _log.debug("Calibration preview driver close failed: %s", exc, exc_info=True)

    def _make_preview_driver(self):
        return self.service._make_device_driver()

    def _set_qt_desktop_identity(self) -> None:
        for method_name in ("setDesktopFileName", "setApplicationName"):
            method = getattr(self.QApplication, method_name, None)
            if callable(method):
                method(QT_DESKTOP_FILE_NAME)

    def _show_startup_launch_diagnostic(self) -> None:
        context = launch_context_snapshot()
        startup_id = redact_launch_token(context.get("DESKTOP_STARTUP_ID"))
        activation = redact_launch_token(context.get("XDG_ACTIVATION_TOKEN"))
        _log.info(
            "Startup context: desktop_file=%s startup_id=%s activation=%s tray_available=%s tray_visible=%s",
            self.app.desktopFileName() or "unset",
            startup_id,
            activation,
            self.QSystemTrayIcon.isSystemTrayAvailable(),
            self.tray_icon.isVisible(),
        )
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync startup context",
            (
                f"Qt desktop file name: {self.app.desktopFileName() or 'unset'}\n"
                f"Desktop startup ID: {startup_id}\n"
                f"Activation token: {activation}\n"
                f"Log file: {self.startup_log_path}"
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
        selected_path = "none"
        for candidate in (
            Path(__file__).resolve().parents[3] / "assets" / "icons" / "hicolor" / "scalable" / "apps" / "nanoleaf-kde-sync.svg",
            Path(sys.prefix) / "share" / "icons" / "hicolor" / "scalable" / "apps" / "nanoleaf-kde-sync.svg",
        ):
            if candidate.exists():
                fallback_icon = self.QIcon(str(candidate))
                selected_path = str(candidate)
                break

        idle_icon = themed_idle if not themed_idle.isNull() else fallback_icon
        running_icon = themed_running if not themed_running.isNull() else idle_icon
        if idle_icon.isNull() or running_icon.isNull():
            qt = load_qt()
            pixmap = qt["QPixmap"](16, 16)
            pixmap.fill(qt["QColor"](88, 88, 88))
            fallback_generated_icon = self.QIcon(pixmap)
            if idle_icon.isNull():
                idle_icon = fallback_generated_icon
            if running_icon.isNull():
                running_icon = fallback_generated_icon

        _log.info(
            "Icon resolution: themed_idle_null=%s themed_running_null=%s fallback=%s final_idle_null=%s",
            themed_idle.isNull(),
            themed_running.isNull(),
            selected_path,
            idle_icon.isNull(),
        )
        return idle_icon, running_icon

    def _make_menu(self):
        menu = self.QMenu()
        self.action_start = self.QAction("Start", menu)
        self.action_stop = self.QAction("Stop", menu)
        self.action_settings = self.QAction("Settings", menu)
        self.action_display_wizard = self.QAction("Display Configurator", menu)
        self.action_troubleshooting = self.QAction("Help / Troubleshooting", menu)
        self.action_mode = self.QAction("Mode: --", menu)
        self.action_mode.setEnabled(False)
        self.action_device = self.QAction("Device: --", menu)
        self.action_device.setEnabled(False)
        self.action_status = self.QAction("Status", menu)
        self.action_enable_autostart = self.QAction("Enable autostart", menu)
        self.action_disable_autostart = self.QAction("Disable autostart", menu)
        self.action_reset_probe_cache = self.QAction("Reset Auto-Probe Cache (force fresh selection)", menu)
        self.action_doctor = self.QAction("Run Doctor", menu)
        self.action_smoke = self.QAction("Run Smoke Test", menu)
        self.action_quit = self.QAction("Quit", menu)

        self.action_start.triggered.connect(self.on_start)
        self.action_stop.triggered.connect(self.on_stop)
        self.action_settings.triggered.connect(self.on_settings)
        self.action_display_wizard.triggered.connect(self.on_display_configurator)
        self.action_troubleshooting.triggered.connect(self.on_troubleshooting)
        self.action_status.triggered.connect(self.on_status)
        self.action_enable_autostart.triggered.connect(self.on_enable_autostart)
        self.action_disable_autostart.triggered.connect(self.on_disable_autostart)
        self.action_reset_probe_cache.triggered.connect(self.on_reset_probe_cache)
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
        menu.addAction(self.action_display_wizard)
        menu.addAction(self.action_troubleshooting)
        menu.addAction(self.action_status)
        menu.addAction(self.action_enable_autostart)
        menu.addAction(self.action_disable_autostart)
        menu.addAction(self.action_reset_probe_cache)
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
            self._auto_start_bridge.result_ready.emit(running)

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

    def on_display_configurator(self) -> None:
        dlg = DisplayConfiguratorDialog(parent=None, cfg=self.config, calibration_sender=self._send_calibration_preview)
        if dlg.exec() != self.QDialog.DialogCode.Accepted:
            return
        was_running = self.service.is_running()
        if was_running:
            self.on_stop()
        self.config = dlg.updated_config()
        self.cfg_mgr.save(self.config)
        self.service = NanoleafSyncService(config=self.config)
        self._refresh_mode_labels()
        if was_running:
            self.on_start()
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync",
            "Display setup saved.",
            self.QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def on_settings(self):
        dlg = SettingsDialog(
            parent=None,
            cfg=self.config,
            calibration_sender=self._send_calibration_preview,
            runtime_status=self.service.get_status(),
        )
        if dlg.exec() != self.QDialog.DialogCode.Accepted:
            return
        if dlg.wants_display_configurator():
            self.on_display_configurator()
            return
        new_cfg = dlg.updated_config()
        self.cfg_mgr.save(new_cfg)
        self.config = new_cfg
        was_running = self.service.is_running()
        if was_running:
            self.on_stop()
        self.service = NanoleafSyncService(config=self.config)
        self._refresh_mode_labels()

        if was_running:
            self.on_start()


    def on_troubleshooting(self) -> None:
        guide_path = Path(__file__).resolve().parents[3] / "docs" / "TROUBLESHOOTING.md"
        if guide_path.exists():
            try:
                opened = subprocess.run(
                    ["xdg-open", str(guide_path)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if opened.returncode != 0:
                    raise RuntimeError(f"xdg-open exited with code {opened.returncode}")
                self.tray_icon.showMessage(
                    "nanoleaf-kde-sync",
                    f"Opened troubleshooting guide:\n{guide_path}",
                    self.QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
                return
            except Exception as exc:
                _log.warning("Unable to open troubleshooting guide with xdg-open: %s", exc, exc_info=True)

        self.QMessageBox.information(
            None,
            "nanoleaf-kde-sync troubleshooting",
            (
                "Run diagnostics from the tray menu:\n"
                "• Run Doctor\n"
                "• Run Smoke Test\n\n"
                "If those checks fail, open docs/TROUBLESHOOTING.md in the project source."
            ),
        )

    def on_status(self):
        status = self.service.get_status()
        connection_text = "connected" if status.get("device_discovered") else "not connected"
        summary = "\n".join(
            [
                f"Running: {status.get('running')} | Capture: {status.get('capture_mode')} ({status.get('capture_backend') or 'not-started'})",
                (
                    f"Requested backend: {status.get('requested_capture_backend')} | "
                    f"Effective backend: {status.get('effective_capture_backend') or 'unknown'}"
                ),
                (
                    f"Selection reason: {status.get('selection_reason')} | "
                    f"From auto probe: {status.get('from_auto_probe')}"
                ),
                f"Device mode: {status.get('device_mode')}",
                f"Device: {connection_text} | model={status.get('device_model') or 'unknown'} zones={status.get('device_zone_count')}",
                f"frames={status.get('frames_sent')} errors={status.get('consecutive_errors')} kind={status.get('last_error_kind')}",
                f"last_error={status.get('last_error') or 'none'}",
                f"guidance={status.get('last_error_guidance') or 'none'}",
            ]
        )
        self.tray_icon.showMessage("nanoleaf-kde-sync status", summary, self.QSystemTrayIcon.MessageIcon.Information, 9000)

    def on_doctor(self):
        self._run_command_async(label="doctor", argv=[sys.executable, "-m", "nanoleaf_sync.tools.doctor"])

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
            text = f"Autostart disabled.\nRemoved: {user_autostart_path()}" if removed else f"Autostart already disabled.\nPath: {user_autostart_path()}"
            self.tray_icon.showMessage("nanoleaf-kde-sync", text, self.QSystemTrayIcon.MessageIcon.Information, 6000)
        except Exception as exc:
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                f"Unable to disable autostart: {exc}",
                self.QSystemTrayIcon.MessageIcon.Warning,
                7000,
            )

    def on_smoke_test(self):
        self._run_command_async(label="smoke test", argv=[sys.executable, "-m", "nanoleaf_sync.tools.smoke_test"])

    def on_reset_probe_cache(self) -> None:
        try:
            self.config = self.cfg_mgr.reset_auto_probe_cache()
            if self.service.is_running():
                self.on_stop()
                self.service = NanoleafSyncService(config=self.config)
                self.on_start()
            else:
                self.service = NanoleafSyncService(config=self.config)
            self._refresh_mode_labels()
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                "Auto-probe cache reset. Next auto backend selection may re-probe.",
                self.QSystemTrayIcon.MessageIcon.Information,
                6000,
            )
        except Exception as exc:
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                f"Unable to reset auto-probe cache: {exc}",
                self.QSystemTrayIcon.MessageIcon.Warning,
                7000,
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
                result = subprocess.run(argv, capture_output=True, text=True, check=False)
                preview, rc = summarize_command_output(result.stdout, result.stderr, result.returncode)
                self.QTimer.singleShot(0, lambda: self._handle_tool_result(label=label, preview=preview, rc=rc))
            except Exception as exc:
                self.QTimer.singleShot(0, lambda exc=exc: self._handle_tool_error(label=label, error=exc))

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
        self.tray_icon.showMessage(f"nanoleaf-kde-sync {label}", f"Failed to launch: {error}", self.QSystemTrayIcon.MessageIcon.Warning, 8000)

    def on_quit(self):
        try:
            self.on_stop()
        finally:
            self.app.quit()

    def run(self):
        if bool(getattr(self.config, "wizard_completed", False)) is False:
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                "Display setup is not complete yet. Opening Display Configurator.",
                self.QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
            self.QTimer.singleShot(200, self.on_display_configurator)
        return self.app.exec()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description="nanoleaf-kde-sync tray entry point")
    parser.add_argument("--self-check", action="store_true", help="run non-interactive startup/import checks and exit")
    parser.add_argument(
        "--reset-probe-cache",
        action="store_true",
        help="clear persisted auto-probe winner/signature/timestamp and exit",
    )
    args = parser.parse_args(argv)
    if args.self_check:
        return _run_self_check()
    if args.reset_probe_cache:
        mgr = ConfigManager()
        cfg = mgr.reset_auto_probe_cache()
        print(
            f"Reset auto-probe cache in {mgr.path} "
            f"(policy={cfg.auto_probe_policy}, selected_backend={cfg.auto_selected_backend or 'none'}).",
            flush=True,
        )
        return 0

    log_path = _configure_startup_logging()
    try:
        NanoleafTrayApp().run()
        return 0
    except Exception as exc:
        traceback_text = "".join(traceback.format_exception(exc))
        logging.getLogger(__name__).exception("Tray startup failed")
        _show_gui_startup_error(f"{exc}\n\nDiagnostics log: {log_path}\n\n{traceback_text}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
