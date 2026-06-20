from __future__ import annotations

from pathlib import Path

INSTALLED_DOC_ROOT = Path("/usr/share/doc/nanoleaf-kde-sync")
GITHUB_DOCS_BASE = "https://github.com/SpinGiantCRM/Nanoleaf-Screen-Mirror-for-KDE/blob/main/docs"


def _sanitize_doc_name(name: str) -> str | None:
    candidate = Path(name).name
    if not candidate or candidate != name or ".." in name:
        return None
    if not candidate.endswith(".md"):
        return None
    return candidate


def resolve_user_doc(name: str) -> Path | None:
    safe_name = _sanitize_doc_name(name)
    if safe_name is None:
        return None
    repo_root = Path(__file__).resolve().parents[2]
    for candidate in (
        INSTALLED_DOC_ROOT / safe_name,
        repo_root / "docs" / safe_name,
    ):
        if candidate.is_file():
            return candidate
    return None


def user_doc_url(name: str) -> str | None:
    safe_name = _sanitize_doc_name(name)
    if safe_name is None:
        return None
    return f"{GITHUB_DOCS_BASE}/{safe_name}"
