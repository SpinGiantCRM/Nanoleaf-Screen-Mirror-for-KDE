"""Settings dialog entry point."""

from __future__ import annotations

from collections.abc import Callable

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.qt_lazy import load_qt
from nanoleaf_sync.ui.settings_dialog_handlers import SettingsDialogHandlersMixin
from nanoleaf_sync.ui.settings_dialog_handlers_ext import SettingsDialogHandlersExtMixin
from nanoleaf_sync.ui.settings_dialog_layout import SettingsDialogLayoutMixin
from nanoleaf_sync.ui.settings_dialog_shared import (
    CALIBRATION_MODE_PHYSICAL,
    FPS_MAX,
    FPS_MIN,
    HDR_MAX_NITS_MAX,
    HDR_MAX_NITS_MIN,
    MAX_ZONE_COUNT,
    SDR_BOOST_NITS_MAX,
    SDR_BOOST_NITS_MIN,
    SETTINGS_SECTIONS,
)
from nanoleaf_sync.ui.settings_dialog_widget import SettingsDialogWidgetBase

__all__ = [
    "CALIBRATION_MODE_PHYSICAL",
    "FPS_MAX",
    "FPS_MIN",
    "HDR_MAX_NITS_MAX",
    "HDR_MAX_NITS_MIN",
    "MAX_ZONE_COUNT",
    "SDR_BOOST_NITS_MAX",
    "SDR_BOOST_NITS_MIN",
    "SETTINGS_SECTIONS",
    "SettingsDialog",
]


class SettingsDialog:
    def __init__(
        self,
        parent,
        cfg: AppConfig,
        *,
        calibration_sender: Callable | None = None,
        diagnostic_capture: Callable | None = None,
        runtime_status: dict | None = None,
        initial_section: str | None = None,
        on_apply: Callable[[AppConfig], None] | None = None,
        dialog_geometry: bytes | None = None,
        forget_portal_token_fn: Callable | None = None,
    ):
        qt = load_qt()
        QDialog = qt["QDialog"]
        widget_cls = type(
            "SettingsDialogWidget",
            (
                SettingsDialogWidgetBase,
                SettingsDialogLayoutMixin,
                SettingsDialogHandlersMixin,
                SettingsDialogHandlersExtMixin,
                QDialog,
            ),
            {},
        )
        self._dialog = widget_cls(
            parent,
            cfg,
            qt=qt,
            calibration_sender=calibration_sender,
            diagnostic_capture=diagnostic_capture,
            runtime_status=runtime_status,
            initial_section=initial_section,
            on_apply=on_apply,
            dialog_geometry=dialog_geometry,
            forget_portal_token_fn=forget_portal_token_fn,
        )

    def exec(self) -> int:
        result = self._dialog.exec()
        save_geom = getattr(self._dialog, "saveGeometry", None)
        if callable(save_geom):
            self._saved_geometry = bytes(save_geom())
        return result

    def settings_applied_in_session(self) -> bool:
        return bool(self._dialog.settings_applied_in_session())

    def wants_display_configurator(self) -> bool:
        return bool(self._dialog.wants_display_configurator())

    def updated_config(self) -> AppConfig:
        return self._dialog.updated_config()

    def saved_geometry(self) -> bytes | None:
        return getattr(self, "_saved_geometry", None)
