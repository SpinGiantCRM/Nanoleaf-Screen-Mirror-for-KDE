from __future__ import annotations

from nanoleaf_sync.capture.latency_probe import LatencyProbe


def test_latency_probe_populates_measured_statistics() -> None:
    probe = LatencyProbe(max_samples=16)
    base = 100.0
    for i, delta in enumerate([0.016, 0.017, 0.016, 0.018, 0.016]):
        capture = base + (i * 0.016)
        process_done = capture + 0.003
        send_done = capture + delta
        assert probe.add_sample(
            capture_ts=capture,
            process_done_ts=process_done,
            send_done_ts=send_done,
        )

    measurement = probe.measurement()
    assert measurement is not None
    assert measurement.sample_count == 5
    assert measurement.pipeline_median_ms > 0.0
    assert measurement.pipeline_p95_ms >= measurement.pipeline_median_ms
    assert measurement.pipeline_jitter_ms >= 0.0


def test_latency_probe_rejects_invalid_timestamps() -> None:
    probe = LatencyProbe()
    assert probe.add_sample(capture_ts=1.0, process_done_ts=0.5, send_done_ts=1.2) is False
    assert probe.measurement() is None
