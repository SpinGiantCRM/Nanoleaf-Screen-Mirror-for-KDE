from __future__ import annotations

from pathlib import Path

from nanoleaf_sync.tools.flicker_lab import flicker_scenarios, run_flicker_lab
from nanoleaf_sync.tools.portal_tools import (
    forget_portal_restore_token,
    portal_restore_token_info,
)


def test_forget_portal_restore_token_removes_file(tmp_path: Path) -> None:
    token_path = tmp_path / "portal_token"
    token_path.write_text("saved-token", encoding="utf-8")
    result = forget_portal_restore_token(token_path=token_path)
    assert result["ok"] is True
    assert not token_path.exists()
    info = portal_restore_token_info(token_path=token_path)
    assert info["has_token"] is False


def test_forget_portal_restore_token_when_missing_is_ok(tmp_path: Path) -> None:
    token_path = tmp_path / "missing"
    result = forget_portal_restore_token(token_path=token_path)
    assert result["ok"] is True


def test_run_flicker_lab_all_scenarios_passes_by_default() -> None:
    result = run_flicker_lab(scenario_key="all")
    assert result["ok"] is True
    assert isinstance(result["scenarios"], list)
    assert len(result["scenarios"]) == len(flicker_scenarios())


def test_run_flicker_lab_unknown_scenario() -> None:
    result = run_flicker_lab(scenario_key="not-a-scenario")
    assert result["ok"] is False
