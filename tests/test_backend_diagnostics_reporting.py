def test_latency_backend_breakdown_reports_all_attempts() -> None:
    text = open("src/nanoleaf_sync/ui/settings_dialog.py", "r", encoding="utf-8").read()
    assert "def _backend_probe_breakdown_text" in text
    assert "Best backend: not enough measured candidates" in text
    assert "samples=" in text
    assert "median=" in text
    assert "p95=" in text
    assert "jitter=" in text


def test_service_exposes_backend_probe_attempts() -> None:
    service_text = open("src/nanoleaf_sync/service.py", "r", encoding="utf-8").read()
    factory_text = open("src/nanoleaf_sync/capture/factory.py", "r", encoding="utf-8").read()
    assert "status[\"backend_probe_attempts\"]" in service_text
    assert "def last_auto_probe_report()" in factory_text
