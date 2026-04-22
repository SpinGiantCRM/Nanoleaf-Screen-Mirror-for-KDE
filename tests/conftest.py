from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure imports resolve from the namespaced src layout during test runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from nanoleaf_sync.capture.factory import (  # noqa: E402
    reset_cached_probe_winner,
    reset_capability_check_cache,
)


@pytest.fixture(autouse=True)
def _reset_capture_factory_caches() -> None:
    reset_cached_probe_winner()
    reset_capability_check_cache()
    yield
    reset_cached_probe_winner()
    reset_capability_check_cache()
