#!/usr/bin/env python3
"""Validate stable-tag promotion prerequisites against GitHub Actions evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable
from urllib import error, parse, request

API_VERSION = "2022-11-28"
USER_AGENT = "nanoleaf-release-promotion-validator"


class PromotionValidationError(Exception):
    """Raised when release promotion evidence is missing or invalid."""


@dataclass(frozen=True)
class RequiredJob:
    label: str
    name_fragment: str


REQUIRED_JOBS: tuple[RequiredJob, ...] = (
    RequiredJob("unit/integration tests (Ubuntu)", "Unit and integration tests / Ubuntu"),
    RequiredJob("unit/integration tests (Arch Linux)", "Unit and integration tests / Arch Linux"),
    RequiredJob(
        "release-install regressions (Ubuntu)",
        "Release/install regression tests / Ubuntu",
    ),
    RequiredJob(
        "release-install regressions (Arch Linux)",
        "Release/install regression tests / Arch Linux",
    ),
    RequiredJob("Arch metadata sanity", "Arch package metadata sanity"),
)


class GitHubActionsClient:
    """Small API wrapper focused on release-promotion checks."""

    def __init__(self, repository: str, token: str):
        self.repository = repository
        self.token = token

    def get_json(self, url: str) -> dict[str, Any]:
        req = request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": USER_AGENT,
            },
        )

        try:
            with request.urlopen(req) as response:
                payload = response.read().decode(response.headers.get_content_charset("utf-8"))
        except error.HTTPError as exc:  # pragma: no cover - network/auth dependent
            body = exc.read().decode("utf-8", errors="replace")
            raise PromotionValidationError(
                f"GitHub API request failed ({exc.code}) for {url}: {body}"
            ) from exc
        except error.URLError as exc:  # pragma: no cover - network dependent
            raise PromotionValidationError(
                f"Unable to reach GitHub API for {url}: {exc.reason}"
            ) from exc

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise PromotionValidationError(f"GitHub API returned malformed JSON for {url}.") from exc

        if not isinstance(parsed, dict):
            raise PromotionValidationError(f"GitHub API returned unexpected payload type for {url}.")
        return parsed

    def workflow_runs(self, workflow_file: str, head_sha: str, *, per_page: int = 100) -> list[dict[str, Any]]:
        encoded_workflow = parse.quote(workflow_file, safe="")
        params = parse.urlencode(
            {
                "event": "push",
                "status": "completed",
                "head_sha": head_sha,
                "per_page": per_page,
            }
        )
        payload = self.get_json(
            f"https://api.github.com/repos/{self.repository}/actions/workflows/{encoded_workflow}/runs?{params}"
        )
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list):
            raise PromotionValidationError("GitHub API response missing workflow_runs list.")
        return [run for run in runs if isinstance(run, dict)]

    def jobs_for_run(self, run_id: int) -> list[dict[str, Any]]:
        payload = self.get_json(
            f"https://api.github.com/repos/{self.repository}/actions/runs/{run_id}/jobs?per_page=100"
        )
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise PromotionValidationError("GitHub API response missing jobs list for pre-release run.")
        return [job for job in jobs if isinstance(job, dict)]

    def parent_shas(self, commit_sha: str) -> list[str]:
        payload = self.get_json(
            f"https://api.github.com/repos/{self.repository}/commits/{parse.quote(commit_sha, safe='')}"
        )
        parents = payload.get("parents")
        if not isinstance(parents, list):
            return []

        shas: list[str] = []
        for parent in parents:
            if isinstance(parent, dict):
                sha = parent.get("sha")
                if isinstance(sha, str) and sha:
                    shas.append(sha)
        return shas


def _successful_run_for_sha(runs: list[dict[str, Any]], sha: str) -> dict[str, Any] | None:
    successful = [
        run
        for run in runs
        if run.get("head_sha") == sha and run.get("conclusion") == "success"
    ]
    if not successful:
        return None
    return max(successful, key=lambda run: run.get("run_number", 0))


def _missing_required_jobs(jobs: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []

    for required in REQUIRED_JOBS:
        matched_jobs = [
            job for job in jobs if required.name_fragment.lower() in str(job.get("name", "")).lower()
        ]
        if not matched_jobs:
            missing.append(f"{required.label}: job not found")
            continue

        if not any(job.get("conclusion") == "success" for job in matched_jobs):
            outcomes = ", ".join(
                f"{job.get('name', '<unknown>')}={job.get('conclusion', 'unknown')}" for job in matched_jobs
            )
            missing.append(f"{required.label}: no successful job ({outcomes})")

    return missing


def _candidate_shas(client: GitHubActionsClient, target_sha: str, max_depth: int) -> list[str]:
    """Return target SHA and ancestor SHAs (merge-parent fallback support)."""
    ordered: list[str] = []
    queue: deque[tuple[str, int]] = deque([(target_sha, 0)])
    visited: set[str] = set()

    while queue:
        sha, depth = queue.popleft()
        if sha in visited:
            continue
        visited.add(sha)
        ordered.append(sha)

        if depth >= max_depth:
            continue

        for parent in client.parent_shas(sha):
            if parent not in visited:
                queue.append((parent, depth + 1))

    return ordered


def _iter_successful_candidates(
    client: GitHubActionsClient,
    workflow_file: str,
    shas: Iterable[str],
) -> Iterable[tuple[str, dict[str, Any]]]:
    for sha in shas:
        runs = client.workflow_runs(workflow_file, sha)
        run = _successful_run_for_sha(runs, sha)
        if run is not None:
            yield sha, run


def validate_release_promotion(
    target_sha: str,
    repository: str,
    workflow_file: str,
    token: str,
    max_ancestor_depth: int,
) -> str:
    client = GitHubActionsClient(repository=repository, token=token)

    for candidate_sha, successful_run in _iter_successful_candidates(
        client,
        workflow_file,
        _candidate_shas(client, target_sha, max_ancestor_depth),
    ):
        run_id = successful_run.get("id")
        if not isinstance(run_id, int):
            continue

        missing_jobs = _missing_required_jobs(client.jobs_for_run(run_id))
        if missing_jobs:
            raise PromotionValidationError(
                "Pre-release promotion evidence is incomplete. Required jobs missing/failing: "
                + "; ".join(missing_jobs)
            )

        html_url = successful_run.get("html_url", "<unknown run url>")
        return (
            "Release promotion validation passed: "
            f"workflow={workflow_file}, target_sha={target_sha}, evidence_sha={candidate_sha}, "
            f"run_id={run_id}, run_url={html_url}."
        )

    raise PromotionValidationError(
        "No successful pre-release workflow run found for target commit SHA or recent ancestors. "
        "Promoting stable tags requires successful RC validation before publishing."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate that stable tag promotion has successful pre-release workflow evidence."
    )
    parser.add_argument("--target-sha", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--workflow-file", default="pre-release.yml")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument(
        "--max-ancestor-depth",
        type=int,
        default=1,
        help="How many ancestor levels to inspect when target SHA has no direct pre-release run (default: 1).",
    )

    args = parser.parse_args()

    if not args.target_sha:
        print("ERROR: --target-sha is required (or set GITHUB_SHA).", file=sys.stderr)
        return 2
    if not args.repository:
        print("ERROR: --repository is required (or set GITHUB_REPOSITORY).", file=sys.stderr)
        return 2
    if not args.github_token:
        print("ERROR: --github-token is required (or set GITHUB_TOKEN).", file=sys.stderr)
        return 2
    if args.max_ancestor_depth < 0:
        print("ERROR: --max-ancestor-depth must be >= 0.", file=sys.stderr)
        return 2

    try:
        message = validate_release_promotion(
            target_sha=args.target_sha.strip(),
            repository=args.repository.strip(),
            workflow_file=args.workflow_file.strip(),
            token=args.github_token.strip(),
            max_ancestor_depth=args.max_ancestor_depth,
        )
    except PromotionValidationError as exc:
        print(f"ERROR: Stable release promotion blocked. {exc}", file=sys.stderr)
        return 1

    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
