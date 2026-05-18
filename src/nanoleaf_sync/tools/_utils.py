"""Shared utility functions for the tools subpackage."""

from __future__ import annotations


def effective_runtime_zone_count(
    *, configured: int, detected: int | None
) -> int | None:
    """Return the effective runtime zone count preferring the configured value."""
    configured_count = int(configured or 0)
    if configured_count > 0:
        return configured_count
    detected_count = int(detected or 0)
    if detected_count > 0:
        return detected_count
    return None
