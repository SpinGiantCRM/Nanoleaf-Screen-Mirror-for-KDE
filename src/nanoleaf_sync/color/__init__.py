"""Public color package surface.

This package re-exports stable color conversion and mapping helpers.
Use :mod:`nanoleaf_sync.runtime.zones` for frame/zone averaging helpers.
"""

from typing import Any

from nanoleaf_sync.color.hdr import HDRMetadata, convert_frame_to_srgb8
from nanoleaf_sync.color.zone_mapper import map_colors_to_device_zones


def dominant_colors_kmeans(*args: Any, **kwargs: Any) -> list[tuple[int, int, int]]:
    from nanoleaf_sync.tools.color_kmeans import dominant_colors_kmeans as _impl

    return _impl(*args, **kwargs)


__all__ = [
    "dominant_colors_kmeans",
    "HDRMetadata",
    "convert_frame_to_srgb8",
    "map_colors_to_device_zones",
]
