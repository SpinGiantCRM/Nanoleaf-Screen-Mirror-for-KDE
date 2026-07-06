from __future__ import annotations

from pathlib import Path

import pytest

from nanoleaf_sync.ui.tray_app import _resolve_user_doc, _user_doc_url


def test_resolve_user_doc_rejects_traversal() -> None:
    assert _resolve_user_doc("../etc/passwd") is None
    assert _resolve_user_doc("TROUBLESHOOTING.md/../../etc/passwd") is None


def test_resolve_user_doc_finds_repo_docs() -> None:
    path = _resolve_user_doc("TROUBLESHOOTING.md")
    assert path is not None
    assert path.is_file()
    assert path.name == "TROUBLESHOOTING.md"


def test_resolve_user_doc_installed_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc_root = tmp_path / "nanoleaf-kde-sync"
    doc_root.mkdir(parents=True)
    doc_file = doc_root / "TROUBLESHOOTING.md"
    doc_file.write_text("test")
    monkeypatch.setattr("nanoleaf_sync.ui.tray_app._INSTALLED_DOC_ROOT", doc_root)
    resolved = _resolve_user_doc("TROUBLESHOOTING.md")
    assert resolved == doc_file


def test_user_doc_url() -> None:
    url = _user_doc_url("TROUBLESHOOTING.md")
    assert url is not None
    assert url.endswith("/docs/TROUBLESHOOTING.md")
    assert _user_doc_url("../secrets.md") is None
