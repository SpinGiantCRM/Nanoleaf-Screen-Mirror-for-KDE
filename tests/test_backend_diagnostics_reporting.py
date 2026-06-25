from nanoleaf_sync.capture.factory import last_auto_probe_report, run_fresh_backend_probe
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.diagnostics_exports import format_backend_attempt_row
from nanoleaf_sync.service import NanoleafSyncService
from tests.qt_headless import button_texts, make_settings_dialog


def test_latency_backend_breakdown_reports_all_attempts(monkeypatch) -> None:
    row = format_backend_attempt_row(
        {
            "backend": "kwin-dbus",
            "status": "tested",
            "mode": "fresh-probe",
            "sample_count": 3,
            "median_ms": 12.3,
            "p95_ms": 15.0,
            "jitter_ms": 1.2,
            "score": 0.91,
            "selected": True,
            "tentative": False,
            "reason": "ok",
        }
    )
    assert "samples=3" in row
    assert "median=12.3" in row
    assert "p95=15.0" in row
    assert "jitter=1.2" in row
    assert "score=0.91" in row
    assert "mode=fresh-probe" in row
    assert "selected=yes" in row
    assert "tentative=no" in row

    _qt, _app, _dialog, widget = make_settings_dialog(monkeypatch)
    empty = widget._backend_probe_breakdown_text(selected_backend="none")
    assert "Last auto-run probe result: waiting for first result." in empty
    widget._probe_session_state["backend_probe_attempts"] = [
        {
            "backend": "kwin-dbus",
            "status": "tested",
            "mode": "fresh-probe",
            "sample_count": 2,
            "median_ms": 10.0,
            "p95_ms": 12.0,
            "jitter_ms": 1.0,
            "score": 0.8,
            "selected": True,
            "tentative": False,
            "reason": "ok",
        }
    ]
    manual = widget._backend_probe_breakdown_text(
        selected_backend="kwin-dbus", result_origin="manual"
    )
    assert "Last manual probe result." in manual
    assert "Candidate backends:" in manual
    assert "Selected backend: kwin-dbus." in manual
    cached = widget._backend_probe_breakdown_text(
        selected_backend="kwin-dbus", result_origin="auto"
    )
    widget._runtime_status["cached_probe_backend"] = "kwin-dbus"
    cached = widget._backend_probe_breakdown_text(
        selected_backend="kwin-dbus", result_origin="auto"
    )
    assert "Using cached backend: kwin-dbus." in cached

    buttons = button_texts(widget, _qt)
    assert "Re-test backends (fresh probe)" in buttons
    assert "Test xdg-portal" in buttons
    assert "Benchmark xdg-portal" in buttons
    assert hasattr(widget, "_backend_probe_blocked_by_runtime_state")
    assert hasattr(widget, "_run_xdg_portal_benchmark")
    widget._runtime_status["startup_state"] = "running"
    assert widget._backend_probe_blocked_by_runtime_state() is True
    widget._run_fresh_backend_probe()
    assert "Stop mirroring before re-testing backends." in widget.latency_label.text()


def test_service_exposes_backend_probe_attempts() -> None:
    svc = NanoleafSyncService(config=AppConfig())
    status = svc.get_status()
    assert "backend_probe_attempts" in status
    assert isinstance(status["backend_probe_attempts"], list)
    assert callable(last_auto_probe_report)
    assert callable(run_fresh_backend_probe)
