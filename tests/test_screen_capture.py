import numpy as np
import pytest

from nanoleaf_sync.capture.factory import create_capture_backend
from nanoleaf_sync.capture.kmsgrab import KMSGrabCapture


def test_capture_factory_mock_is_reusable() -> None:
    backend = create_capture_backend(
        width=4,
        height=3,
        use_mock_capture=True,
        prefer_backend="kmsgrab",
        allow_fallback=True,
        hdr_max_nits=1000.0,
        hdr_transfer="srgb",
        hdr_primaries="bt709",
    )

    frame1 = backend.capture()
    frame2 = backend.capture()

    assert isinstance(frame1, np.ndarray)
    assert frame1.shape == (3, 4, 3)
    assert frame1.dtype == np.uint8
    # Mock capture reuses a single buffer to reduce allocations.
    assert frame1 is frame2


def test_capture_factory_kwin_stub_is_black_and_reusable() -> None:
    backend = create_capture_backend(
        width=5,
        height=2,
        use_mock_capture=False,
        prefer_backend="kwin-dbus",
        allow_fallback=True,
        hdr_max_nits=1000.0,
        hdr_transfer="srgb",
        hdr_primaries="bt709",
    )

    frame1 = backend.capture()
    frame2 = backend.capture()

    assert frame1 is frame2
    assert np.array_equal(frame1, np.zeros((2, 5, 3), dtype=np.uint8))


def test_capture_factory_kmsgrab_fallback_vs_no_fallback() -> None:
    # When allow_fallback=True, missing DRM bindings should fall back to kwin stub
    backend_ok = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="kmsgrab",
        allow_fallback=True,
        hdr_max_nits=1000.0,
        hdr_transfer="srgb",
        hdr_primaries="bt709",
    )
    frame = backend_ok.capture()
    assert frame.shape == (4, 6, 3)
    assert frame.dtype == np.uint8

    # When allow_fallback=False, missing DRM bindings should raise
    backend_fail = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="kmsgrab",
        allow_fallback=False,
        hdr_max_nits=1000.0,
        hdr_transfer="srgb",
        hdr_primaries="bt709",
    )
    with pytest.raises(Exception):
        _ = backend_fail.capture()


def test_kmsgrab_downsamples_before_hdr_conversion(monkeypatch) -> None:
    backend = KMSGrabCapture(width=1920, height=1080)
    rgb = np.zeros((1080, 1920, 3), dtype=np.uint16)
    captured_shape = None

    def _fake_convert(frame: np.ndarray, metadata):
        nonlocal captured_shape
        captured_shape = frame.shape
        return np.zeros_like(frame, dtype=np.uint8)

    monkeypatch.setattr(
        "nanoleaf_sync.capture.kmsgrab.convert_frame_to_srgb8", _fake_convert
    )
    out = backend._convert_if_needed(
        (
            rgb,
            {"transfer": "pq", "primaries": "bt2020", "max_nits": 1000.0},
        )
    )
    assert out.dtype == np.uint8
    assert captured_shape is not None
    assert captured_shape[0] < 1080
    assert captured_shape[1] < 1920
    assert out.shape == (1080, 1920, 3)
