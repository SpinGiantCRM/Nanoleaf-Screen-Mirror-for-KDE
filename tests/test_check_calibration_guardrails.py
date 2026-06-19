from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_calibration_guardrails.py"
GUARDRAILS_ARGV = ["check_calibration_guardrails.py", "--base", "a", "--head", "b"]


def _load_guardrails_module():
    spec = importlib.util.spec_from_file_location("check_calibration_guardrails", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_guardrails_passes_when_no_calibration_files_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_guardrails_module()
    monkeypatch.setattr(sys, "argv", GUARDRAILS_ARGV)
    monkeypatch.setattr(module, "_git_changed_files", lambda _base, _head: ["README.md"])
    assert module.main() == 0


def test_guardrails_passes_when_calibration_change_includes_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_guardrails_module()
    monkeypatch.setattr(sys, "argv", GUARDRAILS_ARGV)
    monkeypatch.setattr(
        module,
        "_git_changed_files",
        lambda _base, _head: [
            "src/nanoleaf_sync/runtime/anchor_calibration.py",
            "tests/test_calibration_state.py",
        ],
    )
    assert module.main() == 0


def test_guardrails_fails_when_calibration_changes_without_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_guardrails_module()
    monkeypatch.setattr(sys, "argv", GUARDRAILS_ARGV)
    monkeypatch.setattr(
        module,
        "_git_changed_files",
        lambda _base, _head: ["src/nanoleaf_sync/runtime/zone_derivation.py"],
    )
    assert module.main() == 1


def test_guardrails_skips_when_git_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_guardrails_module()
    monkeypatch.setattr(sys, "argv", GUARDRAILS_ARGV)

    def _raise(_base: str, _head: str) -> list[str]:
        raise RuntimeError("git diff failed")

    monkeypatch.setattr(module, "_git_changed_files", _raise)
    assert module.main() == 0


def test_guardrails_cli_invocation() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--base",
            "HEAD",
            "--head",
            "HEAD",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
