from __future__ import annotations

import numpy as np

from nanoleaf_sync.capture.drm_vendor import scanout_metadata_for_fourcc
from nanoleaf_sync.color.hdr import convert_frame_to_srgb8

_FOURCC_NV_AB4H = 0x48344241
_FOURCC_AR30 = 0x30335241
_FOURCC_XR24 = 0x34325258


def test_vendor_scanout_metadata_matrix() -> None:
    nvidia = scanout_metadata_for_fourcc(_FOURCC_NV_AB4H, vendor="nvidia")
    amd = scanout_metadata_for_fourcc(_FOURCC_AR30, vendor="amd")
    intel = scanout_metadata_for_fourcc(_FOURCC_AR30, vendor="intel")
    sdr = scanout_metadata_for_fourcc(_FOURCC_XR24, vendor="intel")

    assert nvidia["bit_depth"] == 16
    assert amd["bit_depth"] == 10
    assert intel["bit_depth"] == 10
    assert sdr["bit_depth"] == 8
    assert all(meta["display_referred"] is True for meta in (nvidia, amd, intel, sdr))


def test_fp16_hdr_zone_preserves_headroom_before_output() -> None:
    linear = np.array([[[1.6, 1.6, 1.6]]], dtype=np.float32)
    metadata = {
        "transfer": "linear",
        "primaries": "bt709",
        "max_nits": 1000.0,
        "source": "backend metadata",
    }
    out = convert_frame_to_srgb8(linear, metadata)
    assert out.dtype == np.uint8
    assert int(out[0, 0, 0]) > 200
