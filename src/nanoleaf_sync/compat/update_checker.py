from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from packaging.version import Version

import nanoleaf_sync

logger = logging.getLogger(__name__)

GITHUB_LATEST_URL = (
    "https://api.github.com/repos/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/releases/latest"
)
CACHE_TTL_S = 3600
_USER_AGENT = "nanoleaf-kde-sync-update-checker"


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str | None
    update_available: bool
    published_at: str | None
    release_notes: str | None
    check_status: str
    message: str
    checked_at: str
    from_cache: bool

    def __str__(self) -> str:
        if self.update_available and self.latest_version:
            return (
                f"update available: {self.current_version} -> {self.latest_version} "
                f"({self.check_status})"
            )
        return f"up to date: {self.current_version} ({self.check_status})"


def default_cache_path() -> Path:
    return Path.home() / ".cache" / "nanoleaf-kde-sync" / "version-check.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_release_tag(tag_name: str | None) -> str | None:
    if not tag_name:
        return None
    normalized = str(tag_name).strip()
    if normalized.lower().startswith("v"):
        normalized = normalized[1:]
    return normalized or None


def _parse_checked_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cache_is_fresh(payload: dict[str, Any], *, now: datetime | None = None) -> bool:
    checked_at = _parse_checked_at(str(payload.get("checked_at") or ""))
    if checked_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    age_s = (current - checked_at).total_seconds()
    return age_s < CACHE_TTL_S


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("Failed to read update-check cache at %s", path, exc_info=True)
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _result_from_cache(
    payload: dict[str, Any],
    *,
    current_version: str,
    check_status: str,
    message: str,
) -> UpdateCheckResult:
    latest_version = _normalize_release_tag(payload.get("latest_version"))
    if latest_version is None:
        latest_version = _normalize_release_tag(payload.get("tag_name"))
    update_available = bool(payload.get("update_available"))
    if latest_version:
        try:
            update_available = Version(latest_version) > Version(current_version)
        except Exception:
            logger.debug("Unable to compare cached versions", exc_info=True)
    return UpdateCheckResult(
        current_version=current_version,
        latest_version=latest_version,
        update_available=update_available,
        published_at=str(payload.get("published_at") or "") or None,
        release_notes=str(payload.get("release_notes") or "") or None,
        check_status=check_status,
        message=message,
        checked_at=str(payload.get("checked_at") or _utc_now_iso()),
        from_cache=True,
    )


def _build_result(
    *,
    current_version: str,
    tag_name: str | None,
    published_at: str | None,
    release_notes: str | None,
    check_status: str,
    message: str,
    from_cache: bool,
    checked_at: str | None = None,
) -> UpdateCheckResult:
    latest_version = _normalize_release_tag(tag_name)
    update_available = False
    if latest_version:
        try:
            update_available = Version(latest_version) > Version(current_version)
        except Exception:
            logger.debug("Unable to compare release versions", exc_info=True)
    return UpdateCheckResult(
        current_version=current_version,
        latest_version=latest_version,
        update_available=update_available,
        published_at=published_at,
        release_notes=release_notes,
        check_status=check_status,
        message=message,
        checked_at=checked_at or _utc_now_iso(),
        from_cache=from_cache,
    )


def _fetch_latest_release(*, etag: str | None = None) -> tuple[int, dict[str, Any], str | None]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
    }
    if etag:
        headers["If-None-Match"] = etag
    request = Request(GITHUB_LATEST_URL, headers=headers, method="GET")
    with urlopen(request, timeout=15) as response:
        status = int(getattr(response, "status", response.getcode()))
        body = response.read().decode("utf-8")
        response_etag = response.headers.get("ETag")
        payload = json.loads(body) if body.strip() else {}
        if not isinstance(payload, dict):
            raise ValueError("GitHub releases/latest response was not a JSON object")
        return status, payload, response_etag


def _persist_successful_check(
    *,
    cache_path: Path,
    current_version: str,
    release_payload: dict[str, Any],
    etag: str | None,
    check_status: str,
    message: str,
) -> UpdateCheckResult:
    checked_at = _utc_now_iso()
    tag_name = str(release_payload.get("tag_name") or "")
    result = _build_result(
        current_version=current_version,
        tag_name=tag_name,
        published_at=str(release_payload.get("published_at") or "") or None,
        release_notes=str(release_payload.get("body") or "") or None,
        check_status=check_status,
        message=message,
        from_cache=False,
        checked_at=checked_at,
    )
    cache_payload = {
        "checked_at": checked_at,
        "etag": etag,
        "tag_name": tag_name,
        "latest_version": result.latest_version,
        "update_available": result.update_available,
        "published_at": result.published_at,
        "release_notes": result.release_notes,
        "check_status": check_status,
        "message": message,
        "last_notified_version": _load_cache(cache_path).get("last_notified_version"),
    }
    _write_cache(cache_path, cache_payload)
    return result


def mark_update_notified(version: str, *, cache_path: Path | None = None) -> None:
    path = cache_path or default_cache_path()
    payload = _load_cache(path)
    if not payload:
        payload = {"checked_at": _utc_now_iso()}
    payload["last_notified_version"] = _normalize_release_tag(version) or str(version).strip()
    _write_cache(path, payload)


def should_notify_for_update(result: UpdateCheckResult, *, cache_path: Path | None = None) -> bool:
    if not result.update_available or not result.latest_version:
        return False
    payload = _load_cache(cache_path or default_cache_path())
    last_notified = _normalize_release_tag(str(payload.get("last_notified_version") or ""))
    return last_notified != result.latest_version


def update_notification_message(result: UpdateCheckResult) -> str:
    if not result.update_available or not result.latest_version:
        return ""
    return (
        f"Update available: v{result.latest_version} "
        f"(installed v{result.current_version}). "
        "Update with your package manager, for example: paru -Syu"
    )


def manual_check_message(result: UpdateCheckResult) -> str:
    if result.update_available and result.latest_version:
        return (
            f"v{result.latest_version} is available (you have v{result.current_version}).\n"
            "Update with your package manager, for example:\n"
            "  paru -Syu\n"
            "  pacman -Syu"
        )
    if result.check_status in {"error", "rate_limited"} and not result.latest_version:
        return f"Could not check for updates: {result.message}"
    return f"You're up to date (v{result.current_version})."


def check_for_updates(*, force: bool = False, cache_path: Path | None = None) -> UpdateCheckResult:
    path = cache_path or default_cache_path()
    current_version = str(nanoleaf_sync.__version__)
    cached = _load_cache(path)

    if not force and cached and _cache_is_fresh(cached):
        return _result_from_cache(
            cached,
            current_version=current_version,
            check_status="cached",
            message="Using cached update-check result",
        )

    etag = str(cached.get("etag") or "") or None
    try:
        status, payload, response_etag = _fetch_latest_release(etag=etag if cached else None)
    except HTTPError as exc:
        if exc.code == 304 and cached:
            refreshed = dict(cached)
            refreshed["checked_at"] = _utc_now_iso()
            _write_cache(path, refreshed)
            return _result_from_cache(
                refreshed,
                current_version=current_version,
                check_status="cached",
                message="Release metadata unchanged (HTTP 304)",
            )
        if exc.code in {403, 429} and cached:
            logger.warning("GitHub update check rate-limited; using cached result")
            return _result_from_cache(
                cached,
                current_version=current_version,
                check_status="rate_limited",
                message="GitHub API rate limit reached; using cached result",
            )
        logger.warning("GitHub update check failed with HTTP %s", exc.code, exc_info=True)
        if cached:
            return _result_from_cache(
                cached,
                current_version=current_version,
                check_status="error",
                message=f"GitHub HTTP error {exc.code}; using cached result",
            )
        return _build_result(
            current_version=current_version,
            tag_name=None,
            published_at=None,
            release_notes=None,
            check_status="error",
            message=f"GitHub HTTP error {exc.code}",
            from_cache=False,
        )
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Update check failed: %s", exc, exc_info=True)
        if cached:
            return _result_from_cache(
                cached,
                current_version=current_version,
                check_status="error",
                message=f"{exc}; using cached result",
            )
        return _build_result(
            current_version=current_version,
            tag_name=None,
            published_at=None,
            release_notes=None,
            check_status="error",
            message=str(exc),
            from_cache=False,
        )

    if status == 304 and cached:
        refreshed = dict(cached)
        refreshed["checked_at"] = _utc_now_iso()
        _write_cache(path, refreshed)
        return _result_from_cache(
            refreshed,
            current_version=current_version,
            check_status="cached",
            message="Release metadata unchanged (HTTP 304)",
        )

    return _persist_successful_check(
        cache_path=path,
        current_version=current_version,
        release_payload=payload,
        etag=response_etag,
        check_status="ok",
        message="Fetched latest release metadata from GitHub",
    )
