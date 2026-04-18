#!/usr/bin/env python3
"""Validate RC promotion evidence before publishing a stable release."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


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


def _github_get(url: str, token: str) -> dict[str, Any]:
    req = request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nanoleaf-release-promotion-validator",
        },
    )

    try:
        with request.urlopen(req) as resp:
            charset = resp.headers.get_content_charset("utf-8")
            payload = resp.read().decode(charset)
    except error.HTTPError as exc:  # pragma: no cover - network/auth dependent
        body = exc.read().decode("utf-8", errors="replace")
        raise PromotionValidationError(
            f"GitHub API request failed ({exc.code}) for {url}: {body}"
        ) from exc
    except error.URLError as exc:  # pragma: no cover - network dependent
        raise PromotionValidationError(f"Unable to reach GitHub API for {url}: {exc.reason}") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PromotionValidationError(f"GitHub API returned malformed JSON for {url}.") from exc


def _workflow_runs_url(repository: str, workflow_file: str, target_sha: str) -> str:
    encoded_workflow = parse.quote(workflow_file, safe="")
    params = parse.urlencode(
        {
            "event": "push",
            "status": "completed",
            "head_sha": target_sha,
            "per_page": 30,
        }
    )
    return f"https://api.github.com/repos/{repository}/actions/workflows/{encoded_workflow}/runs?{params}"


def _jobs_url(repository: str, run_id: int) -> str:
    return f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100"


def _select_successful_run(runs: list[dict[str, Any]], target_sha: str) -> dict[str, Any]:
    matching = [
        run
        for run in runs
        if run.get("head_sha") == target_sha and run.get("conclusion") == "success"
    ]
    if not matching:
        raise PromotionValidationError(
            "No successful pre-release workflow run found for the target commit SHA. "
            "Promoting stable tags requires successful RC validation on the exact same commit."
        )

    return max(matching, key=lambda run: run.get("run_number", 0))


def _missing_required_jobs(jobs: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []

    for required in REQUIRED_JOBS:
        matched_jobs = [
            job
            for job in jobs
            if required.name_fragment.lower() in str(job.get("name", "")).lower()
        ]
        if not matched_jobs:
            missing.append(f"{required.label}: job not found")
            continue

        if not any(job.get("conclusion") == "success" for job in matched_jobs):
            formatted_outcomes = ", ".join(
                f"{job.get('name', '<unknown>')}={job.get('conclusion', 'unknown')}" for job in matched_jobs
            )
            missing.append(f"{required.label}: no successful job ({formatted_outcomes})")

    return missing


def validate_release_promotion(target_sha: str, repository: str, workflow_file: str, token: str) -> str:
    runs_payload = _github_get(_workflow_runs_url(repository, workflow_file, target_sha), token)
    runs = runs_payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise PromotionValidationError("GitHub API response missing workflow_runs list.")

    successful_run = _select_successful_run(runs, target_sha)

    run_id = successful_run.get("id")
    if not isinstance(run_id, int):
        raise PromotionValidationError("Successful pre-release workflow run is missing a numeric id.")

    jobs_payload = _github_get(_jobs_url(repository, run_id), token)
    jobs = jobs_payload.get("jobs")
    if not isinstance(jobs, list):
        raise PromotionValidationError("GitHub API response missing jobs list for pre-release run.")

    missing_jobs = _missing_required_jobs(jobs)
    if missing_jobs:
        raise PromotionValidationError(
            "Pre-release promotion evidence is incomplete. Required jobs missing/failing: "
            + "; ".join(missing_jobs)
        )

    html_url = successful_run.get("html_url", "<unknown run url>")
    return (
        "Release promotion validation passed: "
        f"workflow={workflow_file}, head_sha={target_sha}, run_id={run_id}, run_url={html_url}."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ensure stable release tags are promoted only from commits that already passed "
            "pre-release workflow validation."
        )
    )
    parser.add_argument(
        "--target-sha",
        default=os.environ.get("GITHUB_SHA"),
        help="Commit SHA that is being promoted to stable (defaults to GITHUB_SHA).",
    )
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="GitHub owner/repo slug (defaults to GITHUB_REPOSITORY).",
    )
    parser.add_argument(
        "--workflow-file",
        default="pre-release.yml",
        help="Workflow file used for RC gates (default: pre-release.yml).",
    )
    parser.add_argument(
        "--github-token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub token with actions read access (defaults to GITHUB_TOKEN env var).",
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

    try:
        message = validate_release_promotion(
            target_sha=args.target_sha.strip(),
            repository=args.repository.strip(),
            workflow_file=args.workflow_file.strip(),
            token=args.github_token.strip(),
        )
    except PromotionValidationError as exc:
        print(
            "ERROR: Stable release promotion blocked. "
            f"{exc}",
            file=sys.stderr,
        )
        return 1

    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
