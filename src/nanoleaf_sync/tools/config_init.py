from __future__ import annotations

import argparse

from nanoleaf_sync.config.store import ConfigManager


def _mode_help() -> str:
    return (
        "full-real (real capture + real USB device, default), "
        "diagnostic (mock capture + real USB device)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create or reset ~/.config/nanoleaf-kde-sync/config.json"
    )
    parser.add_argument(
        "--mode",
        default="full-real",
        choices=["full-real", "diagnostic"],
        help=f"Preset mode: {_mode_help()}",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing config file.",
    )
    args = parser.parse_args(argv)

    mgr = ConfigManager()
    created = mgr.initialize(mode=args.mode, force=args.force)

    if not created:
        print(f"Config already exists: {mgr.path}")
        print("No changes were made. Re-run with --force to overwrite.")
        return 0

    cfg = mgr.load()
    print(f"Wrote config: {mgr.path}")
    print(f"Mode preset: {args.mode}")
    print(
        "Capture mode: "
        + ("mock" if cfg.use_mock_capture else cfg.prefer_backend)
        + " | Device mode: "
        + "real-usb"
    )

    if args.mode == "full-real":
        print(
            "Reminder: verify device_pid (0x8201 dock or 0x8202 strip) and run "
            "nanoleaf-kde-sync-doctor --device."
        )

    print("Next: run nanoleaf-kde-sync-doctor, then nanoleaf-kde-sync-smoke-test.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
