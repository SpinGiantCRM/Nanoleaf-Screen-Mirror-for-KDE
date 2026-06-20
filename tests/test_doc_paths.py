from __future__ import annotations

from pathlib import Path

import pytest

from nanoleaf_sync.doc_paths import resolve_user_doc, user_doc_url


def test_resolve_user_doc_rejects_traversal() -> None:
    assert resolve_user_doc("../etc/passwd") is None
    assert resolve_user_doc("TROUBLESHOOTING.md/../../etc/passwd") is None


def test_resolve_user_doc_finds_repo_docs() -> None:
    path = resolve_user_doc("TROUBLESHOOTING.md")
    assert path is not None
    assert path.is_file()
    assert path.name == "TROUBLESHOOTING.md"


def test_resolve_user_doc_installed_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc_root = tmp_path / "share" / "doc" / "nanoleaf-kde-sync"
    doc_root.mkdir(parents=True)
    guide = doc_root / "TROUBLESHOOTING.md"
    guide.write_text("# test", encoding="utf-8")
    monkeypatch.setattr("nanoleaf_sync.doc_paths.INSTALLED_DOC_ROOT", doc_root)
    resolved = resolve_user_doc("TROUBLESHOOTING.md")
    assert resolved == guide


def test_user_doc_url() -> None:
    url = user_doc_url("TROUBLESHOOTING.md")
    assert url is not None
    assert url.endswith("/docs/TROUBLESHOOTING.md")
    assert user_doc_url("../secrets.md") is None
