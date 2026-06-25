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


def test_kwin_display_referred_overrides_backend_diagnostics() -> None:
    meta = resolve_capture_metadata(
        backend_metadata={
            "input_transfer": "srgb",
            "input_primaries": "bt709",
            "metadata_source": "kwin display-referred",
            "tone_mapping_applied": False,
            "skip_display_gamut_adaptation": True,
        },
        kwin_display_referred=True,
    )
    assert meta.transfer == "srgb"
    assert meta.primaries == "bt709"
    assert meta.source == "kwin display-referred"
    assert meta.skip_display_gamut_adaptation is True
    assert meta.confidence == "heuristic"


def test_tone_mapped_backend_diagnostics_become_display_referred() -> None:
    meta = resolve_capture_metadata(
        backend_metadata={
            "transfer": "linear",
            "primaries": "bt2020",
            "max_nits": 1000.0,
            "source": "backend metadata",
            "tone_mapping_applied": True,
        },
    )
    assert meta.transfer == "srgb"
    assert meta.primaries == "bt709"
    assert meta.source == "backend display-referred"
    assert meta.skip_display_gamut_adaptation is True


def test_analyzer_backend_diagnostics_preserve_hdr_input_metadata() -> None:
    meta = resolve_capture_metadata(
        backend_metadata={
            "input_transfer": "pq",
            "input_primaries": "bt2020",
            "metadata_source": "backend metadata",
            "hdr_max_nits": 1600.0,
            "tone_mapping_applied": False,
        },
    )
    assert meta.transfer == "pq"
    assert meta.primaries == "bt2020"
    assert meta.max_nits == 1600.0
    assert meta.source == "backend metadata"
    assert meta.skip_display_gamut_adaptation is True


def test_analyzer_tone_mapped_diagnostics_are_display_referred() -> None:
    meta = resolve_capture_metadata(
        backend_metadata={
            "input_transfer": "pq",
            "input_primaries": "bt2020",
            "metadata_source": "backend metadata",
            "hdr_max_nits": 1600.0,
            "tone_mapping_applied": True,
        },
    )
    assert meta.transfer == "srgb"
    assert meta.primaries == "bt709"
    assert meta.max_nits == 1600.0
    assert meta.source == "backend display-referred"
    assert meta.skip_display_gamut_adaptation is True
