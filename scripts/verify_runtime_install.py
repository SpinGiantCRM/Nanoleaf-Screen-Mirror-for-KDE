#!/usr/bin/env python3
from __future__ import annotations

import inspect
import shutil
import sys
from importlib import resources
from pathlib import Path

import nanoleaf_sync
import nanoleaf_sync.ui.tray_app as tray_app

REQUIRED_COMMANDS = (
    "nanoleaf-kde-sync",
    "nanoleaf-kde-sync-service",
    "nanoleaf-kde-sync-doctor",
    "nanoleaf-kde-sync-smoke-test",
)


def _resource_exists(relative_path: str) -> bool:
    try:
        package_root = resources.files("nanoleaf_sync")
        return package_root.joinpath(*relative_path.split("/")).is_file()
    except Exception:
        return False


def main() -> int:
    package_path = Path(inspect.getfile(nanoleaf_sync)).resolve()
    version = str(getattr(nanoleaf_sync, "__version__", "") or "")
    tray_version = tray_app._read_app_version()
    missing_commands = [cmd for cmd in REQUIRED_COMMANDS if shutil.which(cmd) is None]
    missing_assets = [
        rel_path
        for rel_path in (
            "VERSION",
            "ui/style.qss",
            "assets/icons/hicolor/scalable/apps/nanoleaf-kde-sync.svg",
            "assets/udev/60-nanoleaf-kde-sync.rules",
        )
        if not _resource_exists(rel_path)
    ]

    print(f"module_path={package_path}")
    print(f"version={version}")
    print(f"tray_version={tray_version}")
    print(f"commands={','.join(REQUIRED_COMMANDS)}")
    print(f"missing_commands={','.join(missing_commands) or 'none'}")
    print(f"missing_assets={','.join(missing_assets) or 'none'}")

    if version and version != "0.0.0" and tray_version == version and not missing_assets:
        print("OK: installed runtime package metadata and assets are present.")
        if missing_commands:
            print(
                "WARN: console scripts are not on PATH; verify package installation path.",
                file=sys.stderr,
            )
        return 0

    print("FAIL: installed runtime package metadata/assets are incomplete.", file=sys.stderr)
    print("Run: ./scripts/reinstall_local.sh", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
