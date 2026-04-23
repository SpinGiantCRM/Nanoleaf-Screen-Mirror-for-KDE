from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import numpy as np


def test_device_package_exports_import() -> None:
    from nanoleaf_sync.device import (
        DeviceDriver,
        DriverCapabilities,
        NanoleafUSBDriver,
        NanoleafUSBIds,
    )

    assert DeviceDriver is not None
    assert DriverCapabilities is not None
    assert NanoleafUSBIds is not None
    assert NanoleafUSBDriver is not None


def test_average_color_runtime_public_path_smoke() -> None:
    from nanoleaf_sync.runtime.zones import average_color

    image = np.array([[[1, 2, 3], [5, 6, 7]]], dtype=np.uint8)

    assert average_color(image) == (3, 4, 5)


def test_cli_entrypoint_target_resolves() -> None:
    project_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    entry_target = pyproject["project"]["scripts"]["nanoleaf-kde-sync"]
    module_name, attr_name = entry_target.split(":", maxsplit=1)

    module = importlib.import_module(module_name)
    assert getattr(module, attr_name) is not None


def test_top_level_runtime_and_ui_packages_import() -> None:
    runtime_pkg = importlib.import_module("nanoleaf_sync.runtime")
    ui_pkg = importlib.import_module("nanoleaf_sync.ui")

    assert runtime_pkg is not None
    assert ui_pkg is not None
