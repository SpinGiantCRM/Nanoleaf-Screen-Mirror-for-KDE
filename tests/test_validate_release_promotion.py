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


def test_successful_run_for_sha_returns_latest_run() -> None:
    runs = [
        {"head_sha": "abc123", "conclusion": "success", "run_number": 10, "id": 100},
        {"head_sha": "abc123", "conclusion": "success", "run_number": 11, "id": 101},
        {"head_sha": "abc123", "conclusion": "failure", "run_number": 99, "id": 200},
    ]

    result = validate_release_promotion._successful_run_for_sha(runs, "abc123")

    assert result is not None
    assert result["id"] == 101


def test_successful_run_for_sha_returns_none_when_not_found() -> None:
    runs = [{"head_sha": "abc123", "conclusion": "failure", "run_number": 3}]

    assert validate_release_promotion._successful_run_for_sha(runs, "abc123") is None


def test_missing_required_jobs_reports_failed_and_missing_jobs() -> None:
    jobs = [
        {"name": "Common CI gates / Unit and integration tests / Ubuntu", "conclusion": "success"},
        {"name": "Common CI gates / Unit and integration tests / Arch Linux", "conclusion": "failure"},
        {"name": "Common CI gates / Release/install regression tests / Ubuntu", "conclusion": "success"},
        {"name": "Common CI gates / Release/install regression tests / Arch Linux", "conclusion": "success"},
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


def test_candidate_shas_includes_target_then_parent() -> None:
    class FakeClient:
        def parent_shas(self, sha: str) -> list[str]:
            return {"target": ["parent"], "parent": []}.get(sha, [])

    shas = validate_release_promotion._candidate_shas(FakeClient(), "target", 1)

    assert shas == ["target", "parent"]


def test_validate_release_promotion_uses_parent_evidence() -> None:
    class FakeClient:
        def __init__(self, repository: str, token: str):
            self.repository = repository
            self.token = token

        def parent_shas(self, sha: str) -> list[str]:
            return {"target": ["parent"], "parent": []}.get(sha, [])

        def workflow_runs(self, workflow_file: str, head_sha: str, *, per_page: int = 100):
            if head_sha == "parent":
                return [{"head_sha": "parent", "conclusion": "success", "run_number": 1, "id": 42, "html_url": "https://example.test/run/42"}]
            return []

        def jobs_for_run(self, run_id: int):
            assert run_id == 42
            return [
                {"name": "Unit and integration tests / Ubuntu", "conclusion": "success"},
                {"name": "Unit and integration tests / Arch Linux", "conclusion": "success"},
                {"name": "Release/install regression tests / Ubuntu", "conclusion": "success"},
                {"name": "Release/install regression tests / Arch Linux", "conclusion": "success"},
                {"name": "Arch package metadata sanity", "conclusion": "success"},
            ]

    original = validate_release_promotion.GitHubActionsClient
    validate_release_promotion.GitHubActionsClient = FakeClient
    try:
        msg = validate_release_promotion.validate_release_promotion(
            target_sha="target",
            repository="owner/repo",
            workflow_file="pre-release.yml",
            token="token",
            max_ancestor_depth=1,
        )
    finally:
        validate_release_promotion.GitHubActionsClient = original

    assert "evidence_sha=parent" in msg


def test_validate_release_promotion_raises_when_no_evidence() -> None:
    class FakeClient:
        def __init__(self, repository: str, token: str):
            self.repository = repository
            self.token = token

        def parent_shas(self, sha: str) -> list[str]:
            return []

        def workflow_runs(self, workflow_file: str, head_sha: str, *, per_page: int = 100):
            return []

        def jobs_for_run(self, run_id: int):
            return []

    original = validate_release_promotion.GitHubActionsClient
    validate_release_promotion.GitHubActionsClient = FakeClient
    try:
        with pytest.raises(validate_release_promotion.PromotionValidationError, match="No successful pre-release"):
            validate_release_promotion.validate_release_promotion(
                target_sha="target",
                repository="owner/repo",
                workflow_file="pre-release.yml",
                token="token",
                max_ancestor_depth=1,
            )
    finally:
        validate_release_promotion.GitHubActionsClient = original
