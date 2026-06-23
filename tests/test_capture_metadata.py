from __future__ import annotations

from nanoleaf_sync.color.capture_metadata import (
    invalidate_plasma_hdr_cache,
    resolve_capture_metadata,
)


def test_plasma_hdr_cache_invalidation_clears_cached_state() -> None:
    from nanoleaf_sync.color.capture_metadata import _plasma_hdr_enabled

    _plasma_hdr_enabled()
    invalidate_plasma_hdr_cache()
    assert _plasma_hdr_enabled.cache_info().currsize == 0


def test_plasma_hdr_cache_invalidation_mid_session() -> None:
    from nanoleaf_sync.color.capture_metadata import _plasma_hdr_enabled

    _plasma_hdr_enabled()
    info_before = _plasma_hdr_enabled.cache_info().currsize
    invalidate_plasma_hdr_cache()
    assert _plasma_hdr_enabled.cache_info().currsize == 0
    _plasma_hdr_enabled()
    assert _plasma_hdr_enabled.cache_info().currsize >= info_before


def test_missing_metadata_defaults_to_display_referred_srgb() -> None:
    meta = resolve_capture_metadata(kwin_display_referred=True)
    assert meta.transfer == "srgb"
    assert meta.primaries == "bt709"
    assert meta.skip_display_gamut_adaptation is True


def test_backend_metadata_preserves_skip_display_gamut_adaptation() -> None:
    meta = resolve_capture_metadata(
        backend_metadata={
            "transfer": "srgb",
            "primaries": "bt709",
            "max_nits": 1000.0,
            "skip_display_gamut_adaptation": True,
            "source": "kwin display-referred",
        },
        kwin_display_referred=True,
    )
    assert meta.skip_display_gamut_adaptation is True
    assert meta.transfer == "srgb"
    assert meta.primaries == "bt709"
