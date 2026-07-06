from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_validate_wheel() -> ModuleType:
    module_path = ROOT / "scripts" / "validate_wheel.py"
    spec = importlib.util.spec_from_file_location("validate_wheel_script", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_minimal_wheel(
    path: Path,
    *,
    filename_tag: str = "cp311-cp311-linux_x86_64",
    metadata_tag: str = "cp311-cp311-linux_x86_64",
    include_helper: bool = True,
    helper_bytes: bytes = b"\x7fELFplaceholder",
) -> Path:
    dist_info = "nanoleaf_kde_sync-1.9.3.dist-info"
    purelib = "nanoleaf_kde_sync-1.9.3.data/purelib/nanoleaf_sync"
    wheel_path = path / f"nanoleaf_kde_sync-1.9.3-{filename_tag}.whl"
    scripts = {
        "nanoleaf-kde-sync",
        "nanoleaf-kde-sync-autostart",
        "nanoleaf-kde-sync-benchmark",
        "nanoleaf-kde-sync-doctor",
        "nanoleaf-kde-sync-init-config",
        "nanoleaf-kde-sync-reset",
        "nanoleaf-kde-sync-service",
        "nanoleaf-kde-sync-setup-permissions",
        "nanoleaf-kde-sync-smoke-test",
    }
    entry_points = "[console_scripts]\n" + "\n".join(
        f"{name}=nanoleaf_sync.__init__:main" for name in sorted(scripts)
    )

    with zipfile.ZipFile(wheel_path, "w") as archive:
        archive.writestr(f"{dist_info}/WHEEL", f"Wheel-Version: 1.0\nTag: {metadata_tag}\n")
        archive.writestr(f"{dist_info}/entry_points.txt", f"{entry_points}\n")
        archive.writestr(f"{purelib}/__init__.py", "")
        archive.writestr(f"{purelib}/VERSION", "1.9.3\n")
        archive.writestr(f"{purelib}/ui/style.qss", "")
        archive.writestr(
            f"{purelib}/assets/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg",
            "<svg />\n",
        )
        archive.writestr(f"{purelib}/assets/udev/60-nanoleaf-kde-sync.rules", "")
        if include_helper:
            archive.writestr(f"{purelib}/capture/nanoleaf_drm_helper", helper_bytes)
    return wheel_path


def test_validate_wheel_accepts_platform_wheel_with_required_assets(tmp_path: Path) -> None:
    validator = _load_validate_wheel()
    wheel_path = _write_minimal_wheel(tmp_path)

    validator.validate_wheel(wheel_path)


def test_validate_wheel_rejects_any_platform_tag(tmp_path: Path) -> None:
    validator = _load_validate_wheel()
    wheel_path = _write_minimal_wheel(
        tmp_path,
        filename_tag="py3-none-linux_x86_64",
        metadata_tag="py3-none-any",
    )

    with pytest.raises(SystemExit):
        validator.validate_wheel(wheel_path)


def test_validate_wheel_rejects_missing_drm_helper(tmp_path: Path) -> None:
    validator = _load_validate_wheel()
    wheel_path = _write_minimal_wheel(tmp_path, include_helper=False)

    with pytest.raises(SystemExit):
        validator.validate_wheel(wheel_path)


def test_validate_wheel_rejects_non_elf_drm_helper(tmp_path: Path) -> None:
    validator = _load_validate_wheel()
    wheel_path = _write_minimal_wheel(tmp_path, helper_bytes=b"not an elf")

    with pytest.raises(SystemExit):
        validator.validate_wheel(wheel_path)
