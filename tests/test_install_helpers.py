from __future__ import annotations

import re
from pathlib import Path

from tests.install_parsers import (
    FORBIDDEN_RUNTIME_VERIFIER_SYMBOLS,
    REQUIRED_RUNTIME_VERIFIER_ASSETS,
    composite_action_run_blocks,
    parse_pkgbuild,
    parse_srcinfo,
    repo_path,
    runtime_verifier_checks_package_version,
    runtime_verifier_references_forbidden_symbols,
    runtime_verifier_required_assets,
    shell_contains_command,
    shell_non_comment_lines,
    workflow_step_runs,
)

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_install_verifier_uses_public_package_invariants() -> None:
    verifier = repo_path(ROOT, "scripts/verify_runtime_install.py")
    assert runtime_verifier_references_forbidden_symbols(verifier) == set()
    assert runtime_verifier_checks_package_version(verifier) is True
    assert runtime_verifier_required_assets(verifier) == REQUIRED_RUNTIME_VERIFIER_ASSETS


def test_arch_build_script_uses_runtime_install_verifier() -> None:
    script = repo_path(ROOT, "scripts/build_arch_package.sh")
    assert shell_contains_command(script, 'python "${SCRIPT_DIR}/verify_runtime_install.py"')
    text = script.read_text(encoding="utf-8")
    assert not any(symbol in text for symbol in FORBIDDEN_RUNTIME_VERIFIER_SYMBOLS)


def test_arch_publish_metadata_pins_source_checksum() -> None:
    pkgbuild_path = repo_path(ROOT, "packaging/arch/PKGBUILD")
    srcinfo_path = repo_path(ROOT, "packaging/arch/.SRCINFO")
    docs_path = repo_path(ROOT, "docs/PACKAGING_AUR.md")

    pkgbuild = parse_pkgbuild(pkgbuild_path)
    srcinfo = parse_srcinfo(srcinfo_path)
    pkgbuild_sums = tuple(str(value) for value in pkgbuild["sha256sums"])
    srcinfo_sum = srcinfo.get("sha256sums", "")

    assert pkgbuild_sums
    assert "SKIP" not in pkgbuild_sums
    assert srcinfo_sum != "SKIP"
    assert pkgbuild_sums[0] == srcinfo_sum
    assert re.fullmatch(r"[0-9a-f]{64}", pkgbuild_sums[0]) is not None

    docs = docs_path.read_text(encoding="utf-8")
    assert "Do not publish AUR metadata with `sha256sums=('SKIP')`" in docs
    assert "v1.0.0 note" not in docs


def test_arch_metadata_action_diffs_generated_srcinfo() -> None:
    action = repo_path(ROOT, ".github/actions/arch-metadata-validation/action.yml")
    blocks = composite_action_run_blocks(action)
    combined = "\n".join(blocks)
    assert "makepkg --printsrcinfo > /tmp/nanoleaf-kde-sync.SRCINFO" in combined
    assert "diff -u .SRCINFO /tmp/nanoleaf-kde-sync.SRCINFO" in combined


def test_release_gate_runs_runtime_verifier_and_lints_scripts() -> None:
    script = repo_path(ROOT, "scripts/release_gate.sh")
    lines = shell_non_comment_lines(script)
    assert 'export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"' in lines
    assert "python scripts/verify_runtime_install.py" in lines
    assert "ruff check src/ tests/ scripts/" in lines
    assert "ruff format --check src/ tests/ scripts/" in lines


def test_ci_runs_runtime_verifier_and_lints_scripts() -> None:
    workflow = repo_path(ROOT, ".github/workflows/ci.yml")
    runs = workflow_step_runs(workflow)
    assert "python scripts/verify_runtime_install.py" in runs
    assert "ruff check src/ tests/ scripts/" in runs
    assert "ruff format --check src/ tests/ scripts/" in runs


def test_weekly_ci_runs_runtime_verifier_and_lints_scripts() -> None:
    workflow = repo_path(ROOT, ".github/workflows/ci-weekly.yml")
    runs = workflow_step_runs(workflow)
    assert "python scripts/verify_runtime_install.py" in runs
    assert "ruff check src/ tests/ scripts/" in runs
    assert "ruff format --check src/ tests/ scripts/" in runs


def test_arch_build_manual_install_hint_uses_pkgbuild_pkgrel() -> None:
    script = repo_path(ROOT, "scripts/build_arch_package.sh")
    text = script.read_text(encoding="utf-8")
    assert 'PKGREL="$(awk -F= ' in text
    assert "nanoleaf-kde-sync-${PKGVER}-${PKGREL}-$(uname -m).pkg.tar.zst" in text
    assert "nanoleaf-kde-sync-${PKGVER}-1-$(uname -m).pkg.tar.zst" not in text


def test_install_local_fix_aliases_maintained_reinstall_script() -> None:
    script = repo_path(ROOT, "scripts/install_local_fix.sh")
    lines = shell_non_comment_lines(script)
    assert 'exec "${SCRIPT_DIR}/reinstall_local.sh"' in lines
    combined = "\n".join(lines)
    assert "makepkg" not in combined
    assert "sudo pacman" not in combined
