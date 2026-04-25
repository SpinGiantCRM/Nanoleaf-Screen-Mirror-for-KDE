from __future__ import annotations

from nanoleaf_sync.capture.latency_probe import (
    FrameTimingSample,
    LatencyProbe,
    STAGE_CAPTURE_WAIT,
    STAGE_COLOUR_PROCESSING,
    STAGE_FRAME_TOTAL,
    STAGE_HID_WRITE,
    STAGE_LOOP_GAP,
    STAGE_SMOOTHING,
)


def test_latency_probe_populates_per_stage_statistics() -> None:
    probe = LatencyProbe(max_samples=16)
    samples = [
        FrameTimingSample(
            stage_ms={
                STAGE_CAPTURE_WAIT: 1.2,
                STAGE_COLOUR_PROCESSING: 2.5,
                STAGE_SMOOTHING: 1.1,
                STAGE_HID_WRITE: 0.8,
                STAGE_FRAME_TOTAL: 7.4,
                STAGE_LOOP_GAP: 8.3,
            },
            dropped_or_skipped_frames_delta=1 if i == 0 else 0,
        )
        for i in range(5)
    ]
    for row in samples:
        assert probe.add_stage_sample(row)

    measurement = probe.measurement()
    assert measurement is not None
    total = measurement.stages[STAGE_FRAME_TOTAL]
    assert total.sample_count == 5
    assert total.median_ms > 0.0
    assert total.p95_ms >= total.median_ms
    assert total.max_ms >= total.p95_ms
    assert measurement.dropped_or_skipped_frames == 1
    assert measurement.effective_output_fps > 0.0


def test_latency_probe_reports_unavailable_stage_honestly() -> None:
    probe = LatencyProbe()
    probe.add_stage_sample(
        FrameTimingSample(stage_ms={STAGE_FRAME_TOTAL: 8.0, STAGE_LOOP_GAP: 8.3})
    )
    measurement = probe.measurement()
    assert measurement is not None
    assert measurement.stages[STAGE_CAPTURE_WAIT].available is False


def test_latency_probe_rejects_negative_stage_values() -> None:
    probe = LatencyProbe()
    assert probe.add_stage_sample(
        FrameTimingSample(stage_ms={STAGE_FRAME_TOTAL: -1.0})
    ) is False
    assert probe.measurement() is None
