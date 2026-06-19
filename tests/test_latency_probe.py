from __future__ import annotations

from nanoleaf_sync.capture.latency_probe import (
    STAGE_ACTUAL_WORK,
    STAGE_CAPTURE_CALL,
    STAGE_CAPTURE_SUCCESS_INTERVAL,
    STAGE_CAPTURE_WAIT,
    STAGE_FRAME_HANDOFF_WAIT,
    STAGE_FRAME_PROCESSING,
    STAGE_HID_WRITE,
    STAGE_LOOP_GAP,
    FrameTimingSample,
    LatencyProbe,
)


def test_latency_probe_populates_per_stage_statistics() -> None:
    probe = LatencyProbe(max_samples=16)
    samples = [
        FrameTimingSample(
            stage_ms={
                STAGE_CAPTURE_WAIT: 1.2,
                STAGE_CAPTURE_CALL: 2.1,
                STAGE_CAPTURE_SUCCESS_INTERVAL: 8.4,
                STAGE_FRAME_HANDOFF_WAIT: 0.2,
                STAGE_FRAME_PROCESSING: 2.5,
                STAGE_HID_WRITE: 0.8,
                STAGE_ACTUAL_WORK: 7.4,
                STAGE_LOOP_GAP: 8.3,
            },
            target_fps=120.0,
            fps_cap=120.0,
            fps_cap_reason="UI FPS control cap",
            dropped_or_skipped_frames_delta=1 if i == 0 else 0,
            counters_delta={"no_pending_frame_ticks": 2},
            flags={"capture_worker_active": True},
            labels={"latest_capture_backend_name": "kwin-dbus"},
        )
        for i in range(5)
    ]
    for row in samples:
        assert probe.add_stage_sample(row)

    measurement = probe.measurement()
    assert measurement is not None
    total = measurement.stages[STAGE_ACTUAL_WORK]
    assert total.sample_count == 5
    assert total.median_ms > 0.0
    assert total.p95_ms >= total.median_ms
    assert total.max_ms >= total.p95_ms
    assert measurement.dropped_or_skipped_frames == 1
    assert measurement.effective_output_fps > 0.0
    assert measurement.target_fps == 120.0
    assert measurement.counters["no_pending_frame_ticks"] == 10
    assert measurement.flags["capture_worker_active"] is True
    assert measurement.labels["latest_capture_backend_name"] == "kwin-dbus"


def test_latency_probe_reports_unavailable_stage_honestly() -> None:
    probe = LatencyProbe()
    probe.add_stage_sample(
        FrameTimingSample(stage_ms={STAGE_ACTUAL_WORK: 8.0, STAGE_LOOP_GAP: 8.3})
    )
    measurement = probe.measurement()
    assert measurement is not None
    assert measurement.stages[STAGE_CAPTURE_WAIT].available is False


def test_latency_probe_rejects_negative_stage_values() -> None:
    probe = LatencyProbe()
    assert probe.add_stage_sample(FrameTimingSample(stage_ms={STAGE_ACTUAL_WORK: -1.0})) is False
    assert probe.measurement() is None
