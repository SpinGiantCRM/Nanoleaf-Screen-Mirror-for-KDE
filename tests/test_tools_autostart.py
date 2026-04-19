from __future__ import annotations

import subprocess
from pathlib import Path

from nanoleaf_sync.tools import autostart


def test_status_systemd_uses_systemctl_state(monkeypatch, capsys) -> None:
    path = Path("/tmp/nanoleaf-kde-sync.service")

    def _fake_run(cmd, capture_output, text, timeout, check):
        assert cmd == ["systemctl", "--user", "is-enabled", "nanoleaf-kde-sync.service"]
        return subprocess.CompletedProcess(cmd, 0, stdout="enabled\n")

    monkeypatch.setattr(autostart, "user_systemd_service_path", lambda: path)
    monkeypatch.setattr(autostart.subprocess, "run", _fake_run)

    rc = autostart.main(["status", "--method", "systemd"])

    assert rc == 0
    assert "Autostart is enabled: nanoleaf-kde-sync.service" in capsys.readouterr().out
