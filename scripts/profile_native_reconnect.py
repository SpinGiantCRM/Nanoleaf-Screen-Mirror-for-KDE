"""Bounded physical reconnect evidence. Uses private config only for input.

The native probe restores controller settings. File-backed output prevents report
backpressure from keeping the collector waiting. Human unplug/replug is required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

from profile_native_lifecycle import control


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, default=Path("native/app/target/release/nanoleaf-native"))
    p.add_argument(
        "--config", type=Path, default=Path.home() / ".config/nanoleaf-kde-sync/config.toml"
    )
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    before = args.config.read_bytes()
    rows = []
    initial = None
    lost = False
    resumed = False
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = args.output.with_suffix(".probe.json")
    error = args.output.with_suffix(".stderr.log")
    with raw.open("w") as stdout, error.open("w") as stderr:
        child = subprocess.Popen(
            [str(args.binary.resolve()), "--live-probe", str(args.config), "30"],
            stdout=stdout,
            stderr=stderr,
        )
        end = time.monotonic() + 45
        try:
            while child.poll() is None and time.monotonic() < end:
                try:
                    s = control("status")
                    rows.append(dict(time=time.monotonic(), status=s))
                    if s["frames"] > 0 and initial is None:
                        initial = s["reconnects"]
                        print("READY: unplug USB, wait three seconds and reconnect.", flush=True)
                    if initial is not None and (
                        "USB recovery" in s["message"] or "Waiting for strip" in s["message"]
                    ):
                        lost = True
                    if lost and s["reconnects"] > initial and s["message"] == "Mirroring":
                        resumed = True
                except (OSError, ValueError):
                    pass
                time.sleep(0.1)
            child.wait(timeout=3)
        finally:
            if child.poll() is None:
                control("quit")
                child.wait(timeout=8)
    probe = json.loads(raw.read_text())
    result = dict(
        exit_code=child.returncode,
        probe=probe,
        status_timeline=rows,
        usb_loss_detected=lost,
        acknowledged_output_resumed=resumed,
        config_unchanged=args.config.read_bytes() == before,
        config_sha256=hashlib.sha256(before).hexdigest(),
        binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    assert (
        result["config_unchanged"]
        and child.returncode == 0
        and probe["controller_power_brightness_restored"]
    )
    print({k: v for k, v in result.items() if k not in {"probe", "status_timeline"}})


if __name__ == "__main__":
    main()
