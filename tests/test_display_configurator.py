import pytest

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.ui.display_configurator import DisplayConfiguratorDialog


def test_display_configurator_requires_qt_runtime() -> None:
    with pytest.raises(RuntimeError):
        DisplayConfiguratorDialog(None, AppConfig(), calibration_sender=None, runtime_status={})
