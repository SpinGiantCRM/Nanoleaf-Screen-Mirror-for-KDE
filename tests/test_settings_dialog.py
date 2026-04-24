import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.settings_dialog import SettingsDialog


def test_settings_dialog_requires_qt_runtime() -> None:
    with pytest.raises(RuntimeError):
        SettingsDialog(None, AppConfig(), calibration_sender=None, runtime_status={})
