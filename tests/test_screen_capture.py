import builtins
import ctypes

import numpy as np
import pytest

from nanoleaf_sync.capture.backend_normalization import normalize_capture_backend
from nanoleaf_sync.capture.errors import KMSGrabError
from nanoleaf_sync.capture.factory import create_capture_backend
from nanoleaf_sync.capture.kmsgrab import KMSGrabCapture


def test_capture_factory_mock_is_reusable(monkeypatch) -> None:
    monkeypatch.setattr("nanoleaf_sync.capture.factory._has_drm_device", lambda: False)
    monkeypatch.setattr("nanoleaf_sync.capture.factory._kmsgrab_bindings_available", lambda: False)

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
    assert np.array_equal(frame1, frame2)


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


@pytest.mark.parametrize(
    ("requested_backend", "expected_backend"),
    [
        ("KWIN_DBUS", "kwin-dbus"),
        ("portal", "xdg-portal"),
        ("kms-grab", "kmsgrab"),
        ("auto", "kwin-dbus"),
    ],
)
def test_backend_preference_resolution_only_emits_supported_backend_tokens(
    monkeypatch,
    requested_backend: str,
    expected_backend: str,
) -> None:
    from nanoleaf_sync.capture.factory import _resolve_prefer_backend

    monkeypatch.setattr(
        "nanoleaf_sync.capture.factory._resolve_auto_backend_with_probe",
        lambda **_kwargs: "kwin-dbus",
    )

    resolved = _resolve_prefer_backend(
        prefer_backend=requested_backend,
        width=6,
        height=4,
        auto_probe_enabled=True,
        cached_probe_winner=None,
    )

    assert resolved == expected_backend
    assert resolved in {"kwin-dbus", "xdg-portal", "kmsgrab"}


def test_capture_factory_auto_keeps_kwin_when_probe_reports_kmsgrab(
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanoleaf_sync.capture.factory._has_drm_device", lambda: True)
    monkeypatch.setattr("nanoleaf_sync.capture.factory._kmsgrab_bindings_available", lambda: True)

    class _ProbeResult:
        selected_backend = "kmsgrab"
        candidates: list[object] = []

    monkeypatch.setattr(
        "nanoleaf_sync.capture.auto_probe.probe_backends",
        lambda *_args, **_kwargs: _ProbeResult(),
    )
    backend = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="auto",
    )
    assert backend.name == "kwin-dbus"


def test_capture_factory_auto_falls_back_to_kwin_when_kmsgrab_is_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanoleaf_sync.capture.factory._has_drm_device", lambda: False)
    monkeypatch.setattr("nanoleaf_sync.capture.factory._kmsgrab_bindings_available", lambda: False)
    monkeypatch.setenv("NANOLEAF_DISABLE_CAPTURE_PROBE", "1")
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


def test_capture_factory_auto_respects_probe_kill_switch(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("NANOLEAF_DISABLE_CAPTURE_PROBE", "1")
    monkeypatch.setattr("nanoleaf_sync.capture.factory._has_drm_device", lambda: False)
    monkeypatch.setattr("nanoleaf_sync.capture.factory._kmsgrab_bindings_available", lambda: False)
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
    monkeypatch.setattr("nanoleaf_sync.capture.factory._has_drm_device", lambda: False)
    monkeypatch.setattr("nanoleaf_sync.capture.factory._kmsgrab_bindings_available", lambda: False)
    caplog.set_level("INFO")
    backend = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="auto",
    )
    assert backend.name == "kwin-dbus"
    assert "capture auto-probe failed" in caplog.text


def test_capture_factory_auto_legacy_fallback_works_without_probe_dependencies(
    monkeypatch,
) -> None:
    original_import = builtins.__import__

    def _import_hook(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "nanoleaf_sync.capture.auto_probe":
            raise ImportError("probe module unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import_hook)
    monkeypatch.setattr("nanoleaf_sync.capture.factory._has_drm_device", lambda: False)
    monkeypatch.setattr("nanoleaf_sync.capture.factory._kmsgrab_bindings_available", lambda: False)

    backend = create_capture_backend(
        width=6,
        height=4,
        use_mock_capture=False,
        prefer_backend="auto",
    )

    assert backend.name == "kwin-dbus"


def test_kmsgrab_converts_hdr_before_any_resizing(monkeypatch) -> None:
    backend = KMSGrabCapture(width=1920, height=1080)
    rgb = np.zeros((1080, 1920, 3), dtype=np.uint16)
    captured_shape = None
    captured_metadata: dict[str, object] | None = None

    def _fake_convert(frame: np.ndarray, metadata):
        nonlocal captured_shape, captured_metadata
        captured_shape = frame.shape
        captured_metadata = dict(metadata)
        return np.zeros_like(frame, dtype=np.uint8)

    monkeypatch.setattr("nanoleaf_sync.capture.kmsgrab.convert_frame_to_srgb8", _fake_convert)
    out = backend._convert_if_needed(
        (
            rgb,
            {"transfer": "pq", "primaries": "bt2020", "max_nits": 1000.0},
        )
    )
    assert out.dtype == np.uint8
    assert captured_shape == (1080, 1920, 3)
    assert captured_metadata is not None
    assert captured_metadata["source"] == "backend metadata"
    assert captured_metadata["transfer"] == "pq"
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


def test_kmsgrab_reuses_cached_probe_result_across_instances(monkeypatch) -> None:
    calls = {"imports": 0}

    def _fake_import(_name):
        calls["imports"] += 1
        raise ImportError("missing")

    monkeypatch.setattr("nanoleaf_sync.capture.kmsgrab.import_module", _fake_import)

    KMSGrabCapture(width=4, height=3)
    KMSGrabCapture(width=8, height=6)

    # Probe should run only once per process lifecycle (two import attempts total).
    assert calls["imports"] == 2


def test_kmsgrab_drm_capture_keyword_only_callable_is_used() -> None:
    backend = KMSGrabCapture(width=4, height=3)
    calls: list[str] = []

    def _keyword_only(*, width, height, card_path):
        calls.append(f"{width}x{height}@{card_path}")
        return np.zeros((height, width, 3), dtype=np.uint8)

    backend._drm_capture_impl = _keyword_only
    out = backend._capture_drm_rgb()

    assert out.shape == (3, 4, 3)
    assert calls == ["4x3@/dev/dri/card0"]


def test_kmsgrab_drm_capture_positional_only_retry_on_keyword_typeerror() -> None:
    backend = KMSGrabCapture(width=4, height=3)
    calls: list[tuple[int, int, str]] = []

    def _positional_only(width, height, card_path, /):
        calls.append((width, height, card_path))
        return np.zeros((height, width, 3), dtype=np.uint8)

    backend._drm_capture_impl = _positional_only
    out = backend._capture_drm_rgb()

    assert out.shape == (3, 4, 3)
    assert calls == [(4, 3, "/dev/dri/card0")]


def test_kmsgrab_drm_capture_mismatched_signature_raises_actionable_kmsgrab_error() -> None:
    backend = KMSGrabCapture(width=4, height=3)

    def _mismatched(foo, /):
        return np.zeros((1, 1, 3), dtype=np.uint8)

    backend._drm_capture_impl = _mismatched

    with pytest.raises(KMSGrabError) as excinfo:
        backend._capture_drm_rgb()

    msg = str(excinfo.value)
    assert "Attempted signature" in msg
    assert "_mismatched(width=..., height=..., card_path=...)" in msg
    assert "does not support positional retry" in msg


def test_kmsgrab_sticky_kwin_fallback_skips_drm_after_first_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = KMSGrabCapture(width=4, height=3)
    drm_attempts = {"count": 0}

    def _fake_drm_impl(**_kwargs) -> np.ndarray:
        drm_attempts["count"] += 1
        raise KMSGrabError("DRM unavailable")

    backend._drm_capture_impl = _fake_drm_impl
    fallback_calls = {"count": 0}
    fallback_frame = np.zeros((3, 4, 3), dtype=np.uint8)

    def _fallback_capture() -> np.ndarray:
        fallback_calls["count"] += 1
        return fallback_frame

    monkeypatch.setattr(backend._fallback, "capture", _fallback_capture)

    assert backend.capture().shape == (3, 4, 3)
    assert backend.capture().shape == (3, 4, 3)

    assert drm_attempts["count"] == 1
    assert fallback_calls["count"] == 2
    assert backend._use_kwin_only is True
    assert backend.last_capture_path == "kwin-dbus"


def test_nvidia_x_tiled_pixel_offset_and_zone_read() -> None:
    from nanoleaf_sync.capture._drm_helper_bridge import is_nvidia_x_tiled_modifier
    from nanoleaf_sync.capture._drm_zone_sampler import (
        _FOURCC_XB24,
        DRMZoneSampler,
        _nvidia_x_tiled_pixel_offset,
    )

    modifier = (0x03 << 56) | 0x10
    assert is_nvidia_x_tiled_modifier(modifier) is True
    assert is_nvidia_x_tiled_modifier(0) is False

    width = 1920
    height = 1080
    tilex = 16
    tiley = 128
    tiles_x = width // tilex
    tiles_y = height // tiley
    buf_len = tiles_x * tiles_y * tilex * tiley * 4
    frame = bytearray(buf_len)

    def _set_pixel(px: int, py: int, r: int, g: int, b: int) -> None:
        offset = _nvidia_x_tiled_pixel_offset(px, py, width)
        frame[offset : offset + 4] = bytes((r, g, b, 255))

    for py in range(254, 259):
        for px in range(30, 35):
            _set_pixel(px, py, 200, 100, 50)

    sampler = object.__new__(DRMZoneSampler)
    sampler._is_10bit = False
    sampler._is_fp16 = False
    sampler._rgb_order = True
    sampler._r_byte, sampler._g_byte, sampler._b_byte = 0, 1, 2
    sampler._width = width
    sampler._height = height
    sampler._pitch_bytes = width * 4
    sampler._fourcc = _FOURCC_XB24
    sampler._nvidia_x_tiled = True
    sampler._remount_count = 0
    sampler._crtc_id = 1
    sampler._fb_id = 1
    sampler._fd = -1
    sampler._dma_buf_fd = -1
    sampler._libc = None
    sampler._ensure_framebuffer_current = lambda: None  # type: ignore[method-assign]

    buf_type = ctypes.c_uint8 * len(frame)
    buf = buf_type.from_buffer_copy(bytes(frame))
    sampler._mapped_ptr = ctypes.addressof(buf)

    out = DRMZoneSampler.capture_zone_patches(sampler, [(32, 256)])
    assert isinstance(out, np.ndarray)
    assert out.shape == (1, 3)
    assert out.dtype == np.uint8
    assert tuple(int(v) for v in out[0]) == (200, 100, 50)


def test_drm_zone_sampler_decodes_10bit_xb30_pixel() -> None:
    from nanoleaf_sync.capture._drm_zone_sampler import (
        _FOURCC_XB30,
        DRMZoneSampler,
        _decode_10bit_pixel,
    )

    word = (150 << 20) | (300 << 10) | 640
    r10, g10, b10 = _decode_10bit_pixel(word, rgb_order=True)
    assert (r10, g10, b10) == (640, 300, 150)

    sampler = object.__new__(DRMZoneSampler)
    sampler._is_10bit = True
    sampler._is_fp16 = False
    sampler._rgb_order = True
    sampler._width = 4
    sampler._height = 4
    sampler._pitch_bytes = 16
    sampler._fourcc = _FOURCC_XB30
    sampler._mapped_ptr = 0
    sampler._remount_count = 0
    sampler._crtc_id = 1
    sampler._fb_id = 1
    sampler._fd = -1
    sampler._dma_buf_fd = -1
    sampler._libc = None
    sampler._ensure_framebuffer_current = lambda: None  # type: ignore[method-assign]

    pixel_bytes = word.to_bytes(4, "little")
    row = pixel_bytes * 4
    frame = row * 4
    buf_type = ctypes.c_uint8 * len(frame)
    buf = buf_type.from_buffer_copy(frame)
    sampler._mapped_ptr = ctypes.addressof(buf)

    out = DRMZoneSampler.capture_zone_patches(sampler, [(0, 0)])
    assert isinstance(out, tuple)
    rgb, metadata = out
    assert metadata["bit_depth"] == 10
    assert metadata["transfer"] == "gamma22"
    assert metadata["primaries"] == "bt2020"
    assert rgb.shape == (1, 3)
    assert rgb.dtype == np.float32
    assert np.allclose(rgb[0], np.array([640, 300, 150], dtype=np.float32) / 1023.0, atol=1e-5)


def test_kmsgrab_converts_drm_10bit_zone_rects(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = KMSGrabCapture(width=4, height=4, drm_zone_patch_capture=True)
    zones = np.array([[0.5, 0.25, 0.1]], dtype=np.float32)
    metadata = {
        "fourcc": 0x30334258,
        "bit_depth": 10,
        "primaries": "bt2020",
        "transfer": "gamma22",
        "source": "backend metadata",
    }

    class _FakeSampler:
        is_10bit = True

        def capture_zone_rects(self, _rects):
            return zones, metadata

        def capture_metadata(self):
            return metadata

    backend._drm_zone_sampler = _FakeSampler()
    converted = np.array([[120, 60, 20]], dtype=np.uint8)
    calls: list[dict[str, object]] = []

    def _fake_convert(frame: np.ndarray, metadata):
        calls.append(dict(metadata))
        return converted

    monkeypatch.setattr("nanoleaf_sync.capture.kmsgrab.convert_frame_to_srgb8", _fake_convert)
    out = backend.capture(zone_rects=[(0, 0, 2, 2)])
    assert out.shape == (1, 3)
    assert out.dtype == np.uint8
    assert np.array_equal(out, converted)
    assert calls
    assert calls[0]["transfer"] == "gamma22"
    assert calls[0]["primaries"] == "bt2020"
    assert backend.last_hdr_diagnostics.get("display_referred") is True
