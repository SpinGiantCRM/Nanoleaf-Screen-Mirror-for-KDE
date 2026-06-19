from __future__ import annotations

import ast
from pathlib import Path

from nanoleaf_sync.runtime import zone_derivation
from nanoleaf_sync.runtime.zone_presets import make_edge_weighted_zones


def test_zone_derivation_does_not_import_ui_zone_presets() -> None:
    source = Path(zone_derivation.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "nanoleaf_sync.ui.zone_presets"
    ]
    assert imports == []


def test_make_edge_weighted_zones_returns_requested_count() -> None:
    zones = make_edge_weighted_zones(12, edge_locality="balanced")
    assert len(zones) == 12
