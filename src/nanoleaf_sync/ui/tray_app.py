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
import time
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
        "Diagnostic mock-capture mode is enabled. Screen capture is simulated, but USB output still needs hardware.\n"
        "You can switch to Real hardware mode any time in Settings.\n"
        "Start the app from the tray menu when ready."
    )


def _read_app_version() -> str:
    try:
        return (Path(__file__).resolve().parents[3] / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except Exception:
        return "unknown"


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
        set_quit_on_last_window_closed = getattr(self.app, "setQuitOnLastWindowClosed", None)
        if callable(set_quit_on_last_window_closed):
            set_quit_on_last_window_closed(False)

        self.startup_log_path = _configure_startup_logging()
        self._app_version = _read_app_version()
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
        self._preview_driver = None
        self._preview_paused_service = False
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

        if self._should_show_startup_launch_diagnostic():
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

        self._shutdown_in_progress = False
        self._shutdown_deadline = 0.0
        self._shutdown_poll_interval_s = 0.05
        self._shutdown_timeout_s = 1.5
        self._quit_finalized = False

    def _close_preview_driver(self, *, resume_service: bool = True) -> None:
        if self._preview_driver is not None:
            try:
                self._preview_driver.close()
            except Exception as exc:
                _log.debug("Calibration preview driver close failed: %s", exc, exc_info=True)
            self._preview_driver = None

        was_paused = self._preview_paused_service
        self._preview_paused_service = False
        if was_paused and resume_service and not self.service.is_running():
            self.service.start()

    def _acquire_preview_driver(self):
        if self._preview_driver is not None:
            return self._preview_driver
        if self.service.is_running():
            self._preview_paused_service = True
            self.on_stop()
        driver = self._make_preview_driver()
        driver.initialize()
        self._preview_driver = driver
        return driver

    def _send_calibration_preview(self, colors: list[tuple[int, int, int]]) -> None:
        try:
            driver = self._acquire_preview_driver()
            driver.send_frame(colors)
        except Exception as exc:
            _log.warning("Calibration preview send failed: %s", exc, exc_info=True)
            self._close_preview_driver(resume_service=True)
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                f"Calibration test pattern failed: {exc}",
                self.QSystemTrayIcon.MessageIcon.Warning,
                5000,
            )

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

    def _should_show_startup_launch_diagnostic(self) -> bool:
        env_value = str(os.environ.get("NANOLEAF_SHOW_STARTUP_DIAGNOSTIC", "") or "").strip().lower()
        env_enabled = env_value in {"1", "true", "yes", "on", "debug", "verbose"}
        return bool(self._startup_warning) or bool(getattr(self.config, "verbose", False)) or env_enabled

    def _load_tray_icons(self):
        themed_idle = self.QIcon.fromTheme("nanoleaf-kde-sync")
        if themed_idle.isNull():
            themed_idle = self.QIcon.fromTheme("preferences-desktop-color")
        themed_running = self.QIcon.fromTheme("media-playback-start")
        if themed_running.isNull():
            themed_running = self.QIcon.fromTheme("media-record")
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
            idle_pixmap = qt["QPixmap"](16, 16)
            idle_pixmap.fill(qt["QColor"](88, 88, 88))
            fallback_generated_icon = self.QIcon(idle_pixmap)
            running_pixmap = qt["QPixmap"](16, 16)
            running_pixmap.fill(qt["QColor"](60, 180, 75))
            fallback_running_icon = self.QIcon(running_pixmap)
            if idle_icon.isNull():
                idle_icon = fallback_generated_icon
            if running_icon.isNull():
                running_icon = fallback_running_icon

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
        self.action_display_wizard = self.QAction("Setup Wizard", menu)
        self.action_calibration_settings = self.QAction("Calibration & Testing (Settings)", menu)
        self.action_status = self.QAction("About / Status", menu)
        self.action_troubleshooting = self.QAction("Help / Troubleshooting", menu)
        self.action_enable_autostart = self.QAction("Enable autostart", menu)
        self.action_disable_autostart = self.QAction("Disable autostart", menu)
        self.action_reset_probe_cache = self.QAction("Reset Auto-Probe Cache (force fresh selection)", menu)
        self.action_launch_diagnostics = self.QAction("Show launch diagnostics", menu)
        self.action_doctor = self.QAction("Run Doctor", menu)
        self.action_smoke = self.QAction("Run Smoke Test", menu)
        self.action_quit = self.QAction("Quit", menu)

        self.action_start.triggered.connect(self.on_start)
        self.action_stop.triggered.connect(self.on_stop)
        self.action_settings.triggered.connect(self.on_settings)
        self.action_display_wizard.triggered.connect(self.on_display_configurator)
        self.action_troubleshooting.triggered.connect(self.on_troubleshooting)
        self.action_calibration_settings.triggered.connect(self.on_open_calibration_settings)
        self.action_status.triggered.connect(self.on_status)
        self.action_enable_autostart.triggered.connect(self.on_enable_autostart)
        self.action_disable_autostart.triggered.connect(self.on_disable_autostart)
        self.action_reset_probe_cache.triggered.connect(self.on_reset_probe_cache)
        self.action_launch_diagnostics.triggered.connect(self.on_show_launch_diagnostics)
        self.action_doctor.triggered.connect(self.on_doctor)
        self.action_smoke.triggered.connect(self.on_smoke_test)
        self.action_quit.triggered.connect(self.on_quit)

        advanced_menu = self.QMenu("Troubleshooting / Advanced", menu)
        advanced_menu.addAction(self.action_troubleshooting)
        advanced_menu.addAction(self.action_calibration_settings)
        advanced_menu.addSeparator()
        advanced_menu.addAction(self.action_doctor)
        advanced_menu.addAction(self.action_smoke)
        advanced_menu.addAction(self.action_reset_probe_cache)
        advanced_menu.addAction(self.action_launch_diagnostics)
        advanced_menu.addSeparator()
        advanced_menu.addAction(self.action_enable_autostart)
        advanced_menu.addAction(self.action_disable_autostart)

        menu.addAction(self.action_start)
        menu.addAction(self.action_stop)
        menu.addAction(self.action_settings)
        menu.addAction(self.action_display_wizard)
        menu.addAction(self.action_status)
        menu.addMenu(advanced_menu)
        menu.addSeparator()
        menu.addAction(self.action_quit)
        return menu

    def _refresh_mode_labels(self) -> None:
        running = self.service.is_running()
        status = self.service.get_status()
        capture_mode, device_mode = describe_mode(
            self.config.use_mock_capture,
            self.config.prefer_backend,
            service_running=running,
            device_discovered=bool(status.get("device_discovered")),
            device_model=str(status.get("device_model") or ""),
        )
        effective_backend = status.get("effective_capture_backend") or ("not-started" if not running else "unresolved")
        selected_backend = status.get("selected_capture_backend") or "unresolved"
        unresolved_reason = status.get("backend_unresolved_reason") or ""
        self.tray_icon.setToolTip(
            "nanoleaf-kde-sync\n"
            f"State: {'running' if running else 'idle'}\n{capture_mode}\n{device_mode}\n"
            f"Requested backend policy: {self.config.prefer_backend}\n"
            f"Selected backend: {selected_backend}\n"
            f"Effective backend: {effective_backend}"
            + (f"\nBackend note: {unresolved_reason}" if unresolved_reason else "")
        )
        self.action_status.setText(f"About / Status ({'Running' if running else 'Idle'})")

    def on_start(self):
        close_preview = getattr(self, "_close_preview_driver", None)
        if callable(close_preview):
            close_preview(resume_service=False)
        try:
            started = self.service.start()
            running = started and self.service.is_running()
        except Exception as exc:
            _log.exception("Unhandled exception while starting service from tray action")
            running = False
            # Recreate service instance so a failed start attempt does not leave
            # runtime lifecycle objects in a broken/unreopenable state.
            self.service = NanoleafSyncService(config=self.config)
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                f"Start failed with exception: {exc}",
                self.QSystemTrayIcon.MessageIcon.Warning,
                7000,
            )

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

    def _request_stop(self) -> None:
        try:
            self.service.stop()
        except Exception as exc:
            _log.warning("Service stop request failed: %s", exc, exc_info=True)

    def _set_idle_ui_state(self) -> None:
        self.tray_icon.setIcon(self._idle_icon)
        self._refresh_mode_labels()

    def _schedule_stop_warning(self, service) -> None:
        def _warn_if_still_running() -> None:
            try:
                if service.is_running():
                    _log.warning("Service still running after stop timeout")
            except Exception as exc:
                _log.warning("Unable to query service stop status: %s", exc, exc_info=True)

        self.QTimer.singleShot(int(self._shutdown_timeout_s * 1000), _warn_if_still_running)

    def on_stop(self):
        service = self.service
        self._request_stop()
        self._set_idle_ui_state()
        if not bool(getattr(self, "_shutdown_in_progress", False)):
            self._schedule_stop_warning(service)

    def _start_after_launch(self) -> None:
        def worker() -> None:
            try:
                started = self.service.start()
                running = started and self.service.is_running()
            except Exception:
                _log.exception("Unhandled exception during auto-start")
                running = False
            self._auto_start_bridge.result_ready.emit(running)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_auto_start_result(self, running: bool) -> None:
        self.tray_icon.setIcon(self._running_icon if running else self._idle_icon)
        self._refresh_mode_labels()
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
        was_running = self.service.is_running() or bool(getattr(self, "_preview_paused_service", False))
        accepted = dlg.exec() == self.QDialog.DialogCode.Accepted
        close_preview = getattr(self, "_close_preview_driver", None)
        if callable(close_preview):
            close_preview(resume_service=False)
        if not accepted:
            if was_running:
                self.on_start()
            return

        was_first_run = not bool(getattr(self.config, "wizard_completed", False))
        if was_running and self.service.is_running():
            self.on_stop()
        self.config = dlg.updated_config()
        self.cfg_mgr.save(self.config)
        self.service = NanoleafSyncService(config=self.config)
        self._refresh_mode_labels()
        if was_running:
            self.on_start()
        message = "Display setup saved."
        if was_first_run:
            mode = "diagnostic" if bool(getattr(self.config, "use_mock_capture", False)) else "full-real"
            message = f"{message}\n\n{first_run_message(mode)}"
        self.tray_icon.showMessage("nanoleaf-kde-sync", message, self.QSystemTrayIcon.MessageIcon.Information, 6000)

    def on_settings(self):
        dlg = SettingsDialog(
            parent=None,
            cfg=self.config,
            calibration_sender=self._send_calibration_preview,
            runtime_status=self.service.get_status(),
        )
        was_running = self.service.is_running() or bool(getattr(self, "_preview_paused_service", False))
        accepted = dlg.exec() == self.QDialog.DialogCode.Accepted
        close_preview = getattr(self, "_close_preview_driver", None)
        if callable(close_preview):
            close_preview(resume_service=False)
        if not accepted:
            if was_running:
                self.on_start()
            return

        if dlg.wants_display_configurator():
            self.config = dlg.updated_config()
            self.cfg_mgr.save(self.config)
            self.on_display_configurator()
            return
        new_cfg = dlg.updated_config()
        self.cfg_mgr.save(new_cfg)
        self.config = new_cfg
        if was_running and self.service.is_running():
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
        running = bool(status.get("running"))
        connected = bool(status.get("device_discovered"))
        connection_text = "Connected" if connected else ("Searching / not connected" if running else "Not started")
        last_error = status.get("last_error")
        summary = "\n".join(
            [
                f"Version: {self._app_version}",
                f"State: {'Running' if running else 'Idle'}",
                f"Capture method: {status.get('effective_capture_backend') or self.config.prefer_backend}",
                f"USB device: {connection_text}",
                f"Device model: {status.get('device_model') or 'unknown'}",
                f"Last issue: {last_error or 'None'}",
                f"Help: {status.get('last_error_guidance') or 'Open Help / Troubleshooting from the tray menu.'}",
            ]
        )
        details = "\n".join(
            [
                f"Requested backend: {status.get('requested_capture_backend')}",
                f"Selected backend: {status.get('selected_capture_backend')}",
                f"Selection reason: {status.get('selection_reason')}",
                f"Frames sent: {status.get('frames_sent')}",
                f"Consecutive errors: {status.get('consecutive_errors')}",
            ]
        )
        dialog = self.QDialog()
        dialog.setWindowTitle("nanoleaf-kde-sync · About / Status")
        layout = self.QVBoxLayout()
        layout.addWidget(self.QLabel(summary))
        details_label = self.QLabel(f"Technical details:\n{details}")
        layout.addWidget(details_label)
        close_button = self.QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.setLayout(layout)
        dialog.exec()
        self._refresh_mode_labels()

    def on_open_calibration_settings(self) -> None:
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync",
            "Calibration tools moved to Settings → Calibration & Testing.",
            self.QSystemTrayIcon.MessageIcon.Information,
            4500,
        )
        self.on_settings()

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

    def on_show_launch_diagnostics(self) -> None:
        self._show_startup_launch_diagnostic()

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

    def _poll_shutdown_completion(self) -> None:
        if not self._shutdown_in_progress:
            return
        if not self.service.is_running():
            self._finalize_quit()
            return
        if time.monotonic() >= self._shutdown_deadline:
            _log.warning("Service still running at quit timeout; forcing app exit")
            self._finalize_quit()
            return
        self.QTimer.singleShot(int(self._shutdown_poll_interval_s * 1000), self._poll_shutdown_completion)

    def _finalize_quit(self) -> None:
        if self._quit_finalized:
            return
        self._quit_finalized = True
        self._shutdown_in_progress = False
        self.app.quit()

    def on_quit(self):
        if self._quit_finalized:
            return
        if self._shutdown_in_progress:
            return

        self._shutdown_in_progress = True
        self._shutdown_deadline = time.monotonic() + self._shutdown_timeout_s
        self._close_preview_driver(resume_service=False)
        self._request_stop()
        self._set_idle_ui_state()
        self.QTimer.singleShot(0, self._poll_shutdown_completion)

    def run(self):
        if bool(getattr(self.config, "wizard_completed", False)) is False:
            self.on_display_configurator()
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
