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

import nanoleaf_sync
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
from nanoleaf_sync.compat.update_checker import (
    check_for_updates,
    manual_check_message,
    mark_update_notified,
    should_notify_for_update,
    update_notification_message,
)
from nanoleaf_sync.service import NanoleafSyncService
from nanoleaf_sync.tools.output_format import describe_mode, summarize_command_output
from nanoleaf_sync.ui.display_configurator import DisplayConfiguratorDialog
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.live_diagnostics import LiveDiagnosticsDialog
from nanoleaf_sync.ui.settings_dialog import SettingsDialog
from nanoleaf_sync.runtime.output_session import OutputSessionController
from nanoleaf_sync.runtime.readiness_check import (
    NEEDS_CALIBRATION_STATUS,
    CONFIG_PROBLEM_STATUS,
    ReadinessReport,
    run_readiness_check,
)

SELF_CHECK_IMPORTS: tuple[str, ...] = (
    "nanoleaf_sync.compat.update_checker",
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
    return nanoleaf_sync.__version__


def _configure_startup_logging() -> Path:
    log_dir = Path.home() / ".cache" / "nanoleaf-kde-sync"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "tray-startup.log"
    root = logging.getLogger()
    if any(
        isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == str(log_path)
        for h in root.handlers
    ):
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
        _log.debug("Unable to show GUI startup error dialog", exc_info=True)
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
        self._load_stylesheet()
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
        self._output_session = OutputSessionController()
        try:
            self._config_created = self.cfg_mgr.initialize(mode="full-real", force=False)
            self.config = self.cfg_mgr.load()
            self.service = NanoleafSyncService(config=self.config)
        except Exception as exc:
            self._startup_warning = f"Failed to load config/service: {exc}. Using safe defaults; open Settings and save to repair your config."
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
        kde_upgrade_notice = getattr(self.service, "kde_upgrade_notice", None)
        if kde_upgrade_notice:
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                kde_upgrade_notice,
                self.QSystemTrayIcon.MessageIcon.Information,
                10000,
            )
        # Only auto-start after a successful config load; skip when config
        # was broken and we fell back to diagnostic mode.
        if (
            not self._config_created
            and not self._startup_warning
            and bool(getattr(self.config, "start_on_launch", False))
        ):
            self.QTimer.singleShot(0, self._start_after_launch)

        self._shutdown_in_progress = False
        self._shutdown_deadline = 0.0
        self._shutdown_poll_interval_s = 0.05
        self._shutdown_timeout_s = 5.0
        self._quit_finalized = False
        self._stop_poll_deadline = 0.0
        self._stop_poll_count = 0
        self._startup_refresh_deadline = 0.0
        self._schedule_startup_update_check()

    def _quick_setup_readiness(self) -> ReadinessReport:
        """Fast config/calibration readiness check without capture/device probes."""
        return run_readiness_check(
            config=self.config,
            runtime_status=self._safe_service_status(),
            source_zone_count=None,
            capture_probe=lambda _cfg: None,
            device_probe=lambda _cfg: None,
        )

    def _schedule_startup_refresh(self) -> None:
        """Poll tray labels while startup is in-flight (portal consent, first frame, etc.)."""
        self._startup_refresh_deadline = time.monotonic() + 120.0
        self.QTimer.singleShot(250, self._poll_startup_refresh)

    def _poll_startup_refresh(self) -> None:
        status = self._safe_service_status()
        startup_state = str(status.get("startup_state") or "")
        self._safe_refresh_mode_labels()
        if startup_state in {"starting", "waiting_for_screen_selection"}:
            if time.monotonic() < getattr(self, "_startup_refresh_deadline", 0.0):
                self.QTimer.singleShot(500, self._poll_startup_refresh)
            return
        if startup_state == "running":
            self.tray_icon.setIcon(self._running_icon)
            return
        if startup_state in {"idle", "error"} and not self._service_running():
            guidance = status.get("last_error_guidance") or ""
            if status.get("last_error") or status.get("start_failure_reason"):
                self.tray_icon.showMessage(
                    "nanoleaf-kde-sync",
                    f"Start failed: {status.get('last_error') or status.get('start_failure_reason')}\n{guidance}",
                    self.QSystemTrayIcon.MessageIcon.Warning,
                    7000,
                )

    def _close_preview_driver(self, *, resume_service: bool = True) -> None:
        if self._preview_driver is not None:
            try:
                self._preview_driver.close()
            except Exception as exc:
                _log.debug("Calibration preview driver close failed: %s", exc, exc_info=True)
            self._preview_driver = None

        was_paused = self._preview_paused_service
        self._preview_paused_service = False
        self._output_session.release("setup")
        if was_paused and resume_service and not self.service.is_running():
            self.service.start()

    def _acquire_preview_driver(self):
        if self._preview_driver is not None:
            return self._preview_driver
        running = self.service.is_running()
        self._output_session.acquire("setup", mirroring_active=running)
        if running:
            self._preview_paused_service = True
            self.service.stop()
            self.service.join(timeout=1.2)
        driver = self._make_preview_driver()
        driver.initialize()
        self._preview_driver = driver
        return driver

    def _send_calibration_preview(self, colors: list[tuple[int, int, int]]) -> None:
        diagnostics = self._build_calibration_preview_diagnostics(frame_color_count=len(colors))
        try:
            self._reconcile_calibration_preview_zone_config(diagnostics=diagnostics)
        except RuntimeError as exc:
            message = f"Calibration test pattern failed: {exc}"
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                message,
                self.QSystemTrayIcon.MessageIcon.Warning,
                5000,
            )
            _log.warning(message)
            return
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                driver = self._acquire_preview_driver()
                diagnostics = self._build_calibration_preview_diagnostics(
                    frame_color_count=len(colors),
                    driver=driver,
                )
                _log.info("Calibration preview diagnostics: %s", diagnostics)
                driver.send_frame(colors)
                return
            except Exception as exc:
                _log.warning(
                    "Calibration preview send failed on attempt %d/%d: %s",
                    attempt,
                    max_attempts,
                    exc,
                    exc_info=True,
                )
                self._close_preview_driver(resume_service=True)
                if attempt < max_attempts:
                    continue
                self.tray_icon.showMessage(
                    "nanoleaf-kde-sync",
                    f"Calibration test pattern failed: {exc} | diagnostics={diagnostics}",
                    self.QSystemTrayIcon.MessageIcon.Warning,
                    5000,
                )

    def _build_calibration_preview_diagnostics(
        self, *, frame_color_count: int, driver=None
    ) -> dict[str, int]:
        status = self.service.get_status()
        detected_zone_count = int(
            status.get("detected_device_zone_count") or status.get("device_zone_count") or 0
        )
        top_level_zone_count = int(getattr(self.config, "device_zone_count", 0) or 0)
        nested_zone_count = int(
            getattr(getattr(self.config, "calibration", None), "device_zone_count", 0) or 0
        )
        driver_instance = driver if driver is not None else getattr(self, "_preview_driver", None)
        driver_configured = int(getattr(driver_instance, "_configured_zone_count", 0) or 0)
        driver_effective = int(getattr(driver_instance, "zone_count", 0) or 0)
        return {
            "detected_device_zone_count": detected_zone_count,
            "config_device_zone_count": top_level_zone_count,
            "config_calibration_device_zone_count": nested_zone_count,
            "ui_calibration_state_device_zone_count": int(frame_color_count or 0),
            "driver_configured_zone_count": driver_configured,
            "driver_effective_zone_count": driver_effective,
            "frame_color_count": int(frame_color_count or 0),
        }

    def _reconcile_calibration_preview_zone_config(self, *, diagnostics: dict[str, int]) -> None:
        configured = int(diagnostics.get("config_device_zone_count", 0) or 0)
        frame_count = int(diagnostics.get("frame_color_count", 0) or 0)
        target = configured
        if frame_count > 0 and target > 0 and frame_count > target:
            raise RuntimeError(
                "Config sync error before driver send: "
                f"frame_colors={frame_count} but synced_device_zone_count={target}. "
                f"diagnostics={diagnostics}"
            )

    def _make_preview_driver(self):
        return self.service.make_device_driver(enable_live_frame_write_optimization=False)

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

    def _should_show_startup_launch_diagnostic(self) -> bool:
        env_value = (
            str(os.environ.get("NANOLEAF_SHOW_STARTUP_DIAGNOSTIC", "") or "").strip().lower()
        )
        env_enabled = env_value in {"1", "true", "yes", "on", "debug", "verbose"}
        return (
            bool(self._startup_warning)
            or bool(getattr(self.config, "verbose", False))
            or env_enabled
        )

    def _load_stylesheet(self) -> None:
        qss_path = Path(__file__).resolve().parent / "style.qss"
        if qss_path.exists():
            self.app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
        else:
            _log.warning(
                "Stylesheet not found at %s; continuing without custom theme",
                qss_path,
            )

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
            Path(__file__).resolve().parents[3]
            / "assets"
            / "icons"
            / "hicolor"
            / "scalable"
            / "apps"
            / "nanoleaf-kde-sync.svg",
            Path(sys.prefix)
            / "share"
            / "icons"
            / "hicolor"
            / "scalable"
            / "apps"
            / "nanoleaf-kde-sync.svg",
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

        # Log a warning if generated pixel-fallback icons are used
        if idle_icon.isNull() or running_icon.isNull():
            _log.warning(
                "No SVG/theme icons found; using generated fallback icons. "
                "Install the app properly or place icons in assets/icons/hicolor/scalable/apps/"
            )
        return idle_icon, running_icon

    def _make_menu(self):
        menu = self.QMenu()

        # ── Top-level daily-use actions ──
        self.action_start = self.QAction(
            self.QIcon.fromTheme("media-playback-start"), "Start", menu
        )
        self.action_stop = self.QAction(self.QIcon.fromTheme("media-playback-stop"), "Stop", menu)
        self.action_settings = self.QAction(
            self.QIcon.fromTheme("preferences-system"), "Settings…", menu
        )
        self.action_display_wizard = self.QAction(
            self.QIcon.fromTheme("preferences-desktop-display"), "Calibration / Setup…", menu
        )
        self.action_status = self.QAction(
            self.QIcon.fromTheme("help-about"), "About / Status", menu
        )

        # ── Advanced submenu actions ──
        self.action_advanced_settings = self.QAction("Advanced Settings", menu)
        self.action_troubleshooting_guide = self.QAction("Troubleshooting Guide", menu)
        self.action_live_diagnostics = self.QAction("Live Diagnostics", menu)
        self.action_doctor = self.QAction("Run Doctor", menu)
        self.action_smoke = self.QAction("Run Smoke Test", menu)
        self.action_check_updates = self.QAction("Check for Updates…", menu)
        self.action_reset_probe_cache = self.QAction("Reset Auto-Probe Cache", menu)
        self.action_launch_diagnostics = self.QAction("Show Launch Diagnostics", menu)
        self.action_enable_autostart = self.QAction("Enable Autostart", menu)
        self.action_disable_autostart = self.QAction("Disable Autostart", menu)
        self.action_quit = self.QAction(self.QIcon.fromTheme("application-exit"), "Quit", menu)

        # ── Wire triggers ──
        self.action_start.triggered.connect(self.on_start)
        self.action_stop.triggered.connect(self.on_stop)
        self.action_settings.triggered.connect(self.on_settings)
        self.action_display_wizard.triggered.connect(self.on_display_configurator)
        self.action_advanced_settings.triggered.connect(self.on_open_advanced_settings)
        self.action_troubleshooting_guide.triggered.connect(self.on_open_troubleshooting_guide)
        self.action_live_diagnostics.triggered.connect(self.on_live_diagnostics)
        self.action_status.triggered.connect(self.on_status)
        self.action_enable_autostart.triggered.connect(self.on_enable_autostart)
        self.action_disable_autostart.triggered.connect(self.on_disable_autostart)
        self.action_reset_probe_cache.triggered.connect(self.on_reset_probe_cache)
        self.action_launch_diagnostics.triggered.connect(self.on_show_launch_diagnostics)
        self.action_doctor.triggered.connect(self.on_doctor)
        self.action_smoke.triggered.connect(self.on_smoke_test)
        self.action_check_updates.triggered.connect(self.on_check_for_updates)
        self.action_quit.triggered.connect(self.on_quit)

        # ── Build Advanced submenu ──
        advanced_menu = self.QMenu("Advanced", menu)
        advanced_menu.addAction(self.action_advanced_settings)
        advanced_menu.addAction(self.action_troubleshooting_guide)
        advanced_menu.addAction(self.action_live_diagnostics)
        advanced_menu.addSeparator()
        advanced_menu.addAction(self.action_doctor)
        advanced_menu.addAction(self.action_smoke)
        advanced_menu.addAction(self.action_check_updates)
        advanced_menu.addAction(self.action_reset_probe_cache)
        advanced_menu.addAction(self.action_launch_diagnostics)
        advanced_menu.addSeparator()
        advanced_menu.addAction(self.action_enable_autostart)
        advanced_menu.addAction(self.action_disable_autostart)

        # ── Assemble top-level menu ──
        menu.addAction(self.action_start)
        menu.addAction(self.action_stop)
        menu.addSeparator()
        menu.addAction(self.action_settings)
        menu.addAction(self.action_display_wizard)
        menu.addAction(self.action_status)
        menu.addSeparator()
        menu.addMenu(advanced_menu)
        menu.addSeparator()
        menu.addAction(self.action_quit)
        return menu

    def _refresh_mode_labels(self) -> None:
        running = self.service.is_running()
        status = self.service.get_status()
        startup_state = str(status.get("startup_state") or ("running" if running else "idle"))
        waiting_for_screen = startup_state == "waiting_for_screen_selection"
        start_action_enabled = startup_state in {"idle", "error"}
        set_enabled = getattr(self.action_start, "setEnabled", None)
        if callable(set_enabled):
            set_enabled(start_action_enabled)
        stop_set_enabled = getattr(self.action_stop, "setEnabled", None)
        if callable(stop_set_enabled):
            stop_set_enabled(running)
        # Dynamic autostart: show only the relevant action.
        autostart_enabled = user_autostart_path().exists()
        enable_visible = getattr(self.action_enable_autostart, "setVisible", None)
        disable_visible = getattr(self.action_disable_autostart, "setVisible", None)
        if callable(enable_visible):
            enable_visible(not autostart_enabled)
        if callable(disable_visible):
            disable_visible(autostart_enabled)
        capture_mode, device_mode = describe_mode(
            self.config.use_mock_capture,
            self.config.prefer_backend,
            service_running=running,
            device_discovered=bool(status.get("device_discovered")),
            device_model=str(status.get("device_model") or ""),
        )
        effective_backend = status.get("effective_capture_backend") or (
            "not-started" if not running else "unresolved"
        )
        selected_backend = status.get("selected_capture_backend") or "unresolved"
        unresolved_reason = status.get("backend_unresolved_reason") or ""
        self.tray_icon.setToolTip(
            "nanoleaf-kde-sync\n"
            f"State: {startup_state}\n{capture_mode}\n{device_mode}\n"
            f"Requested backend policy: {self.config.prefer_backend}\n"
            f"Selected backend: {selected_backend}\n"
            f"Effective backend: {effective_backend}"
            + (f"\nBackend note: {unresolved_reason}" if unresolved_reason else "")
        )
        self.action_status.setText(
            f"About / Status ({startup_state.replace('_', ' ').title()} · v{self._app_version})"
        )
        if waiting_for_screen:
            self.action_start.setText("Start (Waiting for screen selection)")
        elif not running and startup_state in {"idle", "error"}:
            readiness_fn = getattr(self, "_quick_setup_readiness", None)
            if callable(readiness_fn):
                report = readiness_fn()
                if report.status == NEEDS_CALIBRATION_STATUS:
                    self.action_start.setText("Start (Needs calibration)")
                elif report.status == CONFIG_PROBLEM_STATUS:
                    self.action_start.setText("Start (Needs setup)")
                else:
                    self.action_start.setText("Start")
            else:
                self.action_start.setText("Start")
        else:
            self.action_start.setText("Start")

    def _safe_service_status(self) -> dict:
        try:
            status = self.service.get_status()
            return status if isinstance(status, dict) else {}
        except Exception as exc:
            _log.warning("Unable to query service status: %s", exc, exc_info=True)
            return {}

    def _safe_refresh_mode_labels(self) -> None:
        try:
            self._refresh_mode_labels()
        except Exception as exc:
            _log.warning("Unable to refresh tray labels: %s", exc, exc_info=True)

    def on_start(self):
        start_status = NanoleafTrayApp._safe_service_status(self)
        startup_state = str(start_status.get("startup_state") or "")
        if startup_state in {"starting", "waiting_for_screen_selection", "running", "stopping"}:
            NanoleafTrayApp._safe_refresh_mode_labels(self)
            schedule_refresh = getattr(self, "_schedule_startup_refresh", None)
            if startup_state in {"starting", "waiting_for_screen_selection"} and callable(
                schedule_refresh
            ):
                schedule_refresh()
            return
        close_preview = getattr(self, "_close_preview_driver", None)
        if callable(close_preview):
            close_preview(resume_service=False)

        readiness_fn = getattr(self, "_quick_setup_readiness", None)
        preflight = readiness_fn() if callable(readiness_fn) else None
        if (
            preflight is not None
            and not preflight.ready
            and bool(getattr(self.config, "wizard_completed", False))
        ):
            issue = preflight.issues[0] if preflight.issues else None
            reason = issue.reason if issue else preflight.status
            fix = issue.fix if issue else "Open Display Setup or Settings"
            message = f"Cannot start mirroring yet.\n{reason}\n{fix}"
            if preflight.status == NEEDS_CALIBRATION_STATUS:
                message = f"{message}\n\nOpening Display Setup…"
                self.tray_icon.showMessage(
                    "nanoleaf-kde-sync",
                    message,
                    self.QSystemTrayIcon.MessageIcon.Warning,
                    8000,
                )
                self.on_display_configurator(was_running_intent=False)
                return
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                message,
                self.QSystemTrayIcon.MessageIcon.Warning,
                8000,
            )
            if preflight.status == CONFIG_PROBLEM_STATUS:
                self.on_settings()
            return

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

        status = NanoleafTrayApp._safe_service_status(self)
        startup_state = str(status.get("startup_state") or "")
        running = bool(running and startup_state == "running")
        self.tray_icon.setIcon(self._running_icon if running else self._idle_icon)
        NanoleafTrayApp._safe_refresh_mode_labels(self)
        if startup_state in {"starting", "running", "waiting_for_screen_selection"}:
            schedule_refresh = getattr(self, "_schedule_startup_refresh", None)
            if startup_state in {"starting", "waiting_for_screen_selection"} and callable(
                schedule_refresh
            ):
                schedule_refresh()
            return
        if not running:
            guidance = (
                status.get("last_error_guidance") or "Run nanoleaf-kde-sync-doctor for diagnostics."
            )
            error_text = self.service.last_error or "unknown error"
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                f"Start failed: {error_text}\n{guidance}",
                self.QSystemTrayIcon.MessageIcon.Warning,
                7000,
            )

    def _request_stop(self, *, timeout_s: float | None = None) -> bool:
        try:
            if timeout_s is None:
                result = self.service.stop()
            else:
                result = self.service.stop(timeout=timeout_s)
            return bool(result) if result is not None else (not self.service.is_running())
        except TypeError:
            self.service.stop()
            return not self.service.is_running()
        except Exception as exc:
            _log.warning("Service stop request failed: %s", exc, exc_info=True)
            return False

    def _set_idle_ui_state(self) -> None:
        self.tray_icon.setIcon(self._idle_icon)
        NanoleafTrayApp._safe_refresh_mode_labels(self)

    def _service_running(self, service=None) -> bool:
        target = service if service is not None else self.service
        try:
            return bool(target.is_running())
        except Exception as exc:
            _log.warning("Unable to query service running state: %s", exc, exc_info=True)
            return False

    def _schedule_stop_warning(self, service) -> None:
        def _warn_if_still_running() -> None:
            try:
                if service.is_running():
                    _log.warning("Service still running after stop timeout")
            except Exception as exc:
                _log.warning("Unable to query service stop status: %s", exc, exc_info=True)

        self.QTimer.singleShot(int(self._shutdown_timeout_s * 1000), _warn_if_still_running)

    def _poll_stop_completion(self) -> None:
        """Poll until the runtime thread finishes shutting down, then re-enable Start."""
        if not self._service_running():
            self._set_idle_ui_state()
            return
        if time.monotonic() >= getattr(self, "_stop_poll_deadline", 0.0):
            _log.warning(
                "Service still running after stop deadline; "
                "keeping Start disabled until next UI refresh"
            )
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                "Mirroring is still stopping or failed to stop within timeout.",
                self.QSystemTrayIcon.MessageIcon.Warning,
                7000,
            )
            return
        self._stop_poll_count = getattr(self, "_stop_poll_count", 0) + 1
        # Back off after repeated polls to avoid busy-waiting.
        interval_s = min(0.5, 0.05 * (1 + self._stop_poll_count // 10))
        self.QTimer.singleShot(int(interval_s * 1000), self._poll_stop_completion)

    def on_stop(self):
        service = self.service
        try:
            stopped = self._request_stop(timeout_s=self._shutdown_timeout_s)
        except Exception as exc:
            _log.warning("Unhandled stop action exception: %s", exc, exc_info=True)
            stopped = False
        still_running = self._service_running(service)
        if stopped and not still_running:
            self._set_idle_ui_state()
            return

        # If the service is still winding down, poll until it stops or we hit
        # an extended deadline; re-enable the Start button once it's idle.
        self._stop_poll_deadline = time.monotonic() + self._shutdown_timeout_s
        self._stop_poll_count = 0
        self._poll_stop_completion()

    def _start_after_launch(self) -> None:
        def worker() -> None:
            try:
                started = self.service.start()
                running = started and self.service.is_running()
            except Exception:
                _log.exception("Unhandled exception during auto-start")
                running = False
            self._auto_start_bridge.result_ready.emit(running)

        threading.Thread(target=worker, name="auto-start-worker", daemon=True).start()

    def _handle_auto_start_result(self, running: bool) -> None:
        status = self.service.get_status()
        startup_state = str(status.get("startup_state") or "")
        effective_running = bool(running and startup_state == "running")
        self.tray_icon.setIcon(self._running_icon if effective_running else self._idle_icon)
        NanoleafTrayApp._safe_refresh_mode_labels(self)
        if startup_state in {"starting", "running", "waiting_for_screen_selection"}:
            schedule_refresh = getattr(self, "_schedule_startup_refresh", None)
            if startup_state in {"starting", "waiting_for_screen_selection"} and callable(
                schedule_refresh
            ):
                schedule_refresh()
            return
        if not effective_running:
            guidance = (
                status.get("last_error_guidance") or "Run nanoleaf-kde-sync-doctor for diagnostics."
            )
            self.tray_icon.showMessage(
                "nanoleaf-kde-sync",
                f"Start failed: {self.service.last_error or 'unknown error'}\n{guidance}",
                self.QSystemTrayIcon.MessageIcon.Warning,
                7000,
            )

    def on_display_configurator(self, *, was_running_intent: bool | None = None) -> None:
        dlg = DisplayConfiguratorDialog(
            parent=None,
            cfg=self.config,
            calibration_sender=self._send_calibration_preview,
            runtime_status=self.service.get_status(),
        )
        was_running = (
            was_running_intent
            if was_running_intent is not None
            else self.service.is_running() or bool(getattr(self, "_preview_paused_service", False))
        )
        accepted = dlg.exec() == self.QDialog.DialogCode.Accepted
        close_preview = getattr(self, "_close_preview_driver", None)
        if callable(close_preview):
            close_preview(resume_service=False)
        if not accepted:
            self.config = dlg.in_progress_config()
            self.cfg_mgr.save(self.config)
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
            mode = (
                "diagnostic"
                if bool(getattr(self.config, "use_mock_capture", False))
                else "full-real"
            )
            message = f"{message}\n\n{first_run_message(mode)}"
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync", message, self.QSystemTrayIcon.MessageIcon.Information, 6000
        )

    def on_settings(self, *, initial_section: str | None = None):
        def _apply_settings_dialog_config(new_cfg) -> None:
            self.cfg_mgr.save(new_cfg)
            self.config = new_cfg
            if was_running and self.service.is_running():
                self.on_stop()
            self.service = NanoleafSyncService(config=self.config)
            self._refresh_mode_labels()
            if was_running:
                self.on_start()

        dlg = SettingsDialog(
            parent=None,
            cfg=self.config,
            calibration_sender=self._send_calibration_preview,
            diagnostic_capture=getattr(self.service, "capture_one_diagnostic_frame", None),
            runtime_status=self.service.get_status(),
            initial_section=initial_section,
            on_apply=_apply_settings_dialog_config,
            dialog_geometry=getattr(self, "_saved_settings_geometry", None),
        )
        was_running = self.service.is_running() or bool(
            getattr(self, "_preview_paused_service", False)
        )
        accepted = dlg.exec() == self.QDialog.DialogCode.Accepted
        close_preview = getattr(self, "_close_preview_driver", None)
        if callable(close_preview):
            close_preview(resume_service=False)
        if not accepted:
            if was_running:
                self.on_start()
            return

        save_geom = getattr(dlg, "saved_geometry", None)
        if callable(save_geom):
            self._saved_settings_geometry = save_geom()
        if dlg.wants_display_configurator():
            self.config = dlg.updated_config()
            self.cfg_mgr.save(self.config)
            self.on_display_configurator(was_running_intent=was_running)
            return
        _apply_settings_dialog_config(dlg.updated_config())

    def on_open_troubleshooting_guide(self) -> None:
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
                _log.warning(
                    "Unable to open troubleshooting guide with xdg-open: %s", exc, exc_info=True
                )

        self.QMessageBox.information(
            None,
            "nanoleaf-kde-sync troubleshooting",
            (
                "Run diagnostics from Troubleshooting / Advanced:\n"
                "• Advanced / Troubleshooting\n"
                "• Run Doctor\n"
                "• Run Smoke Test\n\n"
                "If those checks fail, open docs/TROUBLESHOOTING.md in the project source."
            ),
        )

    def on_live_diagnostics(self) -> None:
        dlg = LiveDiagnosticsDialog(
            parent=None,
            refresh_fn=self.service.get_status,
        )
        dlg.exec()

    def on_status(self):
        status = self.service.get_status()
        running = bool(status.get("running"))
        connected = bool(status.get("device_discovered"))
        connection_text = (
            "Connected"
            if connected
            else ("Searching / not connected" if running else "Not started")
        )
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

    def on_open_advanced_settings(self) -> None:
        self.on_settings(initial_section="Diagnostics")
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync",
            "Opened Advanced Settings.",
            self.QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    def on_doctor(self):
        self._run_command_async(
            label="doctor", argv=[sys.executable, "-m", "nanoleaf_sync.tools.doctor"]
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
                "nanoleaf-kde-sync", text, self.QSystemTrayIcon.MessageIcon.Information, 6000
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
            label="smoke test", argv=[sys.executable, "-m", "nanoleaf_sync.tools.smoke_test"]
        )

    def _schedule_startup_update_check(self) -> None:
        def worker() -> None:
            try:
                result = check_for_updates(force=False)
            except Exception as exc:
                _log.warning("Startup update check failed: %s", exc, exc_info=True)
                return
            self.QTimer.singleShot(0, lambda: self._handle_startup_update_check(result))

        threading.Thread(target=worker, name="update-check-startup", daemon=True).start()

    def _handle_startup_update_check(self, result) -> None:
        self._safe_refresh_mode_labels()
        if not should_notify_for_update(result):
            return
        notice = update_notification_message(result)
        if not notice or result.latest_version is None:
            return
        mark_update_notified(result.latest_version)
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync",
            notice,
            self.QSystemTrayIcon.MessageIcon.Information,
            10000,
        )

    def on_check_for_updates(self) -> None:
        self.action_check_updates.setEnabled(False)
        self.tray_icon.showMessage(
            "nanoleaf-kde-sync",
            "Checking for updates…",
            self.QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

        def worker() -> None:
            try:
                result = check_for_updates(force=True)
            except Exception as exc:
                self.QTimer.singleShot(
                    0,
                    lambda exc=exc: self._handle_manual_update_check_error(exc),
                )
                return
            self.QTimer.singleShot(0, lambda: self._handle_manual_update_check(result))

        threading.Thread(target=worker, name="update-check-manual", daemon=True).start()

    def _handle_manual_update_check(self, result) -> None:
        self.action_check_updates.setEnabled(True)
        self.QMessageBox.information(
            None,
            "nanoleaf-kde-sync updates",
            manual_check_message(result),
        )

    def _handle_manual_update_check_error(self, error: Exception) -> None:
        self.action_check_updates.setEnabled(True)
        self.QMessageBox.warning(
            None,
            "nanoleaf-kde-sync updates",
            f"Could not check for updates: {error}",
        )

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
                result = subprocess.run(
                    argv, capture_output=True, text=True, check=False, timeout=30
                )
                preview, rc = summarize_command_output(
                    result.stdout, result.stderr, result.returncode
                )
                self.QTimer.singleShot(
                    0, lambda: self._handle_tool_result(label=label, preview=preview, rc=rc)
                )
            except subprocess.TimeoutExpired:
                self.QTimer.singleShot(
                    0,
                    lambda: self._handle_tool_error(
                        label=label,
                        error=RuntimeError(f"{label} timed out after 30s"),
                    ),
                )
            except Exception as exc:
                self.QTimer.singleShot(
                    0, lambda exc=exc: self._handle_tool_error(label=label, error=exc)
                )

        threading.Thread(target=worker, name="tool-runner", daemon=True).start()

    def _handle_tool_result(self, label: str, preview: str, rc: int) -> None:
        self.action_doctor.setEnabled(True)
        self.action_smoke.setEnabled(True)
        is_ok = rc == 0
        self.tray_icon.showMessage(
            f"nanoleaf-kde-sync {label}",
            f"{'Completed successfully' if is_ok else f'Finished with exit code {rc}'}.\n{preview}",
            self.QSystemTrayIcon.MessageIcon.Information
            if is_ok
            else self.QSystemTrayIcon.MessageIcon.Warning,
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
        self.QTimer.singleShot(
            int(self._shutdown_poll_interval_s * 1000), self._poll_shutdown_completion
        )

    def _finalize_quit(self) -> None:
        if self._quit_finalized:
            return
        self._quit_finalized = True
        self._shutdown_in_progress = False
        hide_tray_icon = getattr(self.tray_icon, "hide", None)
        if callable(hide_tray_icon):
            hide_tray_icon()
        self.app.quit()

    def on_quit(self):
        if self._quit_finalized:
            return
        if self._shutdown_in_progress:
            return

        self._shutdown_in_progress = True
        self._shutdown_deadline = time.monotonic() + self._shutdown_timeout_s
        self._close_preview_driver(resume_service=False)
        try:
            self._request_stop(timeout_s=0.0)
        except TypeError:
            self._request_stop()
        self._set_idle_ui_state()
        self.QTimer.singleShot(0, self._poll_shutdown_completion)

    def run(self):
        if bool(getattr(self.config, "wizard_completed", False)) is False:
            # Skip wizard if config passes readiness check (already configured manually)
            from nanoleaf_sync.runtime.readiness_check import (
                READY_STATUS,
                run_readiness_check,
            )

            try:
                report = run_readiness_check(
                    config=self.config,
                    runtime_status=self.service.get_status(),
                    source_zone_count=None,
                    capture_probe=lambda _cfg: None,
                    device_probe=lambda _cfg: None,
                )
                if report.status == READY_STATUS:
                    _log.info("Config passes readiness check; skipping first-run wizard")
                else:
                    self.on_display_configurator()
            except Exception:
                _log.warning(
                    "Readiness check failed during startup; falling back to wizard",
                    exc_info=True,
                )
                self.on_display_configurator()
        return self.app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="nanoleaf-kde-sync tray entry point")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="run non-interactive startup/import checks and exit",
    )
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
