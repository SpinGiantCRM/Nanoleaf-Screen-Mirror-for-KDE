from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(relative_path: str, module_name: str):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


validate_release_promotion = _load_module(
    "scripts/validate_release_promotion.py", "validate_release_promotion"
)


def test_select_successful_run_returns_latest_for_target_sha() -> None:
    runs = [
        {"head_sha": "abc123", "conclusion": "success", "run_number": 11, "id": 1},
        {"head_sha": "abc123", "conclusion": "success", "run_number": 12, "id": 2},
        {"head_sha": "other", "conclusion": "success", "run_number": 99, "id": 3},
    ]

    selected = validate_release_promotion._select_successful_run(runs, "abc123")

    assert selected["id"] == 2


def test_select_successful_run_raises_when_none_for_target_sha() -> None:
    runs = [{"head_sha": "abc123", "conclusion": "failure", "run_number": 3}]

    with pytest.raises(validate_release_promotion.PromotionValidationError, match="No successful pre-release"):
        validate_release_promotion._select_successful_run(runs, "abc123")


def test_missing_required_jobs_reports_failed_and_missing_jobs() -> None:
    jobs = [
        {"name": "Common CI gates / Unit and integration tests / Ubuntu", "conclusion": "success"},
        {"name": "Common CI gates / Unit and integration tests / Arch Linux", "conclusion": "failure"},
        {"name": "Common CI gates / Release/install regression tests / Ubuntu", "conclusion": "success"},
        {"name": "Common CI gates / Release/install regression tests / Arch Linux", "conclusion": "success"},
        # Arch package metadata sanity intentionally missing.
    ]

    missing = validate_release_promotion._missing_required_jobs(jobs)

    assert len(missing) == 2
    assert any("unit/integration tests (Arch Linux): no successful job" in item for item in missing)
    assert any("Arch metadata sanity: job not found" in item for item in missing)


def test_missing_required_jobs_empty_when_all_successful() -> None:
    jobs = [
        {"name": "Common CI gates / Unit and integration tests / Ubuntu", "conclusion": "success"},
        {"name": "Common CI gates / Unit and integration tests / Arch Linux", "conclusion": "success"},
        {"name": "Common CI gates / Release/install regression tests / Ubuntu", "conclusion": "success"},
        {"name": "Common CI gates / Release/install regression tests / Arch Linux", "conclusion": "success"},
        {"name": "Common CI gates / Arch package metadata sanity", "conclusion": "success"},
    ]

    assert validate_release_promotion._missing_required_jobs(jobs) == []
