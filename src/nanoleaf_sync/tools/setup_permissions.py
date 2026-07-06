"""Install udev rules and print DRM helper setcap guidance."""

from __future__ import annotations

import argparse
import shutil
import subprocess  # nosec B404
import sys
from importlib import resources
from pathlib import Path


def _bundled_udev_rules() -> Path:
    with resources.as_file(
        resources.files("nanoleaf_sync").joinpath("assets/udev/60-nanoleaf-kde-sync.rules")
    ) as bundled:
        return Path(bundled)


def _helper_path() -> Path | None:
    from nanoleaf_sync.capture._drm_helper_bridge import _helper_binary_path

    return _helper_binary_path()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Nanoleaf USB/DRM permissions helpers.")
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print commands without attempting privileged installs.",
    )
    args = parser.parse_args(argv)

    rules_src = _bundled_udev_rules()
    rules_dest = Path("/etc/udev/rules.d/60-nanoleaf-kde-sync.rules")
    print(f"Udev rules source: {rules_src}")
    print(f"Udev rules target: {rules_dest}")
    if args.print_only:
        print(f"sudo install -m 0644 {rules_src} {rules_dest}")
        print("sudo udevadm control --reload-rules && sudo udevadm trigger")
    else:
        try:
            subprocess.run(  # nosec B603 B607
                ["sudo", "install", "-m", "0644", str(rules_src), str(rules_dest)],
                check=True,
            )
            subprocess.run(  # nosec B603 B607
                ["sudo", "udevadm", "control", "--reload-rules"],
                check=True,
            )
            subprocess.run(  # nosec B603 B607
                ["sudo", "udevadm", "trigger"],
                check=True,
            )
            print("Installed udev rules.")
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"Could not install udev rules automatically: {exc}")
            print(f"Run manually: sudo install -m 0644 {rules_src} {rules_dest}")

    helper = _helper_path()
    if helper is not None:
        from nanoleaf_sync.tools.setcap_helper import (
            caps_required_for_helper,
            helper_has_required_caps,
            setcap_command_for,
        )

        print(f"DRM helper: {helper}")
        if caps_required_for_helper(helper) and not helper_has_required_caps(helper):
            print(f"DRM helper capabilities required. Run:\n  {setcap_command_for(helper)}")
        elif not caps_required_for_helper(helper):
            print("DRM helper setcap not required for this install path.")
        else:
            print("DRM helper capabilities look OK.")
    else:
        print("DRM helper binary not found in package.")

    if (
        shutil.which("getent")
        and subprocess.run(  # nosec B603 B607
            ["getent", "group", "plugdev"],
            check=False,
        ).returncode
        != 0
    ):
        print('Optional: sudo groupadd plugdev && sudo usermod -aG plugdev "$USER"')
    print("Reconnect the Nanoleaf strip and log out/in if permissions were just installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
