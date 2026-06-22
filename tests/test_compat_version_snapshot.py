from __future__ import annotations

import json

from nanoleaf_sync.compat import version_snapshot


def test_version_snapshot_read_write(tmp_path, monkeypatch) -> None:
    snapshot_path = tmp_path / "kde-version-snapshot.json"
    monkeypatch.setattr(
        version_snapshot,
        "collect_current_versions",
        lambda: {
            "last_seen_kwin_version": "6.3.1",
            "last_seen_kde_plasma_version": "6.3.1",
            "last_seen_screenshot2_version": 5,
            "last_seen_portal_version": 6,
            "last_seen_python_version": "3.12.7",
        },
    )

    payload = version_snapshot.update_snapshot(path=snapshot_path)
    assert snapshot_path.is_file()
    stored = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert stored["last_seen_kwin_version"] == "6.3.1"
    assert stored["last_seen_screenshot2_version"] == 5
    assert "last_updated" in stored
    assert stored["snapshot_persisted"] is True
    assert payload["snapshot_persisted"] is True
    assert payload["last_seen_portal_version"] == 6


def test_version_snapshot_write_failure_is_nonfatal(tmp_path, monkeypatch) -> None:
    snapshot_path = tmp_path / "readonly" / "kde-version-snapshot.json"
    monkeypatch.setattr(
        version_snapshot,
        "collect_current_versions",
        lambda: {
            "last_seen_kwin_version": "6.3.1",
            "last_seen_kde_plasma_version": "6.3.1",
            "last_seen_screenshot2_version": 5,
            "last_seen_portal_version": 6,
            "last_seen_python_version": "3.12.7",
        },
    )

    def _fail_write_text(*_args, **_kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(type(snapshot_path), "write_text", _fail_write_text)

    payload = version_snapshot.update_snapshot(path=snapshot_path)

    assert payload["snapshot_persisted"] is False
    assert payload["snapshot_write_error"] == str(snapshot_path)
    assert payload["last_seen_kwin_version"] == "6.3.1"


def test_version_diff_detection(tmp_path, monkeypatch) -> None:
    snapshot_path = tmp_path / "kde-version-snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "last_seen_kwin_version": "6.3.0",
                "last_seen_kde_plasma_version": "6.3.0",
                "last_seen_screenshot2_version": 4,
                "last_seen_portal_version": 5,
                "last_seen_python_version": "3.12.0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        version_snapshot,
        "collect_current_versions",
        lambda: {
            "last_seen_kwin_version": "6.4.0",
            "last_seen_kde_plasma_version": "6.4.0",
            "last_seen_screenshot2_version": 5,
            "last_seen_portal_version": 6,
            "last_seen_python_version": "3.12.7",
        },
    )

    report = version_snapshot.check_for_upgrade(path=snapshot_path)
    changed = report["changed"]
    assert changed["last_seen_kwin_version"] == {"previous": "6.3.0", "current": "6.4.0"}
    assert changed["last_seen_kde_plasma_version"] == {"previous": "6.3.0", "current": "6.4.0"}
    assert changed["last_seen_screenshot2_version"] == {"previous": 4, "current": 5}
    assert changed["last_seen_portal_version"] == {"previous": 5, "current": 6}
    assert changed["last_seen_python_version"] == {"previous": "3.12.0", "current": "3.12.7"}
    assert report["first_run"] is False


def test_version_diff_first_run_has_no_changes(tmp_path, monkeypatch) -> None:
    snapshot_path = tmp_path / "missing.json"
    monkeypatch.setattr(
        version_snapshot,
        "collect_current_versions",
        lambda: {
            "last_seen_kwin_version": "6.3.1",
            "last_seen_kde_plasma_version": "6.3.1",
            "last_seen_screenshot2_version": 5,
            "last_seen_portal_version": 6,
            "last_seen_python_version": "3.12.7",
        },
    )

    report = version_snapshot.check_for_upgrade(path=snapshot_path)
    assert report["first_run"] is True
    assert report["changed"] == {}


def test_upgrade_notification_message() -> None:
    message = version_snapshot.upgrade_notification_message(
        {
            "changed": {
                "last_seen_kde_plasma_version": {"previous": "6.3.0", "current": "6.4.0"},
            },
            "current": {"last_seen_kde_plasma_version": "6.4.0"},
        }
    )
    assert message is not None
    assert "6.4.0" in message
    assert "nanoleaf-kde-sync-doctor" in message
