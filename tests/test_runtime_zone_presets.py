from __future__ import annotations

import builtins
import importlib
import sys

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.zone_presets import make_edge_weighted_zones


def test_zone_derivation_operates_when_ui_zone_presets_are_unavailable(monkeypatch) -> None:
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "nanoleaf_sync.ui.zone_presets":
            raise ImportError("UI zone presets are not available in runtime context")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    module_name = "nanoleaf_sync.runtime.zone_derivation"
    previous = sys.modules.pop(module_name, None)
    try:
        zone_derivation = importlib.import_module(module_name)
        zones = zone_derivation.derive_source_zones(
            config=AppConfig(device_zone_count=12),
            detected_device_zone_count=48,
            frame_width=1920,
            frame_height=1080,
        )
    finally:
        if previous is not None:
            sys.modules[module_name] = previous
        else:
            sys.modules.pop(module_name, None)

    assert len(zones) == 12
    assert zones[0].y == 0.0


def test_make_edge_weighted_zones_returns_requested_count() -> None:
    zones = make_edge_weighted_zones(12, edge_locality="balanced")
    assert len(zones) == 12
