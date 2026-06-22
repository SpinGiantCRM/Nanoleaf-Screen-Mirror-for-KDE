from __future__ import annotations

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.service import NanoleafSyncService


def test_run_colour_path_probe_uses_runtime_zone_diagnostics() -> None:
    service = NanoleafSyncService(config=AppConfig())
    service._runtime.latest_zone_diagnostics = [
        {
            "zone_index": 0,
            "side": "top",
            "sampled_rgb": (100, 120, 140),
            "output_rgb_before_led_calibration": (90, 110, 130),
            "final_output_rgb": (80, 100, 120),
        }
    ]
    result = service.run_colour_path_probe(zone_index=0)
    assert result["ok"] is True
    comparison = result["comparison"]
    assert comparison["captured_rgb"] == (100, 120, 140)
    assert comparison["final_rgb"] == (80, 100, 120)


def test_forget_portal_restore_token_delegates(tmp_path, monkeypatch) -> None:
    service = NanoleafSyncService(config=AppConfig())
    token_path = tmp_path / "portal_token"
    token_path.write_text("token", encoding="utf-8")
    monkeypatch.setattr(
        "nanoleaf_sync.tools.portal_tools._DEFAULT_TOKEN_PATH",
        token_path,
    )
    result = service.forget_portal_restore_token()
    assert result["ok"] is True
    assert not token_path.exists()
