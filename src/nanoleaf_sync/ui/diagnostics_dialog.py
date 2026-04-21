from __future__ import annotations

from dataclasses import dataclass

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.calibration_state import backend_selection_info
from nanoleaf_sync.ui.qt_lazy import load_qt


@dataclass
class DiagnosticsSnapshot:
    requested_backend: str
    selected_backend: str
    effective_backend: str
    selection_reason: str
    source: str
    unresolved_reason: str
    runtime_started: bool
    from_auto_probe: bool
    auto_probe_timestamp: str
    detected_device_zone_count: int
    configured_device_zone_count: int


class BackendDiagnosticsDialog:
    """Diagnostics-only dialog for backend status.

    Calibration and testing controls were moved to SettingsDialog.
    """

    def __init__(self, parent, *, cfg: AppConfig, runtime_status: dict) -> None:
        qt = load_qt()
        QDialog = qt["QDialog"]
        QGridLayout = qt["QGridLayout"]
        QLabel = qt["QLabel"]

        class _Dialog(QDialog):
            def __init__(self):
                super().__init__(parent)
                self.setWindowTitle("Backend Diagnostics")
                self._cfg = cfg
                self._status = runtime_status

                self.status_label = QLabel("")
                self.debug_label = QLabel("")
                self.note_label = QLabel(
                    "Calibration and test controls live in Settings → Calibration & Testing."
                )

                layout = QGridLayout()
                layout.addWidget(QLabel("Backend selection"), 0, 0, 1, 2)
                layout.addWidget(self.status_label, 1, 0, 1, 2)
                layout.addWidget(self.debug_label, 2, 0, 1, 2)
                layout.addWidget(self.note_label, 3, 0, 1, 2)
                self.setLayout(layout)
                self._refresh()

            def _snapshot(self) -> DiagnosticsSnapshot:
                info = backend_selection_info(self._status, self._cfg)
                return DiagnosticsSnapshot(
                    requested_backend=info.requested_policy,
                    selected_backend=info.selected_backend,
                    effective_backend=info.effective_backend,
                    selection_reason=info.reason,
                    source=info.source,
                    unresolved_reason=info.unresolved_reason,
                    runtime_started=info.runtime_started,
                    from_auto_probe=bool(self._status.get("from_auto_probe")),
                    auto_probe_timestamp=str(getattr(self._cfg, "auto_probe_timestamp", "") or "n/a"),
                    detected_device_zone_count=int(self._status.get("device_zone_count") or 0),
                    configured_device_zone_count=int(self._cfg.device_zone_count or 0),
                )

            def _refresh(self):
                snapshot = self._snapshot()
                self.status_label.setText(
                    f"Requested backend policy: {snapshot.requested_backend} | Selected backend: {snapshot.selected_backend}\n"
                    f"Effective runtime backend: {snapshot.effective_backend} | Source: {snapshot.source} | Reason: {snapshot.selection_reason}"
                    + (f"\nUnresolved reason: {snapshot.unresolved_reason}" if snapshot.unresolved_reason else "")
                )
                self.debug_label.setText(
                    f"Runtime started: {snapshot.runtime_started} | From auto probe: {snapshot.from_auto_probe} | Auto probe timestamp: {snapshot.auto_probe_timestamp}\n"
                    f"Detected strip zones: {snapshot.detected_device_zone_count or 'unknown'} | Configured strip zones: {snapshot.configured_device_zone_count or 'auto'}"
                )

        self._dialog = _Dialog()

    def exec(self) -> int:
        return self._dialog.exec()

    def show(self) -> None:
        self._dialog.show()

    def raise_(self) -> None:
        self._dialog.raise_()

    def activateWindow(self) -> None:
        self._dialog.activateWindow()

    def set_runtime_status(self, runtime_status: dict) -> None:
        self._dialog._status = runtime_status
        self._dialog._refresh()

    def set_config(self, cfg: AppConfig) -> None:
        self._dialog._cfg = cfg
        self._dialog._refresh()


# Backward-compat alias for older imports.
CalibrationDiagnosticsDialog = BackendDiagnosticsDialog
