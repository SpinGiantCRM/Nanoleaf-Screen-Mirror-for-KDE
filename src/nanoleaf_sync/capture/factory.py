from __future__ import annotations

from importlib import import_module
import logging
import os
from pathlib import Path
import threading
import time
from typing import Callable

from nanoleaf_sync.capture.backend_selection import (
    AUTO_BACKEND,
    AUTO_PROBE_CANDIDATES,
    KMSGRAB_BACKEND,
    KWIN_DBUS_BACKEND,
    XDG_PORTAL_BACKEND,
    is_valid_probe_candidate,
    normalize_backend_preference,
)
from nanoleaf_sync.capture.errors import CaptureBackendInitializationError
from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.capture.kmsgrab import KMSGrabCapture
from nanoleaf_sync.capture.kwin_dbus import KWinDBusScreenshotCapture
from nanoleaf_sync.capture.mock_capture import MockScreenCapture
from nanoleaf_sync.capture.xdg_portal import XDGPortalCapture

logger = logging.getLogger(__name__)

_AUTO_PROBE_DISABLED_ENV = "NANOLEAF_DISABLE_CAPTURE_PROBE"
_AUTO_PROBE_ENABLE_ENV = "NANOLEAF_ENABLE_CAPTURE_PROBE"
_CAPABILITY_CACHE_TTL_SECONDS = 10.0
_cached_probe_winner: str | None = None
_cached_probe_winner_lock = threading.Lock()
_capability_cache_lock = threading.Lock()
_capability_cache: dict[str, tuple[float, bool]] = {}
_last_auto_probe_report_lock = threading.Lock()
_last_auto_probe_report: list[dict[str, object]] = []




def reset_cached_probe_winner() -> None:
    global _cached_probe_winner

    with _cached_probe_winner_lock:
        _cached_probe_winner = None


def reset_capability_check_cache() -> None:
    with _capability_cache_lock:
        _capability_cache.clear()


def last_auto_probe_report() -> list[dict[str, object]]:
    with _last_auto_probe_report_lock:
        return [dict(row) for row in _last_auto_probe_report]


def _set_last_auto_probe_report(entries: list[dict[str, object]]) -> None:
    with _last_auto_probe_report_lock:
        _last_auto_probe_report.clear()
        _last_auto_probe_report.extend(dict(item) for item in entries)


def _capability_cache_get_or_refresh(
    key: str,
    resolver: Callable[[], bool],
) -> bool:
    now = time.monotonic()
    with _capability_cache_lock:
        cached = _capability_cache.get(key)
        if cached is not None:
            cached_at, value = cached
            if (now - cached_at) < _CAPABILITY_CACHE_TTL_SECONDS:
                return value

    resolved = bool(resolver())
    with _capability_cache_lock:
        _capability_cache[key] = (time.monotonic(), resolved)
    return resolved


def _has_drm_device() -> bool:
    card_path = os.environ.get("NANOLEAF_DRM_CARD", "/dev/dri/card0")
    return _capability_cache_get_or_refresh("has_drm_device", lambda: Path(card_path).exists())


def _kmsgrab_bindings_available() -> bool:
    def _resolve() -> bool:
        try:
            module = import_module("nanoleaf_sync.capture._kmsgrab")
            if callable(getattr(module, "capture_dma_buf_rgb", None)):
                return True
        except ImportError:
            pass

        try:
            module = import_module("kmsgrab")  # type: ignore
            return callable(getattr(module, "capture", None))
        except ImportError:
            return False

    return _capability_cache_get_or_refresh("kmsgrab_bindings_available", _resolve)


def _resolve_auto_backend() -> str:
    if _has_drm_device() and _kmsgrab_bindings_available():
        return "kmsgrab"
    return "kwin-dbus"


def _env_bool(var_name: str) -> bool | None:
    raw = os.environ.get(var_name)
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return None


def _probe_enabled(config_probe_enabled: bool | None) -> tuple[bool, str | None]:
    env_disabled = _env_bool(_AUTO_PROBE_DISABLED_ENV)
    if env_disabled is True:
        return False, f"{_AUTO_PROBE_DISABLED_ENV}=true"

    env_enabled = _env_bool(_AUTO_PROBE_ENABLE_ENV)
    if env_enabled is False:
        return False, f"{_AUTO_PROBE_ENABLE_ENV}=false"

    if config_probe_enabled is False:
        return False, "config auto_probe_enabled=false"

    return True, None


def auto_probe_effective_state(config_probe_enabled: bool | None) -> tuple[bool, str]:
    enabled, disable_reason = _probe_enabled(config_probe_enabled)
    return enabled, (disable_reason or "enabled")


def _resolve_auto_backend_with_probe(
    *,
    width: int,
    height: int,
    auto_probe_enabled: bool | None,
    cached_probe_winner: str | None,
) -> str:
    global _cached_probe_winner

    fallback = _resolve_auto_backend()
    enabled, disable_reason = _probe_enabled(auto_probe_enabled)
    if not enabled:
        _set_last_auto_probe_report(
            [
                {
                    "backend": candidate,
                    "status": "skipped",
                    "reason": f"Auto-probe disabled: {disable_reason}",
                    "sample_count": 0,
                    "median_ms": None,
                    "p95_ms": None,
                    "jitter_ms": None,
                    "score": None,
                    "selected_reason": "",
                    "selected": candidate == fallback,
                }
                for candidate in AUTO_PROBE_CANDIDATES
            ]
        )
        logger.info(
            "capture auto-probe skipped; using capability fallback=%s reason=%s",
            fallback,
            disable_reason,
        )
        return fallback

    with _cached_probe_winner_lock:
        cached = cached_probe_winner or _cached_probe_winner
    if is_valid_probe_candidate(cached):
        _set_last_auto_probe_report(
            [
                {
                    "backend": candidate,
                    "status": "skipped",
                    "reason": f"Using cached winner '{cached}'",
                    "sample_count": 0,
                    "median_ms": None,
                    "p95_ms": None,
                    "jitter_ms": None,
                    "score": None,
                    "selected_reason": "",
                    "selected": candidate == cached,
                }
                for candidate in AUTO_PROBE_CANDIDATES
            ]
        )
        logger.info("capture auto-probe using cached winner=%s", cached)
        return str(cached)

    candidates = list(AUTO_PROBE_CANDIDATES)
    logger.info("capture auto-probe candidates=%s", ", ".join(candidates))

    try:
        from nanoleaf_sync.capture.auto_probe import ProbeConfig, probe_backends

        result = probe_backends(width, height, candidates, ProbeConfig())
        probe_rows: list[dict[str, object]] = []
        for candidate in result.candidates:
            latencies = list(getattr(candidate, "latencies_ms", []) or [])
            probe_rows.append(
                {
                    "backend": candidate.candidate,
                    "status": str(getattr(candidate, "status", "tested" if latencies else ("failed" if candidate.errors else "skipped"))),
                    "reason": str(getattr(candidate, "reason", "") or ("; ".join(error.message for error in candidate.errors) if candidate.errors else "")),
                    "sample_count": len(latencies),
                    "median_ms": candidate.median_ms,
                    "p95_ms": candidate.p95_ms,
                    "jitter_ms": candidate.jitter_ms,
                    "score": candidate.score,
                    "selected_reason": candidate.reason,
                    "selected": candidate.candidate == result.selected_backend,
                }
            )
        _set_last_auto_probe_report(probe_rows)
        tested = ", ".join(item.candidate for item in result.candidates)
        logger.info("capture auto-probe tested candidates=%s", tested)

        if result.selected_backend is not None:
            with _cached_probe_winner_lock:
                current_cached = _cached_probe_winner
                if is_valid_probe_candidate(current_cached):
                    logger.info("capture auto-probe cache updated by peer; winner=%s", current_cached)
                    return str(current_cached)
                _cached_probe_winner = result.selected_backend
            logger.info("capture auto-probe selected winner=%s", result.selected_backend)
            return result.selected_backend

        logger.warning(
            "capture auto-probe yielded no qualified backend; using capability fallback=%s",
            fallback,
        )
    except Exception as exc:  # noqa: BLE001 - preserve startup reliability
        _set_last_auto_probe_report(
            [
                {
                    "backend": candidate,
                    "status": "failed",
                    "reason": f"Auto-probe failed: {exc}",
                    "sample_count": 0,
                    "median_ms": None,
                    "p95_ms": None,
                    "jitter_ms": None,
                    "score": None,
                    "selected_reason": "",
                    "selected": candidate == fallback,
                }
                for candidate in AUTO_PROBE_CANDIDATES
            ]
        )
        logger.warning(
            "capture auto-probe failed; using capability fallback=%s reason=%s",
            fallback,
            exc,
        )

    return fallback


def run_explicit_xdg_portal_probe(*, width: int, height: int) -> dict[str, object]:
    from nanoleaf_sync.capture.auto_probe import ProbeConfig, probe_backends

    result = probe_backends(
        width,
        height,
        [XDG_PORTAL_BACKEND],
        ProbeConfig(
            allow_interactive=True,
            quick_probe=True,
            measure_iterations=20,
            global_timeout_s=45.0,
            instantiate_timeout_s=45.0,
            warmup_timeout_s=20.0,
            capture_timeout_s=10.0,
        ),
    )
    row = result.candidates[0] if result.candidates else None
    return {
        "selected_backend": result.selected_backend,
        "status": getattr(row, "status", "failed") if row else "failed",
        "reason": getattr(row, "reason", "No result") if row else "No result",
        "sample_count": len(getattr(row, "latencies_ms", []) or []),
        "median_ms": getattr(row, "median_ms", None),
        "p95_ms": getattr(row, "p95_ms", None),
        "jitter_ms": getattr(row, "jitter_ms", None),
        "score": getattr(row, "score", None),
        "timed_out": bool(result.timed_out),
    }


def _resolve_prefer_backend(
    *,
    prefer_backend: str,
    width: int,
    height: int,
    auto_probe_enabled: bool | None,
    cached_probe_winner: str | None,
) -> str:
    normalized = normalize_backend_preference(prefer_backend)
    if normalized == AUTO_BACKEND:
        return _resolve_auto_backend_with_probe(
            width=width,
            height=height,
            auto_probe_enabled=auto_probe_enabled,
            cached_probe_winner=cached_probe_winner,
        )
    logger.info("capture backend explicitly configured=%s; probe bypassed", normalized)
    return normalized


def create_capture_backend(
    *,
    width: int,
    height: int,
    use_mock_capture: bool,
    prefer_backend: str,
    hdr_max_nits: float = 1000.0,
    hdr_transfer: str = "srgb",
    hdr_primaries: str = "bt709",
    auto_probe_enabled: bool | None = None,
    cached_probe_winner: str | None = None,
) -> CaptureBackend:
    """Create capture backend for the runtime.

    Supports mock capture plus compositor-backed capture via KWin D-Bus or
    XDG desktop portal (ScreenCast + PipeWire).
    """

    if use_mock_capture:
        return MockScreenCapture(width=width, height=height)

    normalized = _resolve_prefer_backend(
        prefer_backend=prefer_backend,
        width=width,
        height=height,
        auto_probe_enabled=auto_probe_enabled,
        cached_probe_winner=cached_probe_winner,
    )
    if normalized == KWIN_DBUS_BACKEND:
        try:
            return KWinDBusScreenshotCapture(
                width=width,
                height=height,
                hdr_max_nits=hdr_max_nits,
                hdr_transfer=hdr_transfer,
                hdr_primaries=hdr_primaries,
            )
        except Exception as exc:  # noqa: BLE001
            raise CaptureBackendInitializationError(KWIN_DBUS_BACKEND, str(exc)) from exc

    if normalized == XDG_PORTAL_BACKEND:
        try:
            return XDGPortalCapture(width=width, height=height)
        except Exception as exc:  # noqa: BLE001
            raise CaptureBackendInitializationError(XDG_PORTAL_BACKEND, str(exc)) from exc

    if normalized == KMSGRAB_BACKEND:
        try:
            return KMSGrabCapture(
                width=width,
                height=height,
                hdr_max_nits=hdr_max_nits,
                hdr_transfer=hdr_transfer,
                hdr_primaries=hdr_primaries,
            )
        except Exception as exc:  # noqa: BLE001
            raise CaptureBackendInitializationError(KMSGRAB_BACKEND, str(exc)) from exc

    raise AssertionError(
        "Invariant violation: _resolve_prefer_backend returned unsupported backend "
        f"{normalized!r}; expected one of "
        f"{KWIN_DBUS_BACKEND!r}, {XDG_PORTAL_BACKEND!r}, or {KMSGRAB_BACKEND!r}."
    )
