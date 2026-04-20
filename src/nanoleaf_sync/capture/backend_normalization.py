from __future__ import annotations


def normalize_capture_backend(value: str | None, *, default: str = "auto") -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"", "auto"}:
        return "auto"
    if normalized in {"kwin-dbus", "kwin_dbus", "kwin-dbus-screenshot"}:
        return "kwin-dbus"
    if normalized in {"xdg-portal", "xdg_portal", "portal"}:
        return "xdg-portal"
    if normalized in {"kmsgrab", "kms-grab", "drm-kms", "drm_kms"}:
        return "kmsgrab"
    return default
