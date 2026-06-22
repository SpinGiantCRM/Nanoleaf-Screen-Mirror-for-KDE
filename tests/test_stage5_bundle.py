from __future__ import annotations

import json
import zipfile
from pathlib import Path

from nanoleaf_sync.tools.diagnostic_bundle import create_diagnostic_bundle, redact_text


def test_redact_text_hides_home_directory(tmp_path: Path) -> None:
    redacted = redact_text("config path /home/alice/.config/nanoleaf")
    assert "/home/alice" not in redacted
    assert "<redacted>" in redacted


def test_create_diagnostic_bundle_writes_expected_files(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.zip"
    create_diagnostic_bundle(
        bundle_path,
        runtime_status={
            "effective_capture_backend": "kwin-dbus",
            "latest_frame_context": {
                "capture_method": "CaptureScreen",
                "frame_size": [1920, 1080],
                "source": {"monitor_id": "DP-1"},
            },
            "latest_color_context": {"confidence": "backend"},
            "configured_device_zone_count": 48,
            "detected_device_zone_count": 48,
        },
    )
    with zipfile.ZipFile(bundle_path) as archive:
        names = set(archive.namelist())
        assert "bundle.json" in names
        assert "runtime_status.json" in names
        assert "config_redacted.json" in names
        assert "doctor_report.txt" in names
        assert "issue_template.txt" in names
        bundle_meta = json.loads(archive.read("bundle.json"))
        assert bundle_meta["backend"] == "kwin-dbus"
