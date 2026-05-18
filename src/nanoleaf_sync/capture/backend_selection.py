from __future__ import annotations

from nanoleaf_sync.capture.backend_normalization import normalize_capture_backend

AUTO_BACKEND = "auto"
KWIN_DBUS_BACKEND = "kwin-dbus"
XDG_PORTAL_BACKEND = "xdg-portal"
KMSGRAB_BACKEND = "kmsgrab"

SUPPORTED_REAL_BACKENDS: tuple[str, ...] = (
    KWIN_DBUS_BACKEND,
    XDG_PORTAL_BACKEND,
    KMSGRAB_BACKEND,
)
AUTO_PROBE_CANDIDATES: tuple[str, ...] = (
    KMSGRAB_BACKEND,
    KWIN_DBUS_BACKEND,
    XDG_PORTAL_BACKEND,
)


def normalize_backend_preference(value: str | None) -> str:
    """Normalize capture backend aliases into a canonical backend label."""
    return normalize_capture_backend(value, default=AUTO_BACKEND)


def normalize_cached_backend(value: str | None) -> str:
    """Normalize persisted backend winner values; invalid entries become empty."""
    normalized = normalize_capture_backend(value, default="")
    return "" if normalized == AUTO_BACKEND else normalized


def is_valid_probe_candidate(value: str | None) -> bool:
    return value in AUTO_PROBE_CANDIDATES
