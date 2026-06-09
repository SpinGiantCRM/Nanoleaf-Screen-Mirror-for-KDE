from __future__ import annotations

from pathlib import Path

from nanoleaf_sync.compat import kde_version


def test_parse_version_tuple_helpers() -> None:
    assert kde_version.format_version_tuple((6, 3, 1)) == "6.3.1"
    assert kde_version.format_version_tuple((0, 0, 0)) == "unknown"


def test_kwin_version_from_cli(monkeypatch) -> None:
    monkeypatch.setattr(
        kde_version,
        "_run_command",
        lambda args: "KWin 6.3.1" if args[0] == "kwin" else "",
    )
    assert kde_version.get_kwin_version() == (6, 3, 1)


def test_plasma_version_from_kdeglobals(tmp_path, monkeypatch) -> None:
    config_home = tmp_path / ".config"
    config_home.mkdir()
    (config_home / "kdeglobals").write_text(
        "[General]\nVersion=6.2.5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(kde_version, "_run_command", lambda _args: "")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert kde_version.get_plasma_version() == (6, 2, 5)
