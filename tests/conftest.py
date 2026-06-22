from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure imports resolve from the namespaced src layout during test runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from nanoleaf_sync import service as service_module  # noqa: E402
from nanoleaf_sync.capture.factory import (  # noqa: E402
    reset_cached_probe_winner,
    reset_capability_check_cache,
)
from nanoleaf_sync.capture.kmsgrab import reset_cached_drm_probe  # noqa: E402
from nanoleaf_sync.runtime.color_processing import (  # noqa: E402
    init_gamut_adaptation,
    set_skip_display_gamut_adaptation,
)


@pytest.fixture(autouse=True)
def _reset_color_processing_globals() -> None:
    set_skip_display_gamut_adaptation(False)
    init_gamut_adaptation("srgb")
    yield
    set_skip_display_gamut_adaptation(False)
    init_gamut_adaptation("srgb")


@pytest.fixture(autouse=True)
def _reset_capture_factory_caches() -> None:
    reset_cached_probe_winner()
    reset_capability_check_cache()
    reset_cached_drm_probe()
    service_module.NanoleafSyncService.reset_boot_probe_state()
    yield
    reset_cached_probe_winner()
    reset_capability_check_cache()
    reset_cached_drm_probe()
    service_module.NanoleafSyncService.reset_boot_probe_state()
