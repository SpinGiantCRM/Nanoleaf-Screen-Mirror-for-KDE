import builtins

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
