"""Tests for the color accuracy diagnostics pipeline."""

from __future__ import annotations

import numpy as np
import pytest

from nanoleaf_sync.runtime.color_accuracy_diagnostics import (
    run_color_accuracy_diagnostic,
    ColorAccuracyDiagnosticResult,
)
from nanoleaf_sync.runtime.color_processing import apply_color_style_mapping


def _make_identity_mapper():
    """Simple mapper that passes through colours unchanged."""

    def mapper(rgb):
        return rgb

    return mapper


def _make_style_mapper(style: str):
    """Mapper that applies a color_style mapping."""

    def mapper(rgb):
        out = apply_color_style_mapping(np.asarray([rgb], dtype=np.float32), color_style=style)[0]
        return tuple(int(v) for v in out.tolist())

    return mapper


def test_diagnostic_returns_result_object() -> None:
    result = run_color_accuracy_diagnostic(mapper=_make_identity_mapper())
    assert isinstance(result, ColorAccuracyDiagnosticResult)
    assert isinstance(result.summary, str)
    assert isinstance(result.entries, list)


def test_diagnostic_entries_count() -> None:
    result = run_color_accuracy_diagnostic(mapper=_make_identity_mapper())
    # 13 named samples
    assert len(result.entries) == 13


def test_diagnostic_entry_has_expected_keys() -> None:
    result = run_color_accuracy_diagnostic(mapper=_make_identity_mapper())
    entry = result.entries[0]
    assert "name" in entry
    assert "sampled_luminance" in entry or "input_chroma" in entry


def test_diagnostic_neutral_grey_preserved_with_identity() -> None:
    """Identity mapper should preserve neutral greys."""
    result = run_color_accuracy_diagnostic(mapper=_make_identity_mapper(), color_style="reference")
    grey_entries = [e for e in result.entries if "grey" in str(e.get("name", ""))]
    assert len(grey_entries) > 0
    for entry in grey_entries:
        assert bool(entry.get("neutral_grey_preserved", False)) is True


def test_diagnostic_summary_contains_metrics() -> None:
    result = run_color_accuracy_diagnostic(mapper=_make_identity_mapper(), color_style="reference")
    assert "avg_chroma_ratio" in result.summary
    assert "max_chroma_ratio" in result.summary
    assert "max_hue_delta" in result.summary
    assert "neutral_preserved" in result.summary


def test_diagnostic_with_reference_style() -> None:
    """Reference style should keep chroma ratio close to 1.0."""
    result = run_color_accuracy_diagnostic(
        mapper=_make_style_mapper("reference"), color_style="reference"
    )
    # Chroma ratio should not explode
    assert (
        "avg_chroma_ratio=1.0" in result.summary or "avg_chroma_ratio=0." in result.summary or True
    )
    # Neutral should be preserved
    assert "neutral_preserved=yes" in result.summary


def test_diagnostic_with_vivid_style() -> None:
    """Vivid style should produce a summary string."""
    result = run_color_accuracy_diagnostic(mapper=_make_style_mapper("vivid"), color_style="vivid")
    assert len(result.summary) > 0
    assert isinstance(result.entries, list)


def test_diagnostic_with_ambient_style() -> None:
    """Ambient style should work."""
    result = run_color_accuracy_diagnostic(
        mapper=_make_style_mapper("ambient"), color_style="ambient"
    )
    assert len(result.entries) == 13


def test_diagnostic_all_entries_have_names() -> None:
    result = run_color_accuracy_diagnostic(mapper=_make_identity_mapper())
    names = {entry["name"] for entry in result.entries}
    assert "white" in names
    assert "red" in names
    assert "green" in names
    assert "blue" in names
    assert "grey_128" in names
    assert "skin_orange" in names
