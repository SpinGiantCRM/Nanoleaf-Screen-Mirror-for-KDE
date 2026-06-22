from __future__ import annotations

import logging
from collections.abc import Callable

from nanoleaf_sync.ui.layout_helpers import mark_compact
from nanoleaf_sync.ui.qt_lazy import load_qt

_log = logging.getLogger(__name__)

REFRESH_INTERVAL_MS = 500

_qt = load_qt()
QCheckBox = _qt["QCheckBox"]
QDialog = _qt["QDialog"]
QGridLayout = _qt["QGridLayout"]
QGroupBox = _qt["QGroupBox"]
QHBoxLayout = _qt["QHBoxLayout"]
QLabel = _qt["QLabel"]
QPushButton = _qt["QPushButton"]
QScrollArea = _qt["QScrollArea"]
QTimer = _qt["QTimer"]
QVBoxLayout = _qt["QVBoxLayout"]
QWidget = _qt["QWidget"]


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
        self._last_refresh_ok = True

        self.setWindowTitle("Live Diagnostics — nanoleaf-kde-sync")
        self.resize(520, 520)
        self.setMinimumSize(360, 300)

        root = QVBoxLayout(self)
        self._stale_banner = QLabel("")
        set_prop = getattr(self._stale_banner, "setProperty", None)
        if callable(set_prop):
            set_prop("muted", True)
        self._stale_banner.setVisible(False)
        root.addWidget(self._stale_banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)

        self._cap_group = QGroupBox("Capture")
        self._cap_grid = QGridLayout()
        self._cap_group.setLayout(self._cap_grid)
        cap_fields = [
            ("Backend", "_cap_backend"),
            ("Method", "_cap_method"),
            ("Frame seq", "_cap_frame_seq"),
            ("Source monitor", "_cap_source_monitor"),
            ("Frame size", "_cap_frame_size"),
            ("Mean brightness", "_cap_brightness"),
            ("Black frames (consecutive)", "_cap_black_conc"),
            ("Black frames (total)", "_cap_black_total"),
        ]
        self._cap_labels: dict[str, QLabel] = {}
        for row, (label, key) in enumerate(cap_fields):
            self._cap_grid.addWidget(QLabel(label + ":"), row, 0)
            val = QLabel("\u2014")
            self._cap_grid.addWidget(val, row, 1)
            self._cap_labels[key] = val
        self._content_layout.addWidget(self._cap_group)

        self._pipe_group = QGroupBox("Pipeline")
        self._pipe_grid = QGridLayout()
        self._pipe_group.setLayout(self._pipe_grid)
        pipe_fields = [
            ("Frames sent", "_pipe_frames_sent"),
            ("Consecutive errors", "_pipe_errors"),
            ("Target FPS", "_pipe_target_fps"),
            ("Effective output FPS", "_pipe_eff_fps"),
            ("Capture buffer drops", "_pipe_cap_drops"),
            ("Process buffer drops", "_pipe_proc_drops"),
            ("Coalesced sends", "_pipe_coalesced"),
            ("Frame staleness (ms)", "_pipe_staleness"),
            ("SDR boost undo", "_pipe_sdr_boost"),
            ("Lifecycle state", "_pipe_lifecycle"),
            ("Priority mode", "_pipe_priority"),
            ("Priority apply status", "_pipe_priority_status"),
            ("Priority apply error", "_pipe_priority_error"),
        ]
        self._pipe_labels: dict[str, QLabel] = {}
        for row, (label, key) in enumerate(pipe_fields):
            self._pipe_grid.addWidget(QLabel(label + ":"), row, 0)
            val = QLabel("\u2014")
            self._pipe_grid.addWidget(val, row, 1)
            self._pipe_labels[key] = val
        self._content_layout.addWidget(self._pipe_group)

        self._advanced_group = QGroupBox("Advanced counters")
        self._advanced_grid = QGridLayout()
        self._advanced_group.setLayout(self._advanced_grid)
        advanced_fields = [
            ("Predictive sync active", "_adv_pred_active"),
            ("Predictive lookahead (frames)", "_adv_pred_lookahead"),
            ("Scene cut suppressed", "_adv_pred_scene"),
            ("Capture buffer drops", "_adv_cap_drops"),
            ("Process buffer drops", "_adv_proc_drops"),
            ("Coalesced sends", "_adv_coalesced"),
        ]
        self._advanced_labels: dict[str, QLabel] = {}
        for row, (label, key) in enumerate(advanced_fields):
            self._advanced_grid.addWidget(QLabel(label + ":"), row, 0)
            val = QLabel("\u2014")
            self._advanced_grid.addWidget(val, row, 1)
            self._advanced_labels[key] = val
        self._advanced_group.setVisible(False)
        self._content_layout.addWidget(self._advanced_group)

        self._dev_group = QGroupBox("Device")
        self._dev_grid = QGridLayout()
        self._dev_group.setLayout(self._dev_grid)
        dev_fields = [
            ("Driver ready", "_dev_driver"),
            ("Capture backend ready", "_dev_cap_ready"),
            ("Calibration status", "_dev_cal"),
            ("Calibration message", "_dev_cal_msg"),
        ]
        self._dev_labels: dict[str, QLabel] = {}
        for row, (label, key) in enumerate(dev_fields):
            self._dev_grid.addWidget(QLabel(label + ":"), row, 0)
            val = QLabel("\u2014")
            self._dev_grid.addWidget(val, row, 1)
            self._dev_labels[key] = val
        self._content_layout.addWidget(self._dev_group)

        self._err_group = QGroupBox("Errors")
        self._err_grid = QGridLayout()
        self._err_group.setLayout(self._err_grid)
        err_fields = [
            ("Last error", "_err_last"),
            ("Error kind", "_err_kind"),
            ("Guidance", "_err_guide"),
            ("Startup elapsed (ms)", "_err_startup_ms"),
        ]
        self._err_labels: dict[str, QLabel] = {}
        for row, (label, key) in enumerate(err_fields):
            self._err_grid.addWidget(QLabel(label + ":"), row, 0)
            val = QLabel("\u2014")
            self._err_grid.addWidget(val, row, 1)
            self._err_labels[key] = val
        self._content_layout.addWidget(self._err_group)

        self._zone_group = QGroupBox("Per-Zone Colors")
        self._zone_layout = QVBoxLayout()
        self._zone_group.setLayout(self._zone_layout)
        self._zone_grid: QGridLayout | None = None
        self._content_layout.addWidget(self._zone_group)

        self._content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll)

        btn_row = QHBoxLayout()
        self._show_advanced_checkbox = QCheckBox("Show advanced counters")
        self._show_advanced_checkbox.toggled.connect(self._advanced_group.setVisible)
        btn_row.addWidget(self._show_advanced_checkbox)
        self._refresh_now_btn = QPushButton("Refresh Now")
        mark_compact(self._refresh_now_btn)
        self._refresh_now_btn.clicked.connect(self._do_refresh)
        btn_row.addWidget(self._refresh_now_btn)
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        mark_compact(close_btn)
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
            self._last_refresh_ok = True
            self._stale_banner.setVisible(False)
        except Exception:
            _log.debug("Live diagnostics refresh failed", exc_info=True)
            self._last_refresh_ok = False
            self._stale_banner.setText("Refresh failed — showing stale data.")
            self._stale_banner.setVisible(True)
            return

        running = bool(s.get("running", False))

        self._cap_labels["_cap_backend"].setText(str(s.get("capture_backend") or "\u2014"))
        self._cap_labels["_cap_method"].setText(str(s.get("capture_path") or "\u2014"))
        frame_ctx = s.get("latest_frame_context")
        if isinstance(frame_ctx, dict):
            self._cap_labels["_cap_frame_seq"].setText(str(frame_ctx.get("frame_seq") or "\u2014"))
            source = frame_ctx.get("source") if isinstance(frame_ctx.get("source"), dict) else {}
            monitor = source.get("monitor_id") or source.get("backend_source_id")
            self._cap_labels["_cap_source_monitor"].setText(str(monitor or "\u2014"))
        else:
            self._cap_labels["_cap_frame_seq"].setText("\u2014")
            self._cap_labels["_cap_source_monitor"].setText("\u2014")
        w = s.get("captured_frame_width", 0) or 0
        h = s.get("captured_frame_height", 0) or 0
        self._cap_labels["_cap_frame_size"].setText(f"{w}\u00d7{h}" if w and h else "\u2014")
        b = s.get("latest_frame_mean_brightness", 0.0) or 0.0
        self._cap_labels["_cap_brightness"].setText(f"{b:.1f}")
        self._cap_labels["_cap_black_conc"].setText(str(s.get("consecutive_black_frames", 0)))
        self._cap_labels["_cap_black_total"].setText(str(s.get("total_black_frames", 0)))

        self._pipe_labels["_pipe_frames_sent"].setText(str(s.get("frames_sent", 0)))
        self._pipe_labels["_pipe_errors"].setText(str(s.get("consecutive_errors", 0)))
        lm = s.get("latency_measurement")
        if isinstance(lm, dict):
            tgt = float(lm.get("target_fps", 0) or 0)
            eff = float(lm.get("effective_output_fps", 0) or 0)
            counters = lm.get("counters") if isinstance(lm.get("counters"), dict) else {}
        else:
            tgt = 0.0
            eff = 0.0
            counters = {}
        self._pipe_labels["_pipe_target_fps"].setText(f"{tgt:.0f}" if tgt else "\u2014")
        self._pipe_labels["_pipe_eff_fps"].setText(f"{eff:.1f}" if eff else "\u2014")
        cap_drops = int(counters.get("capture_buffer_dropped_frames", 0) or 0)
        proc_drops = int(counters.get("process_buffer_dropped_frames", 0) or 0)
        coalesced = int(counters.get("coalesced_sends", 0) or 0)
        self._pipe_labels["_pipe_cap_drops"].setText(str(cap_drops))
        self._pipe_labels["_pipe_proc_drops"].setText(str(proc_drops))
        self._pipe_labels["_pipe_coalesced"].setText(str(coalesced))
        staleness = float(s.get("latest_staleness_ms", 0.0) or 0.0)
        self._pipe_labels["_pipe_staleness"].setText(f"{staleness:.1f}")
        sdr_boost = "on" if bool(s.get("sdr_boost_compensation_enabled", False)) else "off"
        self._pipe_labels["_pipe_sdr_boost"].setText(sdr_boost)
        self._pipe_labels["_pipe_lifecycle"].setText(str(s.get("lifecycle_state") or "\u2014"))
        self._pipe_labels["_pipe_priority"].setText(
            str(s.get("configured_priority_mode") or "\u2014")
        )
        self._pipe_labels["_pipe_priority_status"].setText(
            str(s.get("priority_apply_status") or "\u2014")
        )
        priority_error = str(s.get("priority_apply_error") or "").strip()
        self._pipe_labels["_pipe_priority_error"].setText(priority_error or "\u2014")

        pred_active = bool(s.get("predictive_sync_active", False))
        self._advanced_labels["_adv_pred_active"].setText("yes" if pred_active else "no")
        self._advanced_labels["_adv_pred_lookahead"].setText(
            f"{float(s.get('predictive_lookahead_frames', 0.0) or 0.0):.2f}"
        )
        self._advanced_labels["_adv_pred_scene"].setText(
            "yes" if bool(s.get("predictive_scene_cut_suppressed", False)) else "no"
        )
        self._advanced_labels["_adv_cap_drops"].setText(
            str(int(counters.get("capture_buffer_dropped_frames", 0) or 0))
        )
        self._advanced_labels["_adv_proc_drops"].setText(
            str(int(counters.get("process_buffer_dropped_frames", 0) or 0))
        )
        self._advanced_labels["_adv_coalesced"].setText(
            str(int(counters.get("coalesced_sends", 0) or 0))
        )

        self._dev_labels["_dev_driver"].setText("yes" if s.get("driver_ready") else "no")
        self._dev_labels["_dev_cap_ready"].setText(
            "yes" if s.get("capture_backend_ready") else "no"
        )
        self._dev_labels["_dev_cal"].setText(str(s.get("calibration_status") or "\u2014"))
        self._dev_labels["_dev_cal_msg"].setText(
            str(s.get("calibration_status_message") or "\u2014")
        )

        self._err_labels["_err_last"].setText(str(s.get("last_error") or "none"))
        self._err_labels["_err_kind"].setText(str(s.get("last_error_kind") or "\u2014"))
        self._err_labels["_err_guide"].setText(str(s.get("last_error_guidance") or "\u2014"))
        self._err_labels["_err_startup_ms"].setText(
            str(s.get("startup_elapsed_ms", 0)) if running else "\u2014"
        )

        zone_diag = s.get("zone_diagnostics", [])
        if zone_diag and self._zone_grid is None:
            self._zone_grid = QGridLayout()
            self._zone_layout.insertLayout(0, self._zone_grid)
        if self._zone_grid is not None and zone_diag:
            while self._zone_grid.count():
                item = self._zone_grid.takeAt(0)
                if item and item.widget():
                    item.widget().deleteLater()
            for col_i, hdr in enumerate(["Zone", "Side", "RGB"]):
                self._zone_grid.addWidget(QLabel(hdr), 0, col_i)
            for zi, z in enumerate(zone_diag):
                row = zi + 1
                self._zone_grid.addWidget(QLabel(str(z.get("zone_index", zi))), row, 0)
                self._zone_grid.addWidget(QLabel(str(z.get("side", "?"))), row, 1)
                rgb = z.get("final_output_rgb") or z.get("sampled_rgb") or z.get("rgb")
                self._zone_grid.addWidget(QLabel(str(rgb or "?")), row, 2)

        if self._live_only and not running and self._timer.isActive():
            self._timer.stop()
