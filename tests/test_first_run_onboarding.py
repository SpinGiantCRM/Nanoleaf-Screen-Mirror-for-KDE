from __future__ import annotations

from nanoleaf_sync.ui.tray_app import first_run_message


def test_first_run_message_for_demo_mode() -> None:
    message = first_run_message("diagnostic")
    assert "Mock (no hardware) mode" in message
    assert "Settings" in message


def test_first_run_message_for_real_mode() -> None:
    message = first_run_message("full-real")
    assert "Real hardware mode" in message
    assert "Troubleshooting" in message
