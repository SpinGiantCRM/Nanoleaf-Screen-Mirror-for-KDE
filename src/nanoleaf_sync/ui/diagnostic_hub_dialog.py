from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import QFileDialog, QSpinBox, QTabWidget

from nanoleaf_sync.tools.flicker_lab import flicker_scenarios
from nanoleaf_sync.ui.layout_helpers import mark_compact, mark_heading, mark_muted, mark_primary
from nanoleaf_sync.ui.qt_lazy import load_qt

_log = logging.getLogger(__name__)

REFRESH_INTERVAL_MS = 1000

_qt = load_qt()
QDialog = _qt["QDialog"]
QGridLayout = _qt["QGridLayout"]
QGroupBox = _qt["QGroupBox"]
QHBoxLayout = _qt["QHBoxLayout"]
QLabel = _qt["QLabel"]
QMessageBox = _qt["QMessageBox"]
QPlainTextEdit = _qt["QPlainTextEdit"]
QPushButton = _qt["QPushButton"]
QScrollArea = _qt["QScrollArea"]
QTimer = _qt["QTimer"]
QVBoxLayout = _qt["QVBoxLayout"]
QWidget = _qt["QWidget"]
QComboBox = _qt["QComboBox"]


def _welcome_label(parent: QWidget, text: str) -> QLabel:
    label = QLabel(text, parent)
    mark_muted(label)
    label.setWordWrap(True)
    return label


def _info_grid(
    parent: QWidget,
    fields: tuple[tuple[str, str], ...],
) -> tuple[QGridLayout, dict[str, QLabel]]:
    grid = QGridLayout()
    labels: dict[str, QLabel] = {}
    for row, (title, key) in enumerate(fields):
        title_label = QLabel(f"{title}:")
        grid.addWidget(title_label, row, 0)
        value = QLabel("—")
        value.setWordWrap(True)
        grid.addWidget(value, row, 1)
        labels[key] = value
    return grid, labels


class DiagnosticHubDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        status_fn: Callable[[], dict[str, Any]],
        forget_portal_token_fn: Callable[[], dict[str, object]],
        colour_probe_fn: Callable[..., dict[str, object]],
        flicker_lab_fn: Callable[..., dict[str, object]],
        portal_pick_fn: Callable[[], dict[str, object]],
        export_bundle_fn: Callable[[str], dict[str, object]],
        open_live_diagnostics_fn: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._status_fn = status_fn
        self._forget_portal_token_fn = forget_portal_token_fn
        self._colour_probe_fn = colour_probe_fn
        self._flicker_lab_fn = flicker_lab_fn
        self._portal_pick_fn = portal_pick_fn
        self._export_bundle_fn = export_bundle_fn
        self._open_live_diagnostics_fn = open_live_diagnostics_fn

        self.setWindowTitle("Help & Diagnostics — nanoleaf-kde-sync")
        self.resize(640, 560)
        self.setMinimumSize(480, 420)

        root = QVBoxLayout(self)
        title = QLabel("Welcome to Help & Diagnostics")
        mark_heading(title)
        root.addWidget(title)
        root.addWidget(
            _welcome_label(
                self,
                "Everything here is optional. Use these tools when colours look off, "
                "the wrong screen is captured, or you want a snapshot to share for support.",
            )
        )

        self._warnings_banner = QLabel("")
        self._warnings_banner.setWordWrap(True)
        set_prop = getattr(self._warnings_banner, "setProperty", None)
        if callable(set_prop):
            set_prop("warning", True)
        self._warnings_banner.setVisible(False)
        root.addWidget(self._warnings_banner)

        tabs = QTabWidget()
        tabs.addTab(self._build_overview_tab(), "Overview")
        tabs.addTab(self._build_source_tab(), "Screen source")
        tabs.addTab(self._build_portal_tab(), "Portal screen")
        tabs.addTab(self._build_usb_tab(), "USB strip")
        tabs.addTab(self._build_colour_tab(), "Colour & flicker")
        root.addWidget(tabs, 1)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        mark_compact(refresh_btn)
        refresh_btn.clicked.connect(self._refresh_all)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        mark_compact(close_btn)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_all)
        self._timer.start(REFRESH_INTERVAL_MS)
        self._refresh_all()

    def _build_overview_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(
            _welcome_label(
                page,
                "A quick health check of mirroring, capture, and your strip.",
            )
        )

        overview_group = QGroupBox("At a glance")
        overview_grid, self._overview_labels = _info_grid(
            page,
            (
                ("Mirroring", "running"),
                ("Capture backend", "backend"),
                ("USB strip", "device"),
                ("Calibration", "calibration"),
                ("Warnings", "warning_count"),
            ),
        )
        overview_group.setLayout(overview_grid)
        layout.addWidget(overview_group)

        actions = QGroupBox("Quick actions")
        actions_layout = QVBoxLayout(actions)
        live_btn = QPushButton("Open live diagnostics")
        mark_primary(live_btn)
        live_btn.clicked.connect(self._open_live_diagnostics)
        actions_layout.addWidget(live_btn)

        bundle_btn = QPushButton("Export support bundle…")
        mark_compact(bundle_btn)
        bundle_btn.clicked.connect(self._export_bundle)
        actions_layout.addWidget(bundle_btn)

        self._overview_status = QPlainTextEdit()
        self._overview_status.setReadOnly(True)
        self._overview_status.setMaximumHeight(120)
        actions_layout.addWidget(self._overview_status)
        layout.addWidget(actions)
        layout.addStretch(1)
        return page

    def _build_source_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(
            _welcome_label(
                page,
                "Confirms which screen feed is active and whether its size or identity changed.",
            )
        )
        group = QGroupBox("Source integrity")
        grid, self._source_labels = _info_grid(
            page,
            (
                ("Fingerprint", "fingerprint"),
                ("Confidence", "confidence"),
                ("Scale confidence", "scale_confidence"),
                ("PipeWire serial", "pipewire_serial"),
                ("Source changes", "change_count"),
                ("Monitor", "monitor"),
                ("Frame size", "frame_size"),
            ),
        )
        group.setLayout(grid)
        layout.addWidget(group)
        layout.addStretch(1)
        return page

    def _build_portal_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(
            _welcome_label(
                page,
                "If you use the portal capture path, this remembers your last screen choice. "
                "Clear it when the wrong monitor keeps coming back.",
            )
        )
        group = QGroupBox("Portal restore manager")
        grid, self._portal_labels = _info_grid(
            page,
            (
                ("Runtime token state", "runtime_state"),
                ("Saved token on disk", "disk_token"),
                ("Token file", "token_path"),
            ),
        )
        group.setLayout(grid)
        layout.addWidget(group)

        forget_btn = QPushButton("Forget saved screen choice")
        mark_primary(forget_btn)
        forget_btn.clicked.connect(self._forget_portal_token)
        layout.addWidget(forget_btn)
        self._portal_message = QPlainTextEdit()
        self._portal_message.setReadOnly(True)
        self._portal_message.setMaximumHeight(100)
        layout.addWidget(self._portal_message)
        layout.addStretch(1)
        return page

    def _build_usb_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(
            _welcome_label(
                page,
                "One-click USB transport profile while mirroring is active "
                "and the strip is connected.",
            )
        )
        group = QGroupBox("USB transport profiler")
        grid, self._usb_labels = _info_grid(
            page,
            (
                ("HID backend", "backend"),
                ("Device path", "path"),
                ("Report size", "report_size"),
                ("Live send policy", "send_policy"),
                ("ACK missed rate", "missed_rate"),
                ("Last ACK status", "ack_status"),
                ("Policy transition", "transition"),
            ),
        )
        group.setLayout(grid)
        layout.addWidget(group)

        profile_btn = QPushButton("Refresh USB profile")
        mark_primary(profile_btn)
        profile_btn.clicked.connect(self._refresh_usb_profile)
        layout.addWidget(profile_btn)
        self._usb_message = QPlainTextEdit()
        self._usb_message.setReadOnly(True)
        self._usb_message.setMaximumHeight(140)
        layout.addWidget(self._usb_message)
        layout.addStretch(1)
        return page

    def _build_colour_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        probe_group = QGroupBox("Colour path probe")
        probe_layout = QVBoxLayout(probe_group)
        probe_layout.addWidget(
            _welcome_label(
                probe_group,
                "Compare capture → processing → LED output for one zone. "
                "Stop mirroring first for a fresh one-shot capture.",
            )
        )
        zone_row = QHBoxLayout()
        zone_row.addWidget(QLabel("Zone index:"))
        self._zone_spin = QSpinBox()
        self._zone_spin.setMinimum(0)
        self._zone_spin.setMaximum(255)
        zone_row.addWidget(self._zone_spin)
        zone_row.addStretch(1)
        probe_layout.addLayout(zone_row)

        probe_btn = QPushButton("Compare zone colour path")
        mark_primary(probe_btn)
        probe_btn.clicked.connect(self._run_colour_probe)
        probe_layout.addWidget(probe_btn)

        pick_btn = QPushButton("Pick screen colour (portal)")
        mark_compact(pick_btn)
        pick_btn.clicked.connect(self._run_portal_pick)
        probe_layout.addWidget(pick_btn)
        layout.addWidget(probe_group)

        flicker_group = QGroupBox("Flicker lab")
        flicker_layout = QVBoxLayout(flicker_group)
        flicker_layout.addWidget(
            _welcome_label(
                flicker_group,
                "Synthetic scenes run through the colour pipeline offline — no strip required.",
            )
        )
        scenario_row = QHBoxLayout()
        scenario_row.addWidget(QLabel("Scenario:"))
        self._flicker_combo = QComboBox()
        self._flicker_combo.addItem("All scenarios", "all")
        for scenario in flicker_scenarios():
            self._flicker_combo.addItem(scenario.title, scenario.key)
        scenario_row.addWidget(self._flicker_combo, 1)
        flicker_layout.addLayout(scenario_row)
        flicker_btn = QPushButton("Run flicker lab")
        mark_primary(flicker_btn)
        flicker_btn.clicked.connect(self._run_flicker_lab)
        flicker_layout.addWidget(flicker_btn)
        layout.addWidget(flicker_group)

        self._colour_output = QPlainTextEdit()
        self._colour_output.setReadOnly(True)
        layout.addWidget(self._colour_output, 1)
        return page

    def _open_live_diagnostics(self) -> None:
        if self._open_live_diagnostics_fn is not None:
            self._open_live_diagnostics_fn()

    def _export_bundle(self) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        default_name = f"nanoleaf-diagnostics-{stamp}.zip"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export diagnostic bundle",
            str(Path.home() / default_name),
            "Zip archives (*.zip)",
        )
        if not path:
            return
        if not str(path).lower().endswith(".zip"):
            path = f"{path}.zip"
        result = self._export_bundle_fn(path)
        self._overview_status.setPlainText(str(result.get("message", "")))
        if result.get("ok"):
            QMessageBox.information(self, "Bundle exported", str(result.get("message", "")))
        else:
            QMessageBox.warning(self, "Export failed", str(result.get("message", "")))

    def _forget_portal_token(self) -> None:
        result = self._forget_portal_token_fn()
        self._portal_message.setPlainText(str(result.get("message", "")))
        self._refresh_all()

    def _refresh_usb_profile(self) -> None:
        status = self._status_fn()
        profile = status.get("usb_transport_profile")
        if not isinstance(profile, dict):
            self._usb_message.setPlainText(
                "Connect the strip and start mirroring, then refresh again."
            )
            return
        self._usb_message.setPlainText(json.dumps(profile, indent=2, sort_keys=True))
        self._apply_usb_profile(profile)

    def _run_colour_probe(self) -> None:
        zone_index = int(self._zone_spin.value())
        result = self._colour_probe_fn(zone_index=zone_index)
        if not result.get("ok"):
            self._colour_output.setPlainText(str(result.get("message", "Probe failed.")))
            return
        comparison = result.get("comparison")
        lines = [str(result.get("message", ""))]
        if isinstance(comparison, dict):
            lines.append(json.dumps(comparison, indent=2, sort_keys=True))
        self._colour_output.setPlainText("\n".join(lines))

    def _run_portal_pick(self) -> None:
        self._colour_output.setPlainText("Waiting for portal colour pick…")
        self.repaint()
        result = self._portal_pick_fn()
        if not result.get("ok"):
            self._colour_output.setPlainText(str(result.get("message", "Pick failed.")))
            return
        rgb = result.get("rgb")
        probe = self._colour_probe_fn(zone_index=int(self._zone_spin.value()))
        lines = [str(result.get("message", "")), f"Picked RGB: {rgb}"]
        if probe.get("ok") and isinstance(probe.get("comparison"), dict):
            final = probe["comparison"].get("final_rgb")
            lines.append(f"Zone {self._zone_spin.value()} final output: {final}")
        self._colour_output.setPlainText("\n".join(lines))

    def _run_flicker_lab(self) -> None:
        scenario_key = str(self._flicker_combo.currentData() or "all")
        result = self._flicker_lab_fn(scenario_key=scenario_key)
        self._colour_output.setPlainText(json.dumps(result, indent=2, sort_keys=True))

    def _apply_usb_profile(self, profile: dict[str, Any]) -> None:
        self._usb_labels["backend"].setText(str(profile.get("backend_class") or "—"))
        self._usb_labels["path"].setText(str(profile.get("opened_path") or "—"))
        report_size = int(profile.get("report_size", 0) or 0)
        self._usb_labels["report_size"].setText(str(report_size) if report_size else "—")
        self._usb_labels["send_policy"].setText(str(profile.get("live_send_policy") or "—"))
        missed = float(profile.get("missed_ack_rate", 0.0) or 0.0)
        self._usb_labels["missed_rate"].setText(f"{missed * 100.0:.1f}%")
        self._usb_labels["ack_status"].setText(str(profile.get("last_ack_status") or "—"))
        self._usb_labels["transition"].setText(
            str(profile.get("send_policy_transition_reason") or "—")
        )

    def _refresh_all(self) -> None:
        try:
            status = self._status_fn()
        except Exception:
            _log.debug("Diagnostic hub refresh failed", exc_info=True)
            return

        running = bool(status.get("running"))
        self._overview_labels["running"].setText("Active" if running else "Stopped")
        backend = str(
            status.get("effective_capture_backend") or status.get("capture_backend") or "—"
        )
        self._overview_labels["backend"].setText(backend)
        device = "Connected" if bool(status.get("device_discovered")) else "Not connected"
        self._overview_labels["device"].setText(device)
        self._overview_labels["calibration"].setText(str(status.get("calibration_status") or "—"))

        warnings = status.get("runtime_warnings")
        warning_rows = warnings if isinstance(warnings, list) else []
        self._overview_labels["warning_count"].setText(str(len(warning_rows)))
        if warning_rows:
            summary = "; ".join(str(row.get("message", row)) for row in warning_rows[:3])
            self._warnings_banner.setText(f"Heads up: {summary}")
            self._warnings_banner.setVisible(True)
        else:
            self._warnings_banner.setVisible(False)

        identity = status.get("latest_capture_source_identity")
        if isinstance(identity, dict):
            self._source_labels["fingerprint"].setText(str(identity.get("fingerprint") or "—"))
            self._source_labels["confidence"].setText(str(identity.get("confidence") or "—"))
            self._source_labels["scale_confidence"].setText(
                str(identity.get("scale_confidence") or "—")
            )
            self._source_labels["pipewire_serial"].setText(
                str(identity.get("pipewire_node_serial") or "—")
            )
        else:
            for key in ("fingerprint", "confidence", "scale_confidence", "pipewire_serial"):
                self._source_labels[key].setText("—")
        self._source_labels["change_count"].setText(
            str(int(status.get("capture_source_change_count", 0) or 0))
        )
        frame_ctx = status.get("latest_frame_context")
        if isinstance(frame_ctx, dict):
            source = frame_ctx.get("source") if isinstance(frame_ctx.get("source"), dict) else {}
            monitor = source.get("monitor_id") or source.get("backend_source_id")
            self._source_labels["monitor"].setText(str(monitor or "—"))
            frame_size = frame_ctx.get("frame_size")
            if isinstance(frame_size, (list, tuple)) and len(frame_size) >= 2:
                self._source_labels["frame_size"].setText(f"{frame_size[0]}×{frame_size[1]}")
            else:
                self._source_labels["frame_size"].setText("—")
        else:
            self._source_labels["monitor"].setText("—")
            self._source_labels["frame_size"].setText("—")

        from nanoleaf_sync.tools.portal_tools import portal_restore_token_info

        token_info = portal_restore_token_info()
        self._portal_labels["runtime_state"].setText(
            str(status.get("portal_restore_token_state") or "none")
        )
        self._portal_labels["disk_token"].setText(
            "Saved" if bool(token_info.get("has_token")) else "None"
        )
        self._portal_labels["token_path"].setText(str(token_info.get("path") or "—"))

        profile = status.get("usb_transport_profile")
        if isinstance(profile, dict):
            self._apply_usb_profile(profile)
        else:
            for key in self._usb_labels:
                self._usb_labels[key].setText("—")

        configured_zones = int(status.get("configured_device_zone_count", 0) or 0)
        if configured_zones > 0:
            self._zone_spin.setMaximum(max(0, configured_zones - 1))
