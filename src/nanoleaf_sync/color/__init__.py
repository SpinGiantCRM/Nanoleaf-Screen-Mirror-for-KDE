"""Public color package surface.

This package re-exports stable color conversion and mapping helpers.
Use :mod:`nanoleaf_sync.runtime.zones` for frame/zone averaging helpers.
"""

from nanoleaf_sync.color.hdr import HDRMetadata, convert_frame_to_srgb8
from nanoleaf_sync.color.zone_mapper import map_colors_to_device_zones

RGBTuple = tuple[int, int, int]

__all__ = [
    "HDRMetadata",
    "RGBTuple",
    "convert_frame_to_srgb8",
    "map_colors_to_device_zones",
]
