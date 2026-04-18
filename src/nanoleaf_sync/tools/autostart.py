from __future__ import annotations

import argparse

from nanoleaf_sync.desktop_entry import (
    disable_autostart,
    enable_autostart,
    user_autostart_path,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage nanoleaf-kde-sync desktop autostart.")
    parser.add_argument("action", choices=("enable", "disable", "status"))
    args = parser.parse_args(argv)

    if args.action == "enable":
        path = enable_autostart()
        print(f"Enabled autostart: {path}")
        return 0

    if args.action == "disable":
        removed = disable_autostart()
        if removed:
            print(f"Disabled autostart: removed {user_autostart_path()}")
        else:
            print(f"Autostart was already disabled: {user_autostart_path()}")
        return 0

    path = user_autostart_path()
    if path.exists():
        print(f"Autostart is enabled: {path}")
    else:
        print(f"Autostart is disabled: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
