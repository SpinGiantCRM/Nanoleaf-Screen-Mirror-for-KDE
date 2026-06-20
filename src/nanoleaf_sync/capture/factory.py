from __future__ import annotations

import logging
import os
import statistics
import threading
import time
from collections.abc import Callable
from importlib import import_module
from pathlib import Path

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
from nanoleaf_sync.compat.kwin_probe import log_kwin_probe_results
from nanoleaf_sync.compat.portal_probe import log_portal_probe_results

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
_explicit_portal_probe_lock = threading.Lock()
_portal_benchmark_lock = threading.Lock()


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


def _probe_row(
    *,
    backend: str,
    status: str,
    reason: str,
    selected: bool,
    mode: str,
    sample_count: int = 0,
    median_ms: float | None = None,
    p95_ms: float | None = None,
    jitter_ms: float | None = None,
    score: float | None = None,
    selected_reason: str = "",
    tentative: bool = False,
) -> dict[str, object]:
    return {
        "backend": backend,
        "status": status,
        "reason": reason,
        "mode": mode,
        "sample_count": sample_count,
        "median_ms": median_ms,
        "p95_ms": p95_ms,
        "jitter_ms": jitter_ms,
        "score": score,
        "selected_reason": selected_reason,
        "selected": selected,
        "tentative": tentative,
    }


def _probe_rows_from_result(*, result, mode: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for candidate in result.candidates:
        latencies = list(getattr(candidate, "latencies_ms", []) or [])
        status = str(
            getattr(
                candidate,
                "status",
                "tested" if latencies else ("failed" if candidate.errors else "skipped"),
            )
        )
        row_mode = mode
        if status == "skipped" and candidate.candidate == XDG_PORTAL_BACKEND:
            row_mode = "skipped-interactive"
        elif status == "failed":
            row_mode = "failed"
        rows.append(
            _probe_row(
                backend=candidate.candidate,
                status=status,
                reason=str(
                    getattr(candidate, "reason", "")
                    or (
                        "; ".join(error.message for error in candidate.errors)
                        if candidate.errors
                        else ""
                    )
                ),
                sample_count=len(latencies),
                median_ms=candidate.median_ms,
                p95_ms=candidate.p95_ms,
                jitter_ms=candidate.jitter_ms,
                score=candidate.score,
                selected_reason=str(getattr(candidate, "reason", "") or ""),
                selected=(candidate.candidate == result.selected_backend),
                tentative=bool(getattr(candidate, "tentative", False)),
                mode=row_mode,
            )
        )
    return rows


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


def has_drm_device() -> bool:
    """Public alias for capability check: whether a DRM device is present."""
    return _has_drm_device()


def kmsgrab_bindings_available() -> bool:
    """Public alias for capability check: whether kmsgrab bindings are available."""
    return _kmsgrab_bindings_available()


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
            module = import_module("kmsgrab")
            return callable(getattr(module, "capture", None))
        except ImportError:
            return False

    return _capability_cache_get_or_refresh("kmsgrab_bindings_available", _resolve)


def _resolve_auto_backend() -> str:
    if _has_drm_device() and _kmsgrab_bindings_available():
        return "kmsgrab"
    return "kwin-dbus"


def cached_probe_winner_is_viable(value: str | None) -> bool:
    if not is_valid_probe_candidate(value):
        return False
    if value == KMSGRAB_BACKEND:
        return _has_drm_device() and _kmsgrab_bindings_available()
    return True


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
                _probe_row(
                    backend=candidate,
                    status="skipped",
                    reason=f"Auto-probe disabled: {disable_reason}",
                    selected=(candidate == fallback),
                    mode="unavailable",
                )
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
    if is_valid_probe_candidate(cached) and cached_probe_winner_is_viable(cached):
        _set_last_auto_probe_report(
            [
                _probe_row(
                    backend=candidate,
                    status="skipped",
                    reason=f"Using cached winner '{cached}'",
                    selected=(candidate == cached),
                    mode="cached",
                )
                for candidate in AUTO_PROBE_CANDIDATES
            ]
        )
        logger.info("capture auto-probe using cached winner=%s", cached)
        return str(cached)
    if is_valid_probe_candidate(cached):
        logger.warning(
            "capture auto-probe cached winner=%s is no longer viable; re-probing",
            cached,
        )

    candidates = list(AUTO_PROBE_CANDIDATES)
    logger.info("capture auto-probe candidates=%s", ", ".join(candidates))

    try:
        from nanoleaf_sync.capture.auto_probe import ProbeConfig, probe_backends

        result = probe_backends(width, height, candidates, ProbeConfig())
        probe_rows = _probe_rows_from_result(result=result, mode="fresh-probe")
        _set_last_auto_probe_report(probe_rows)
        tested = ", ".join(item.candidate for item in result.candidates)
        logger.info("capture auto-probe tested candidates=%s", tested)

        if result.selected_backend is not None:
            winner = str(result.selected_backend)
            if not cached_probe_winner_is_viable(winner):
                logger.warning(
                    "capture auto-probe selected winner=%s is not viable; "
                    "using capability fallback=%s",
                    winner,
                    fallback,
                )
                return fallback
            with _cached_probe_winner_lock:
                current_cached = _cached_probe_winner
                if is_valid_probe_candidate(current_cached) and cached_probe_winner_is_viable(
                    current_cached
                ):
                    logger.info(
                        "capture auto-probe cache updated by peer; winner=%s", current_cached
                    )
                    return str(current_cached)
                _cached_probe_winner = winner
            logger.info("capture auto-probe selected winner=%s", winner)
            return winner

        logger.warning(
            "capture auto-probe yielded no qualified backend; using capability fallback=%s",
            fallback,
        )
    except Exception as exc:  # noqa: BLE001 - preserve startup reliability
        _set_last_auto_probe_report(
            [
                _probe_row(
                    backend=candidate,
                    status="failed",
                    reason=f"Auto-probe failed: {exc}",
                    selected=(candidate == fallback),
                    mode="failed",
                )
                for candidate in AUTO_PROBE_CANDIDATES
            ]
        )
        logger.warning(
            "capture auto-probe failed; using capability fallback=%s reason=%s",
            fallback,
            exc,
        )

    return fallback


def run_fresh_backend_probe(*, width: int, height: int) -> dict[str, object]:
    from nanoleaf_sync.capture.auto_probe import ProbeConfig, probe_backends

    result = probe_backends(
        width,
        height,
        list(AUTO_PROBE_CANDIDATES),
        ProbeConfig(allow_interactive=False),
    )
    rows = _probe_rows_from_result(result=result, mode="fresh-probe")
    _set_last_auto_probe_report(rows)
    return {
        "selected_backend": result.selected_backend,
        "timed_out": bool(result.timed_out),
        "attempts": rows,
    }


def run_explicit_xdg_portal_probe(*, width: int, height: int) -> dict[str, object]:
    if not _explicit_portal_probe_lock.acquire(blocking=False):
        return {
            "selected_backend": None,
            "status": "failed",
            "mode": "explicit-test",
            "reason": "A Test xdg-portal operation is already in progress.",
            "sample_count": 0,
            "median_ms": None,
            "p95_ms": None,
            "jitter_ms": None,
            "score": None,
            "timed_out": False,
            "stages": [],
        }
    try:
        probe = XDGPortalCapture(width=width, height=height)
        return probe.run_explicit_diagnostic()
    finally:
        _explicit_portal_probe_lock.release()


def _benchmark_backend(
    *, backend_name: str, width: int, height: int, samples: int
) -> dict[str, object]:
    backend = create_capture_backend(
        width=width,
        height=height,
        use_mock_capture=False,
        prefer_backend=backend_name,
    )
    capture_ms: list[float] = []
    empty_buffers = 0
    frame_bytes = 0
    actual_size = "unknown"
    fmt = "unknown"
    stride = None
    started = time.monotonic()
    try:
        for _ in range(max(1, samples)):
            call_start = time.monotonic()
            try:
                frame = backend.capture()
            except Exception:
                logger.debug("Capture benchmark attempt failed", exc_info=True)
                continue
            capture_ms.append((time.monotonic() - call_start) * 1000.0)
            if frame.size <= 0 or frame.nbytes <= 0:
                empty_buffers += 1
            frame_bytes = int(frame.nbytes)
            if frame.ndim == 3:
                actual_size = f"{frame.shape[1]}x{frame.shape[0]}"
                fmt = "RGB"
                stride = int(frame.strides[0]) if frame.strides else None
    finally:
        close_fn = getattr(backend, "close", None)
        if callable(close_fn):
            close_fn()

    elapsed_s = max(0.0001, time.monotonic() - started)
    return {
        "backend": backend_name,
        "target_capture_size": f"{width}x{height}",
        "actual_frame_size": actual_size,
        "format": fmt,
        "frame_bytes": frame_bytes,
        "stride": stride,
        "median_capture_ms": float(statistics.median(capture_ms)) if capture_ms else 0.0,
        "p95_capture_ms": float(
            sorted(capture_ms)[
                max(0, min(len(capture_ms) - 1, int(round((len(capture_ms) - 1) * 0.95))))
            ]
        )
        if capture_ms
        else 0.0,
        "jitter_ms": float(max(capture_ms) - min(capture_ms)) if len(capture_ms) > 1 else 0.0,
        "effective_fps": len(capture_ms) / elapsed_s,
        "empty_buffers": empty_buffers,
        "sample_count": len(capture_ms),
    }


def run_manual_portal_benchmark(*, width: int, height: int, samples: int = 30) -> dict[str, object]:
    if not _portal_benchmark_lock.acquire(blocking=False):
        return {
            "status": "failed",
            "mode": "manual-benchmark",
            "reason": "A Benchmark xdg-portal operation is already in progress.",
        }
    try:
        portal_test = run_explicit_xdg_portal_probe(width=width, height=height)
        if str(portal_test.get("status")) != "tested":
            return {
                "status": "failed",
                "mode": "manual-benchmark",
                "reason": portal_test.get("reason")
                or "Portal stream negotiated, but no CPU-readable frame was received.",
                "portal_test": portal_test,
            }

        portal_stats = _benchmark_backend(
            backend_name=XDG_PORTAL_BACKEND,
            width=width,
            height=height,
            samples=samples,
        )
        kwin_stats = _benchmark_backend(
            backend_name=KWIN_DBUS_BACKEND,
            width=width,
            height=height,
            samples=samples,
        )
        portal_better = (
            float(portal_stats["p95_capture_ms"]) <= float(kwin_stats["p95_capture_ms"])  # type: ignore[arg-type]
            and float(portal_stats["jitter_ms"]) <= float(kwin_stats["jitter_ms"])  # type: ignore[arg-type]
            and int(portal_stats["empty_buffers"]) == 0  # type: ignore[call-overload]
            and int(portal_stats["sample_count"]) >= max(10, samples // 2)  # type: ignore[call-overload]
        )
        return {
            "status": "tested",
            "mode": "manual-benchmark",
            "selected_backend": KWIN_DBUS_BACKEND,
            "reason": "Manual xdg-portal benchmark completed.",
            "recommendation": (
                "candidate default (manual benchmark only; not auto-selected)"
                if portal_better
                else "working fallback, not recommended"
            ),
            "portal_requires_prompt_each_launch": None,
            "results": [portal_stats, kwin_stats],
            "portal_test": portal_test,
        }
    finally:
        _portal_benchmark_lock.release()


def _log_compat_probe_results(*, prefer_backend: str) -> None:
    normalized = normalize_backend_preference(prefer_backend)
    if normalized in {AUTO_BACKEND, KWIN_DBUS_BACKEND, KMSGRAB_BACKEND}:
        log_kwin_probe_results()
    if normalized in {AUTO_BACKEND, XDG_PORTAL_BACKEND}:
        log_portal_probe_results()


def _resolve_prefer_backend(
    *,
    prefer_backend: str,
    width: int,
    height: int,
    auto_probe_enabled: bool | None,
    cached_probe_winner: str | None,
) -> str:
    _log_compat_probe_results(prefer_backend=prefer_backend)
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
    drm_zone_patch_capture: bool = False,
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
                drm_zone_patch_capture=drm_zone_patch_capture,
            )
        except Exception as exc:  # noqa: BLE001
            raise CaptureBackendInitializationError(KMSGRAB_BACKEND, str(exc)) from exc

    raise AssertionError(
        "Invariant violation: _resolve_prefer_backend returned unsupported backend "
        f"{normalized!r}; expected one of "
        f"{KWIN_DBUS_BACKEND!r}, {XDG_PORTAL_BACKEND!r}, or {KMSGRAB_BACKEND!r}."
    )
