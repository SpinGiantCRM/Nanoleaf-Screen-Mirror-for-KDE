from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
from pathlib import Path

_log = logging.getLogger(__name__)

_HELPER_HASH_NAME = ".helper_caps_hash"
_REQUIRED_CAPS = ("cap_sys_admin", "cap_sys_ptrace")


def helper_config_dir() -> Path:
    return Path.home() / ".config" / "nanoleaf-kde-sync"


def helper_hash_path() -> Path:
    return helper_config_dir() / _HELPER_HASH_NAME


def helper_binary_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_stored_helper_hash() -> str | None:
    path = helper_hash_path()
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def store_helper_hash(path: Path) -> None:
    helper_config_dir().mkdir(parents=True, exist_ok=True)
    helper_hash_path().write_text(helper_binary_sha256(path), encoding="utf-8")


def helper_has_required_caps(path: Path) -> bool:
    getcap = shutil.which("getcap")
    if getcap is None or not path.is_file():
        return False
    try:
        result = subprocess.run(
            [getcap, str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = (result.stdout or "").strip().lower()
    if not output:
        return False
    return all(cap in output for cap in _REQUIRED_CAPS)


def setcap_command_for(path: Path) -> str:
    return f"sudo setcap cap_sys_admin,cap_sys_ptrace+ep {path}"


def caps_required_for_helper(path: Path) -> bool:
    if os.environ.get("NANOLEAF_DRM_HELPER_SKIP_CAPS") == "1":
        return False
    resolved = path.resolve()
    for prefix in (Path("/usr/bin"), Path("/usr/lib"), Path("/usr/local/bin")):
        try:
            resolved.relative_to(prefix)
            return True
        except ValueError:
            continue
    return False


def ensure_helper_caps(
    helper_path: Path | None,
    *,
    show_dialog: bool = False,
) -> bool:
    if helper_path is None or not helper_path.is_file():
        return True
    if not caps_required_for_helper(helper_path):
        return True
    if helper_has_required_caps(helper_path):
        store_helper_hash(helper_path)
        return True

    current_hash = helper_binary_sha256(helper_path)
    stored_hash = read_stored_helper_hash()
    command = setcap_command_for(helper_path)
    if stored_hash == current_hash:
        _log.warning(
            "DRM helper binary is unchanged but capabilities are missing. Run: %s",
            command,
        )
        return False

    message = (
        "Nanoleaf DRM capture helper needs one-time capability setup after install/update.\n\n"
        f"Run this command once:\n{command}"
    )
    _log.warning("%s", message.replace("\n", " "))
    if show_dialog:
        try:
            from PyQt6.QtGui import QGuiApplication
            from PyQt6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance()
            created = False
            if app is None:
                app = QApplication([])
                created = True
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("Nanoleaf DRM Helper Setup")
            box.setText(message)
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.exec()
            if created:
                app.quit()
            _ = QGuiApplication
        except Exception:
            pass
    return False
