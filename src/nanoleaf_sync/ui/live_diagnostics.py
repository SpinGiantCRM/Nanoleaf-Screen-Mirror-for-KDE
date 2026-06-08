from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_log = logging.getLogger(__name__)

REFRESH_INTERVAL_MS = 500


class LiveDiagnosticsDialog(QDialog):
    """Live diagnostics window that auto-refreshes from the runtime status dict."""

    def __init__(
        self,
        parent: QWidget | None,
        refresh_fn: Callable[[], dict],
        *,
        live_only: bool = False,
    ):
        super().__init__(parent)
        self._refresh_fn = refresh_fn
        self._live_only = live_only

        self.setWindowTitle("Live Diagnostics — nanoleaf-kde-sync")
        self.resize(520, 520)
        self.setMinimumSize(360, 300)

        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)

        # Capture section
        self._cap_group = QGroupBox("Capture")
        self._cap_grid = QGridLayout()
        self._cap_group.setLayout(self._cap_grid)
        cap_fields = [
            ("Backend", "_cap_backend"),
            ("Method", "_cap_method"),
            ("Frame size", "_cap_frame_size"),
            ("Mean brightness", "_cap_brightness"),
            ("Black frames (consecutive)", "_cap_black_conc"),
            ("Black frames (total)", "_cap_black_total"),
        ]
        self._cap_labels = {}
        for row, (label, key) in enumerate(cap_fields):
            self._cap_grid.addWidget(QLabel(label + ":"), row, 0)
            val = QLabel("\u2014")
            self._cap_grid.addWidget(val, row, 1)
            self._cap_labels[key] = val
        self._content_layout.addWidget(self._cap_group)

        # Pipeline section
        self._pipe_group = QGroupBox("Pipeline")
        self._pipe_grid = QGridLayout()
        self._pipe_group.setLayout(self._pipe_grid)
        pipe_fields = [
            ("Frames sent", "_pipe_frames_sent"),
            ("Consecutive errors", "_pipe_errors"),
            ("Target FPS", "_pipe_target_fps"),
            ("Effective output FPS", "_pipe_eff_fps"),
            ("Lifecycle state", "_pipe_lifecycle"),
            ("Priority mode", "_pipe_priority"),
        ]
        self._pipe_labels = {}
        for row, (label, key) in enumerate(pipe_fields):
            self._pipe_grid.addWidget(QLabel(label + ":"), row, 0)
            val = QLabel("\u2014")
            self._pipe_grid.addWidget(val, row, 1)
            self._pipe_labels[key] = val
        self._content_layout.addWidget(self._pipe_group)

        # Device section
        self._dev_group = QGroupBox("Device")
        self._dev_grid = QGridLayout()
        self._dev_group.setLayout(self._dev_grid)
        dev_fields = [
            ("Driver ready", "_dev_driver"),
            ("Capture backend ready", "_dev_cap_ready"),
            ("Calibration status", "_dev_cal"),
            ("Calibration message", "_dev_cal_msg"),
        ]
        self._dev_labels = {}
        for row, (label, key) in enumerate(dev_fields):
            self._dev_grid.addWidget(QLabel(label + ":"), row, 0)
            val = QLabel("\u2014")
            self._dev_grid.addWidget(val, row, 1)
            self._dev_labels[key] = val
        self._content_layout.addWidget(self._dev_group)

        # Errors section
        self._err_group = QGroupBox("Errors")
        self._err_grid = QGridLayout()
        self._err_group.setLayout(self._err_grid)
        err_fields = [
            ("Last error", "_err_last"),
            ("Error kind", "_err_kind"),
            ("Guidance", "_err_guide"),
            ("Startup elapsed (ms)", "_err_startup_ms"),
        ]
        self._err_labels = {}
        for row, (label, key) in enumerate(err_fields):
            self._err_grid.addWidget(QLabel(label + ":"), row, 0)
            val = QLabel("\u2014")
            self._err_grid.addWidget(val, row, 1)
            self._err_labels[key] = val
        self._content_layout.addWidget(self._err_group)

        # Per-zone colors (collapsible)
        self._zone_group = QGroupBox("Per-Zone Colors")
        self._zone_layout = QVBoxLayout()
        self._zone_group.setLayout(self._zone_layout)
        self._zone_grid = None
        self._content_layout.addWidget(self._zone_group)

        self._content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll)

        # Close / refresh controls
        btn_row = QHBoxLayout()
        self._refresh_now_btn = QPushButton("Refresh Now")
        self._refresh_now_btn.clicked.connect(self._do_refresh)
        btn_row.addWidget(self._refresh_now_btn)
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._do_refresh)
        self._do_refresh()
        if self._is_running():
            self._timer.start(REFRESH_INTERVAL_MS)

    def _is_running(self) -> bool:
        if self._live_only:
            try:
                return bool(self._refresh_fn().get("running", False))
            except Exception:
                _log.debug("Unable to query live diagnostics running state", exc_info=True)
                return False
        return True

    def _do_refresh(self) -> None:
        try:
            s = self._refresh_fn()
        except Exception:
            _log.debug("Live diagnostics refresh failed", exc_info=True)
            return

        running = bool(s.get("running", False))

        # Capture
        self._cap_labels["_cap_backend"].setText(str(s.get("capture_backend") or "\u2014"))
        self._cap_labels["_cap_method"].setText(str(s.get("capture_path") or "\u2014"))
        w = s.get("captured_frame_width", 0) or 0
        h = s.get("captured_frame_height", 0) or 0
        self._cap_labels["_cap_frame_size"].setText(f"{w}\u00d7{h}" if w and h else "\u2014")
        b = s.get("latest_frame_mean_brightness", 0.0) or 0.0
        self._cap_labels["_cap_brightness"].setText(f"{b:.1f}")
        self._cap_labels["_cap_black_conc"].setText(str(s.get("consecutive_black_frames", 0)))
        self._cap_labels["_cap_black_total"].setText(str(s.get("total_black_frames", 0)))

        # Pipeline
        self._pipe_labels["_pipe_frames_sent"].setText(str(s.get("frames_sent", 0)))
        self._pipe_labels["_pipe_errors"].setText(str(s.get("consecutive_errors", 0)))
        lm = s.get("latency_measurement")
        if lm:
            tgt = lm.get("target_fps", 0)
            eff = lm.get("effective_output_fps", 0)
        else:
            tgt = 0
            eff = 0
        self._pipe_labels["_pipe_target_fps"].setText(f"{tgt:.0f}" if tgt else "\u2014")
        self._pipe_labels["_pipe_eff_fps"].setText(f"{eff:.1f}" if eff else "\u2014")
        self._pipe_labels["_pipe_lifecycle"].setText(str(s.get("lifecycle_state") or "\u2014"))
        self._pipe_labels["_pipe_priority"].setText(
            str(s.get("configured_priority_mode") or "\u2014")
        )

        # Device
        self._dev_labels["_dev_driver"].setText("yes" if s.get("driver_ready") else "no")
        self._dev_labels["_dev_cap_ready"].setText(
            "yes" if s.get("capture_backend_ready") else "no"
        )
        self._dev_labels["_dev_cal"].setText(str(s.get("calibration_status") or "\u2014"))
        self._dev_labels["_dev_cal_msg"].setText(
            str(s.get("calibration_status_message") or "\u2014")
        )

        # Errors
        self._err_labels["_err_last"].setText(str(s.get("last_error") or "none"))
        self._err_labels["_err_kind"].setText(str(s.get("last_error_kind") or "\u2014"))
        self._err_labels["_err_guide"].setText(str(s.get("last_error_guidance") or "\u2014"))
        self._err_labels["_err_startup_ms"].setText(
            str(s.get("startup_elapsed_ms", 0)) if running else "\u2014"
        )

        # Zone colors
        zone_diag = s.get("zone_diagnostics", [])
        if zone_diag and self._zone_grid is None:
            self._zone_grid = QGridLayout()
            self._zone_layout.insertLayout(0, self._zone_grid)
        if self._zone_grid is not None and zone_diag:
            # Clear existing grid contents (takeAt removes from layout; deleteLater frees widgets)
            while self._zone_grid.count():
                item = self._zone_grid.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            # Rebuild headers + zone rows
            for col_i, hdr in enumerate(["Zone", "Side", "RGB"]):
                self._zone_grid.addWidget(QLabel(hdr), 0, col_i)
            for zi, z in enumerate(zone_diag):
                row = zi + 1
                self._zone_grid.addWidget(QLabel(str(z.get("zone_index", zi))), row, 0)
                self._zone_grid.addWidget(QLabel(str(z.get("side", "?"))), row, 1)
                self._zone_grid.addWidget(QLabel(str(z.get("rgb", "?"))), row, 2)

        # Manage timer: stop if mirroring stopped (live_only mode)
        if self._live_only and not running and self._timer.isActive():
            self._timer.stop()
