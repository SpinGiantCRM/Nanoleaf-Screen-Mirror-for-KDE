from __future__ import annotations

from importlib import import_module
from functools import lru_cache
import logging
import os
from pathlib import Path
import threading

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
_cached_probe_winner: str | None = None
_cached_probe_winner_lock = threading.Lock()




def reset_cached_probe_winner() -> None:
    global _cached_probe_winner

    with _cached_probe_winner_lock:
        _cached_probe_winner = None


def reset_capability_check_cache() -> None:
    _has_drm_device.cache_clear()
    _kmsgrab_bindings_available.cache_clear()


@lru_cache(maxsize=1)
def _has_drm_device() -> bool:
    card_path = os.environ.get("NANOLEAF_DRM_CARD", "/dev/dri/card0")
    return Path(card_path).exists()


@lru_cache(maxsize=1)
def _kmsgrab_bindings_available() -> bool:
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
        logger.info(
            "capture auto-probe skipped; using capability fallback=%s reason=%s",
            fallback,
            disable_reason,
        )
        return fallback

    with _cached_probe_winner_lock:
        cached = cached_probe_winner or _cached_probe_winner
        if is_valid_probe_candidate(cached):
            logger.info("capture auto-probe using cached winner=%s", cached)
            return str(cached)

        candidates = list(AUTO_PROBE_CANDIDATES)
        logger.info("capture auto-probe candidates=%s", ", ".join(candidates))

        try:
            from nanoleaf_sync.capture.auto_probe import ProbeConfig, probe_backends

            result = probe_backends(width, height, candidates, ProbeConfig())
            tested = ", ".join(item.candidate for item in result.candidates)
            logger.info("capture auto-probe tested candidates=%s", tested)

            if result.selected_backend is not None:
                _cached_probe_winner = result.selected_backend
                logger.info("capture auto-probe selected winner=%s", result.selected_backend)
                return result.selected_backend

            logger.warning(
                "capture auto-probe yielded no qualified backend; using capability fallback=%s",
                fallback,
            )
        except Exception as exc:  # noqa: BLE001 - preserve startup reliability
            logger.warning(
                "capture auto-probe failed; using capability fallback=%s reason=%s",
                fallback,
                exc,
            )

        return fallback


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
