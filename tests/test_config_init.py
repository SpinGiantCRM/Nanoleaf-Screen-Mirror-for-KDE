"""Tests for tools/config_init.py - config creation/reset CLI tool."""

from __future__ import annotations

from pathlib import Path

import pytest

import nanoleaf_sync.config.store as config_store
from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.tools.config_init import main


def test_main_creates_config_full_real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config_store, "default_config_path", lambda: path)
    result = main(["--mode", "full-real"])
    assert result == 0
    assert path.exists()
    cfg = ConfigManager(path=path).load()
    assert cfg.use_mock_capture is False
    assert cfg.prefer_backend == "auto"


def test_main_creates_config_diagnostic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config_store, "default_config_path", lambda: path)
    result = main(["--mode", "diagnostic"])
    assert result == 0
    assert path.exists()
    cfg = ConfigManager(path=path).load()
    assert cfg.use_mock_capture is True


def test_main_default_mode_is_full_real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config_store, "default_config_path", lambda: path)
    result = main([])
    assert result == 0
    cfg = ConfigManager(path=path).load()
    assert cfg.use_mock_capture is False


def test_main_warns_when_config_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("device_zone_count = 10\n", encoding="utf-8")
    monkeypatch.setattr(config_store, "default_config_path", lambda: path)
    result = main(["--mode", "full-real"])
    assert result == 0


def test_main_force_overwrites_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("device_zone_count = 10\n", encoding="utf-8")
    monkeypatch.setattr(config_store, "default_config_path", lambda: path)
    result = main(["--mode", "full-real", "--force"])
    assert result == 0
    # After force overwrite, the file should exist with the new config
    assert path.exists()


def test_main_output_format_full_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config_store, "default_config_path", lambda: path)
    result = main(["--mode", "full-real"])
    assert result == 0
    captured = capsys.readouterr().out
    assert "Wrote config:" in captured
    assert "Mode preset: full-real" in captured
    assert "Next:" in captured


def test_main_output_format_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config_store, "default_config_path", lambda: path)
    result = main(["--mode", "diagnostic"])
    assert result == 0
    captured = capsys.readouterr().out
    assert "Wrote config:" in captured
    assert "Mode preset: diagnostic" in captured
    assert "mock" in captured.lower()


def test_main_invalid_mode_exits_nonzero() -> None:
    with pytest.raises(SystemExit):
        main(["--mode", "bogus"])


def test_main_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    captured = capsys.readouterr().out
    assert "--mode" in captured
    assert "--force" in captured
    assert "Create or reset" in captured
