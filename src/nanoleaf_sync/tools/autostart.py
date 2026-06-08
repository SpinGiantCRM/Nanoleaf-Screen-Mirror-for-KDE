from __future__ import annotations

import argparse
import logging
import subprocess

logger = logging.getLogger(__name__)

from nanoleaf_sync.desktop_entry import (
    disable_autostart,
    disable_systemd_autostart,
    enable_autostart,
    enable_systemd_autostart,
    user_systemd_service_path,
    user_autostart_path,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage nanoleaf-kde-sync desktop autostart.")
    parser.add_argument("action", choices=("enable", "disable", "status"))
    parser.add_argument(
        "--method",
        choices=("desktop", "systemd"),
        default="desktop",
        help="Autostart method. Use desktop for KWin ScreenShot2 authorization; systemd may miss desktop-session DBus authorization context.",
    )
    args = parser.parse_args(argv)

    if args.action == "enable":
        path = enable_autostart() if args.method == "desktop" else enable_systemd_autostart()
        print(f"Enabled autostart: {path}")
        if args.method == "systemd":
            print(
                "WARNING: systemd --user autostart can fail KWin ScreenShot2 authorization because it "
                "may not inherit desktop-entry launch context. Prefer `--method desktop` for reliable capture."
            )
        return 0

    if args.action == "disable":
        removed = disable_autostart() if args.method == "desktop" else disable_systemd_autostart()
        target = user_autostart_path() if args.method == "desktop" else user_systemd_service_path()
        if removed:
            print(f"Disabled autostart: removed {target}")
        else:
            print(f"Autostart was already disabled: {target}")
        return 0

    if args.method == "systemd":
        path = user_systemd_service_path()
        unit = path.name
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-enabled", unit],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            state = (result.stdout or "").strip() or (result.stderr or "").strip() or "disabled"
        except Exception:
            logger.debug("Unable to query systemd autostart state", exc_info=True)
            state = "unknown"
        if state == "enabled":
            print(f"Autostart is enabled: {unit}")
        else:
            print(f"Autostart is {state}: {unit}")
        return 0

    path = user_autostart_path()
    if path.exists():
        print(f"Autostart is enabled: {path}")
    else:
        print(f"Autostart is disabled: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
