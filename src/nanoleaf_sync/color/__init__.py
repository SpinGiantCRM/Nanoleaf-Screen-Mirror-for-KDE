from nanoleaf_sync.tools.color_kmeans import dominant_colors_kmeans
from nanoleaf_sync.color.hdr import HDRMetadata, convert_frame_to_srgb8
from nanoleaf_sync.color.zone_mapper import map_colors_to_device_zones


def average_color(*args, **kwargs):
    from nanoleaf_sync.runtime.zones import average_color as _average_color

    return _average_color(*args, **kwargs)


def zone_colors(*args, **kwargs):
    from nanoleaf_sync.runtime.zones import zone_colors as _zone_colors

    return _zone_colors(*args, **kwargs)


__all__ = [
    "average_color",
    "dominant_colors_kmeans",
    "zone_colors",
    "HDRMetadata",
    "convert_frame_to_srgb8",
    "map_colors_to_device_zones",
]
