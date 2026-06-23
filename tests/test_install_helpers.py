from __future__ import annotations

from tests.repo_text import read_repo_text


def test_runtime_install_verifier_uses_public_package_invariants() -> None:
    text = read_repo_text("scripts/verify_runtime_install.py")
    assert "_LOW_LIGHT_HOLD_PEAK" not in text
    assert "_HUE_STABLE_MIN_CHROMA" not in text
    assert "apply_output_quantization_hold" not in text
    assert "__version__" in text
    assert "ui/style.qss" in text
    assert "assets/udev/60-nanoleaf-kde-sync.rules" in text


def test_arch_build_script_uses_runtime_install_verifier() -> None:
    text = read_repo_text("scripts/build_arch_package.sh")
    assert 'python "${SCRIPT_DIR}/verify_runtime_install.py"' in text
    assert "_LOW_LIGHT_HOLD_PEAK" not in text


def test_arch_publish_metadata_pins_source_checksum() -> None:
    pkgbuild = read_repo_text("packaging/arch/PKGBUILD")
    srcinfo = read_repo_text("packaging/arch/.SRCINFO")
    docs = read_repo_text("docs/PACKAGING_AUR.md")

    assert "sha256sums=('SKIP')" not in pkgbuild
    assert "\tsha256sums = SKIP" not in srcinfo
    assert "c4206cff52f471cd3e57259d29680c6606f628c9cd423e7529f17dbc60278610" in pkgbuild
    assert "c4206cff52f471cd3e57259d29680c6606f628c9cd423e7529f17dbc60278610" in srcinfo
    assert "Do not publish AUR metadata with `sha256sums=('SKIP')`" in docs
    assert "v1.0.0 note" not in docs


def test_arch_metadata_action_diffs_generated_srcinfo() -> None:
    text = read_repo_text(".github/actions/arch-metadata-validation/action.yml")
    assert "makepkg --printsrcinfo > /tmp/nanoleaf-kde-sync.SRCINFO" in text
    assert "diff -u .SRCINFO /tmp/nanoleaf-kde-sync.SRCINFO" in text


def test_release_gate_runs_runtime_verifier_and_lints_scripts() -> None:
    text = read_repo_text("scripts/release_gate.sh")
    assert 'export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"' in text
    assert "python scripts/verify_runtime_install.py" in text
    assert "ruff check src/ tests/ scripts/" in text
    assert "ruff format --check src/ tests/ scripts/" in text


def test_ci_runs_runtime_verifier_and_lints_scripts() -> None:
    text = read_repo_text(".github/workflows/ci.yml")
    assert "python scripts/verify_runtime_install.py" in text
    assert "ruff check src/ tests/ scripts/" in text
    assert "ruff format --check src/ tests/ scripts/" in text


def test_weekly_ci_runs_runtime_verifier_and_lints_scripts() -> None:
    text = read_repo_text(".github/workflows/ci-weekly.yml")
    assert "python scripts/verify_runtime_install.py" in text
    assert "ruff check src/ tests/ scripts/" in text
    assert "ruff format --check src/ tests/ scripts/" in text


def test_arch_build_manual_install_hint_uses_pkgbuild_pkgrel() -> None:
    text = read_repo_text("scripts/build_arch_package.sh")
    assert 'PKGREL="$(awk -F= ' in text
    assert "nanoleaf-kde-sync-${PKGVER}-${PKGREL}-$(uname -m).pkg.tar.zst" in text
    assert "nanoleaf-kde-sync-${PKGVER}-1-$(uname -m).pkg.tar.zst" not in text


def test_install_local_fix_aliases_maintained_reinstall_script() -> None:
    text = read_repo_text("scripts/install_local_fix.sh")
    assert 'exec "${SCRIPT_DIR}/reinstall_local.sh"' in text
    assert "makepkg" not in text
    assert "sudo pacman" not in text
