from __future__ import annotations

from nanoleaf_sync.capture.drm_vendor import (
    modifier_layout,
    nvidia_x_tiled_pixel_offset,
    pixel_byte_offset,
    resolve_drm_primaries_label,
    scanout_metadata_for_fourcc,
    vendor_validation_tier,
)

_FOURCC_NV_AB4H = 0x48344241
_FOURCC_AR30 = 0x30335241
_FOURCC_XR24 = 0x34325258


def test_vendor_validation_tier() -> None:
    assert vendor_validation_tier("nvidia") == "validated"
    assert vendor_validation_tier("amd") == "unvalidated"
    assert vendor_validation_tier("intel") == "unvalidated"


def test_modifier_layout_linear_and_nvidia() -> None:
    assert modifier_layout(0, vendor="amd") == "linear"
    nvidia_mod = (0x03 << 56) | 123
    assert modifier_layout(nvidia_mod, vendor="nvidia") == "nvidia_x_tiled"


def test_pixel_byte_offset_linear_matches_pitch() -> None:
    offset = pixel_byte_offset(
        px=3,
        py=2,
        pitch_bytes=64,
        bpp=4,
        frame_width=1920,
        modifier=0,
        vendor="intel",
    )
    assert offset == 2 * 64 + 3 * 4


def test_scanout_metadata_fp16_nvidia() -> None:
    meta = scanout_metadata_for_fourcc(_FOURCC_NV_AB4H, vendor="nvidia")
    assert meta["bit_depth"] == 16
    assert meta["display_referred"] is True
    assert meta["validation_tier"] == "validated"


def test_scanout_metadata_10bit_amd_intel() -> None:
    for vendor in ("amd", "intel"):
        meta = scanout_metadata_for_fourcc(_FOURCC_AR30, vendor=vendor)
        assert meta["bit_depth"] == 10
        assert meta["transfer"] == "gamma22"
        assert meta["validation_tier"] == "unvalidated"


def test_scanout_metadata_8bit_sdr() -> None:
    meta = scanout_metadata_for_fourcc(_FOURCC_XR24, vendor="intel")
    assert meta["bit_depth"] == 8
    assert meta["transfer"] == "srgb"


def test_nvidia_x_tiled_offset_monotonic() -> None:
    a = nvidia_x_tiled_pixel_offset(0, 0, 1920, bpp=4)
    b = nvidia_x_tiled_pixel_offset(1, 0, 1920, bpp=4)
    assert b > a


def test_connector_drm_name_and_monitor_match() -> None:
    from nanoleaf_sync.capture.drm_vendor import (
        connector_drm_name,
        connector_matches_capture_monitor,
    )

    assert connector_drm_name(connector_type=11, connector_type_id=1) == "HDMI-A-1"
    assert connector_matches_capture_monitor(
        connector_type=11,
        connector_type_id=1,
        capture_monitor="HDMI-A-1",
    )
    assert not connector_matches_capture_monitor(
        connector_type=10,
        connector_type_id=2,
        capture_monitor="HDMI-A-1",
    )
    assert connector_matches_capture_monitor(
        connector_type=11,
        connector_type_id=1,
        capture_monitor="",
    )


def test_resolve_drm_primaries_label_default() -> None:

    label = resolve_drm_primaries_label()
    assert label in {"bt709", "bt2020"}
