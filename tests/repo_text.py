from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_repo_text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def normalized_repo_text(relative: str) -> str:
    raw = read_repo_text(relative).replace('"', " ").replace("'", " ")
    return " ".join(raw.split())


def source_contains_all(relative: str, *fragments: str) -> bool:
    normalized = normalized_repo_text(relative)
    return all(fragment in normalized for fragment in fragments)
