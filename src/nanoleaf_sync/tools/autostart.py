from __future__ import annotations

import argparse

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
    parser.add_argument("--method", choices=("desktop", "systemd"), default="desktop")
    args = parser.parse_args(argv)

    if args.action == "enable":
        path = enable_autostart() if args.method == "desktop" else enable_systemd_autostart()
        print(f"Enabled autostart: {path}")
        return 0

    if args.action == "disable":
        removed = disable_autostart() if args.method == "desktop" else disable_systemd_autostart()
        target = user_autostart_path() if args.method == "desktop" else user_systemd_service_path()
        if removed:
            print(f"Disabled autostart: removed {target}")
        else:
            print(f"Autostart was already disabled: {target}")
        return 0

    path = user_autostart_path() if args.method == "desktop" else user_systemd_service_path()
    if path.exists():
        print(f"Autostart is enabled: {path}")
    else:
        print(f"Autostart is disabled: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
