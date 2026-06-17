from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import nanoleaf_sync

from nanoleaf_sync.compat import update_checker


class _FakeHTTPResponse:
    def __init__(self, *, status: int, body: str, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._body = body.encode("utf-8")
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_check_for_updates_uses_fresh_cache_without_network(tmp_path: Path, monkeypatch) -> None:
    cache_path = tmp_path / "version-check.json"
    checked_at = datetime.now(timezone.utc).isoformat()
    cache_path.write_text(
        json.dumps(
            {
                "checked_at": checked_at,
                "etag": '"abc"',
                "tag_name": "v9.9.9",
                "latest_version": "9.9.9",
                "update_available": True,
                "published_at": "2026-01-01T00:00:00Z",
                "release_notes": "Big release",
                "check_status": "ok",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(nanoleaf_sync, "__version__", "1.6.0")

    def _fail_fetch(**_kwargs):
        raise AssertionError("network fetch should be skipped for fresh cache")

    monkeypatch.setattr(update_checker, "_fetch_latest_release", _fail_fetch)

    result = update_checker.check_for_updates(cache_path=cache_path)

    assert result.from_cache is True
    assert result.check_status == "cached"
    assert result.latest_version == "9.9.9"
    assert result.update_available is True


def test_check_for_updates_fetches_and_writes_cache(tmp_path: Path, monkeypatch) -> None:
    cache_path = tmp_path / "version-check.json"
    monkeypatch.setattr(nanoleaf_sync, "__version__", "1.6.0")
    monkeypatch.setattr(
        update_checker,
        "_fetch_latest_release",
        lambda **_: (
            200,
            {
                "tag_name": "v1.7.0",
                "published_at": "2026-02-01T00:00:00Z",
                "body": "Release notes",
            },
            '"release-etag"',
        ),
    )

    result = update_checker.check_for_updates(force=True, cache_path=cache_path)

    assert result.check_status == "ok"
    assert result.latest_version == "1.7.0"
    assert result.update_available is True
    assert cache_path.is_file()
    stored = json.loads(cache_path.read_text(encoding="utf-8"))
    assert stored["etag"] == '"release-etag"'
    assert stored["latest_version"] == "1.7.0"


def test_check_for_updates_honors_etag_not_modified(tmp_path: Path, monkeypatch) -> None:
    cache_path = tmp_path / "version-check.json"
    stale_checked_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    cache_path.write_text(
        json.dumps(
            {
                "checked_at": stale_checked_at,
                "etag": '"etag-1"',
                "tag_name": "v1.6.0",
                "latest_version": "1.6.0",
                "update_available": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(nanoleaf_sync, "__version__", "1.6.0")

    def _raise_304(**_kwargs):
        raise HTTPError(
            update_checker.GITHUB_LATEST_URL,
            304,
            "Not Modified",
            hdrs=None,
            fp=BytesIO(b""),
        )

    monkeypatch.setattr(update_checker, "_fetch_latest_release", _raise_304)

    result = update_checker.check_for_updates(force=True, cache_path=cache_path)

    assert result.from_cache is True
    assert result.check_status == "cached"
    assert result.latest_version == "1.6.0"
    refreshed = json.loads(cache_path.read_text(encoding="utf-8"))
    assert refreshed["checked_at"] != stale_checked_at


def test_check_for_updates_rate_limited_falls_back_to_cache(tmp_path: Path, monkeypatch) -> None:
    cache_path = tmp_path / "version-check.json"
    cache_path.write_text(
        json.dumps(
            {
                "checked_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                "tag_name": "v1.8.0",
                "latest_version": "1.8.0",
                "update_available": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(nanoleaf_sync, "__version__", "1.6.0")

    def _raise_403(**_kwargs):
        raise HTTPError(
            update_checker.GITHUB_LATEST_URL,
            403,
            "Forbidden",
            hdrs=None,
            fp=BytesIO(b"rate limit"),
        )

    monkeypatch.setattr(update_checker, "_fetch_latest_release", _raise_403)

    result = update_checker.check_for_updates(force=True, cache_path=cache_path)

    assert result.check_status == "rate_limited"
    assert result.latest_version == "1.8.0"
    assert result.update_available is True


def test_should_notify_only_once_per_latest_version(tmp_path: Path) -> None:
    cache_path = tmp_path / "version-check.json"
    result = update_checker.UpdateCheckResult(
        current_version="1.6.0",
        latest_version="1.7.0",
        update_available=True,
        published_at=None,
        release_notes=None,
        check_status="ok",
        message="ok",
        checked_at=update_checker._utc_now_iso(),
        from_cache=False,
    )

    assert update_checker.should_notify_for_update(result, cache_path=cache_path) is True
    update_checker.mark_update_notified("v1.7.0", cache_path=cache_path)
    assert update_checker.should_notify_for_update(result, cache_path=cache_path) is False


def test_manual_check_message_variants() -> None:
    up_to_date = update_checker.UpdateCheckResult(
        current_version="1.6.0",
        latest_version="1.6.0",
        update_available=False,
        published_at=None,
        release_notes=None,
        check_status="ok",
        message="ok",
        checked_at=update_checker._utc_now_iso(),
        from_cache=False,
    )
    assert "up to date" in update_checker.manual_check_message(up_to_date).lower()

    available = update_checker.UpdateCheckResult(
        current_version="1.6.0",
        latest_version="1.7.0",
        update_available=True,
        published_at=None,
        release_notes=None,
        check_status="ok",
        message="ok",
        checked_at=update_checker._utc_now_iso(),
        from_cache=False,
    )
    message = update_checker.manual_check_message(available)
    assert "1.7.0" in message
    assert "paru -Syu" in message


def test_default_cache_path_under_nanoleaf_cache() -> None:
    path = update_checker.default_cache_path()
    assert path.name == "version-check.json"
    assert path.parent.name == "nanoleaf-kde-sync"
