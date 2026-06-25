"""Shared constants and Qt fallbacks for the settings dialog."""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

_log = logging.getLogger(__name__)

FPS_MIN = 1
FPS_MAX = 120
HDR_MAX_NITS_MIN = 80
HDR_MAX_NITS_MAX = 10000
MAX_ZONE_COUNT = 128
SDR_BOOST_NITS_MIN = 80
SDR_BOOST_NITS_MAX = 400
CALIBRATION_MODE_PHYSICAL = "physical zone walk"

SETTINGS_SECTIONS: tuple[str, ...] = (
    "Everyday",
    "Strip setup",
    "Fine-tuning",
    "Colour",
    "Advanced",
)

_LEGACY_SECTION_ALIASES: dict[str, str] = {
    "Display & Color": "Everyday",
    "Performance": "Fine-tuning",
    "Edge Mapping": "Strip setup",
    "Calibration": "Strip setup",
    "Device": "Advanced",
    "Diagnostics": "Advanced",
}


class _FallbackLayout:
    def addWidget(self, *_args, **_kwargs) -> None:
        _log.warning("Qt QVBoxLayout unavailable; settings UI degraded.")
        return None

    def addLayout(self, *_args, **_kwargs) -> None:
        _log.warning("Qt QVBoxLayout unavailable; settings UI degraded.")
        return None

    def addStretch(self, *_args, **_kwargs) -> None:
        return None


class _FallbackWidget:
    def __init__(self, *_args, **_kwargs) -> None:
        _log.warning("Qt QWidget/QGroupBox unavailable; settings UI degraded.")
        return None

    def setLayout(self, *_args, **_kwargs) -> None:
        return None


class _FallbackScrollArea:
    def setWidgetResizable(self, *_args, **_kwargs) -> None:
        _log.warning("Qt QScrollArea unavailable; settings UI degraded.")
        return None

    def setWidget(self, *_args, **_kwargs) -> None:
        return None


def _qt_widget(qt: dict[str, object], name: str, fallback):
    return qt.get(name, fallback)
