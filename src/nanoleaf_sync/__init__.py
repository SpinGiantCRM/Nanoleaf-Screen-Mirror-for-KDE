"""Nanoleaf Screen Mirror for KDE."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as metadata_version
from pathlib import Path


def _read_version() -> str:
    bundled = Path(__file__).resolve().parent / "VERSION"
    if bundled.is_file():
        text = bundled.read_text(encoding="utf-8").strip()
        if text:
            return text
    try:
        return metadata_version("nanoleaf-kde-sync")
    except PackageNotFoundError:
        return "0.0.0"


__version__ = _read_version()
