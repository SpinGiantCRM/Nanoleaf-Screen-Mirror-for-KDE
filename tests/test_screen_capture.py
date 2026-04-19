import numpy as np
import pytest

from nanoleaf_sync.capture.factory import create_capture_backend
from nanoleaf_sync.capture.kmsgrab import KMSGrabCapture


def test_capture_factory_mock_is_reusable() -> None:
    backend = create_capture_backend(
        width=4,
        height=3,
        use_mock_capture=True,
        prefer_backend="kwin-dbus",
    )

    frame1 = backend.capture()
    frame2 = backend.capture()

    assert isinstance(frame1, np.ndarray)
    assert frame1.shape == (3, 4, 3)
    assert frame1.dtype == np.uint8
    assert frame1 is frame2


def test_capture_factory_rejects_non_primary_real_backends() -> None:
    with pytest.raises(ValueError, match="supports only 'kwin-dbus'"):
        create_capture_backend(
            width=6,
            height=4,
            use_mock_capture=False,
            prefer_backend="kmsgrab",
        )


def test_kmsgrab_converts_hdr_before_any_resizing(monkeypatch) -> None:
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
    assert captured_shape == (1080, 1920, 3)
    assert out.shape == (1080, 1920, 3)


def test_capture_factory_passes_hdr_params_to_kwin_backend(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeKWinBackend:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "nanoleaf_sync.capture.factory.KWinDBusScreenshotCapture",
        _FakeKWinBackend,
    )

    create_capture_backend(
        width=1920,
        height=1080,
        use_mock_capture=False,
        prefer_backend="kwin-dbus",
        hdr_max_nits=1600.0,
        hdr_transfer="pq",
        hdr_primaries="bt2020",
    )

    assert captured["width"] == 1920
    assert captured["height"] == 1080
    assert captured["hdr_max_nits"] == 1600.0
    assert captured["hdr_transfer"] == "pq"
    assert captured["hdr_primaries"] == "bt2020"
