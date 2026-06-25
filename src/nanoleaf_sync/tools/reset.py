from __future__ import annotations

import argparse
import subprocess  # nosec B404

from nanoleaf_sync.config.store import ConfigManager


def _stop_runtime_processes() -> None:
    for pattern in ("nanoleaf-kde-sync-service$", "nanoleaf-kde-sync$"):
        subprocess.run(  # nosec B603 B607
            ["pkill", "-f", pattern],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset nanoleaf-kde-sync state/config safely.")
    parser.add_argument(
        "scope",
        choices=("app-config", "calibration", "diagnostics"),
        help="Reset scope: full app config, calibration only, or diagnostics/cache only.",
    )
    parser.add_argument(
        "--stop-runtime",
        action="store_true",
        help="Stop tray/service processes before applying reset to avoid stale runtime state.",
    )
    args = parser.parse_args(argv)

    if args.stop_runtime:
        _stop_runtime_processes()

    mgr = ConfigManager()
    if args.scope == "app-config":
        cfg = mgr.reset_all_config()
        print(f"Reset full app config at {mgr.path} (strip_zones={cfg.device_zone_count}).")
        return 0
    if args.scope == "calibration":
        cfg = mgr.reset_calibration_only()
        print(
            "Reset calibration only at "
            f"{mgr.path} (anchors TL/TR/BR/BL="
            f"{cfg.corner_anchor_top_left}/{cfg.corner_anchor_top_right}/"
            f"{cfg.corner_anchor_bottom_right}/{cfg.corner_anchor_bottom_left})."
        )
        return 0
    cfg = mgr.reset_diagnostics_cache_only()
    print(
        "Reset diagnostics/cache only at "
        f"{mgr.path} (auto_probe_cache={cfg.auto_selected_backend or 'cleared'})."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
