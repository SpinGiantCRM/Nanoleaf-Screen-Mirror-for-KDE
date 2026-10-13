"""Fixture and parity checks for the offline prototype, never the live service."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "rust_core_benchmark", ROOT / "scripts/benchmark_rust_core.py"
)
assert spec is not None and spec.loader is not None
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def test_python_fixture_probe_preserves_padding_and_linear_light(tmp_path: Path) -> None:
    frame = np.asarray([[[0, 0, 0], [255, 255, 255]]], dtype=np.uint8)
    frame_path, zone_path, _ = harness.write_fixture(tmp_path, frame, [(0, 0, 2, 1)])
    result = harness.python_probe(frame_path, zone_path, 1, 0)
    assert result["rgb"] == [[188, 188, 188]]
    assert result["variance"] == [16256.25]


def test_python_probe_refuses_hdr_label(tmp_path: Path) -> None:
    frame = np.zeros((1, 1, 3), dtype=np.uint8)
    frame_path, zone_path, _ = harness.write_fixture(tmp_path, frame, [(0, 0, 1, 1)])
    blob = frame_path.read_bytes()
    frame_path.write_bytes(b"NHDR0001" + blob[8:])
    with pytest.raises(ValueError, match="SDR"):
        harness.python_probe(frame_path, zone_path, 1, 0)


def test_python_probe_refuses_manual_count_mismatch(tmp_path: Path) -> None:
    frame = np.zeros((1, 1, 3), dtype=np.uint8)
    frame_path, zone_path, _ = harness.write_fixture(tmp_path, frame, [(0, 0, 1, 1)])
    blob = zone_path.read_bytes()
    zone_path.write_bytes(harness.ZONE_HEADER.pack(b"NZONE001", 1, 48) + blob[24:])
    with pytest.raises(ValueError, match="manual-count"):
        harness.python_probe(frame_path, zone_path, 1, 0)
