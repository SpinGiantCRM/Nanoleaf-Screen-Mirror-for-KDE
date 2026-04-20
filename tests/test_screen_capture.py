import numpy as np
import pytest

from nanoleaf_sync.capture.backend_normalization import normalize_capture_backend
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


def test_capture_factory_creates_kmsgrab_backend() -> None:
    backend = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="kmsgrab",
    )
    assert backend.name == "kmsgrab"


def test_capture_factory_creates_xdg_portal_backend() -> None:
    backend = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="xdg-portal",
    )
    assert backend.name == "xdg-portal"


def test_backend_alias_normalization_helper() -> None:
    assert normalize_capture_backend("portal") == "xdg-portal"
    assert normalize_capture_backend("KWIN_DBUS") == "kwin-dbus"
    assert normalize_capture_backend("kms-grab") == "kmsgrab"


def test_capture_factory_auto_prefers_kmsgrab_when_low_latency_path_is_available(
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanoleaf_sync.capture.factory._has_drm_device", lambda: True)
    monkeypatch.setattr(
        "nanoleaf_sync.capture.factory._kmsgrab_bindings_available", lambda: True
    )
    backend = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="auto",
    )
    assert backend.name == "kmsgrab"


def test_capture_factory_auto_falls_back_to_kwin_when_kmsgrab_is_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanoleaf_sync.capture.factory._has_drm_device", lambda: False)
    monkeypatch.setattr(
        "nanoleaf_sync.capture.factory._kmsgrab_bindings_available", lambda: False
    )
    backend = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="auto",
    )
    assert backend.name == "kwin-dbus"


def test_capture_factory_explicit_backend_bypasses_probe(monkeypatch) -> None:
    def _fail_probe(*_args, **_kwargs):
        raise AssertionError("probe should not run for explicit backend")

    monkeypatch.setattr("nanoleaf_sync.capture.auto_probe.probe_backends", _fail_probe)
    backend = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="xdg-portal",
    )
    assert backend.name == "xdg-portal"


def test_capture_factory_auto_uses_cached_probe_winner_without_probing(monkeypatch) -> None:
    def _fail_probe(*_args, **_kwargs):
        raise AssertionError("probe should not run when cached winner is valid")

    monkeypatch.setattr("nanoleaf_sync.capture.auto_probe.probe_backends", _fail_probe)
    backend = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="auto",
        cached_probe_winner="kwin-dbus",
    )
    assert backend.name == "kwin-dbus"


def test_capture_factory_auto_respects_probe_kill_switch(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("NANOLEAF_DISABLE_CAPTURE_PROBE", "1")
    monkeypatch.setattr("nanoleaf_sync.capture.factory._resolve_auto_backend", lambda: "kwin-dbus")
    caplog.set_level("INFO")
    backend = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="auto",
    )
    assert backend.name == "kwin-dbus"
    assert "capture auto-probe skipped" in caplog.text


def test_capture_factory_auto_probe_failure_falls_back_to_capability_logic(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _raise_probe(*_args, **_kwargs):
        raise RuntimeError("synthetic probe failure")

    monkeypatch.setattr("nanoleaf_sync.capture.auto_probe.probe_backends", _raise_probe)
    monkeypatch.setattr("nanoleaf_sync.capture.factory._resolve_auto_backend", lambda: "kwin-dbus")
    caplog.set_level("INFO")
    backend = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="auto",
    )
    assert backend.name == "kwin-dbus"
    assert "capture auto-probe failed" in caplog.text


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


def test_kmsgrab_probes_modules_once_and_falls_back_without_import_exceptions(monkeypatch) -> None:
    calls = {"imports": 0}

    def _fake_import(_name):
        calls["imports"] += 1
        raise ImportError("missing")

    monkeypatch.setattr("nanoleaf_sync.capture.kmsgrab.import_module", _fake_import)

    backend = KMSGrabCapture(width=4, height=3)

    fallback_frame = np.zeros((3, 4, 3), dtype=np.uint8)
    monkeypatch.setattr(backend._fallback, "capture", lambda: fallback_frame)

    first = backend.capture()
    second = backend.capture()

    assert first.shape == (3, 4, 3)
    assert second.shape == (3, 4, 3)
    # Two probes only (internal module + external kmsgrab), not per frame.
    assert calls["imports"] == 2
