"""Bounded ABBA capture-rate comparison on the same synthetic SDR workload.

Operator tool: requires a built capture_scene, installed native app/helper pair,
one selected monitor, and no running native app. Writes only a new evidence
directory. Uses the live probe's exclusive USB lease, low brightness and verified
controller restoration. Paint requests and software ages are not optical latency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import statistics
import subprocess
import time
from pathlib import Path

from profile_native_lifecycle import children, control, resources


def distribution(values):
    values = sorted(values)
    assert values
    return {
        f"p{percent}": values[math.ceil(len(values) * percent / 100) - 1]
        for percent in (50, 95, 99)
    }


def main():
    if not __debug__:
        raise RuntimeError("Run without -O: operator safety/evidence assertions are required")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--scene", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seconds", type=int, default=12, choices=range(8, 31))
    parser.add_argument("--rates", type=int, nargs=2, default=[60, 120])
    parser.add_argument("--pattern", choices=["ramp", "steps"], default="ramp")
    parser.add_argument("--strace", type=Path)
    parser.add_argument("--hidraw", type=Path)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if bool(args.strace) != bool(args.hidraw):
        parser.error("Supply both --strace and --hidraw for paint-to-USB timing")
    if args.strace and args.pattern != "steps":
        parser.error("USB tracing is only for the controlled static step workload")
    assert all(1 <= rate <= 240 for rate in args.rates)
    order = [*args.rates, *reversed(args.rates)]
    if not args.run:
        print(
            json.dumps(
                {
                    "plan_only": True,
                    "rates_abba": order,
                    "seconds_per_probe": args.seconds,
                    "pattern": args.pattern,
                    "note": (
                        "Covers the sole selected monitor with a bounded grey ramp and drives "
                        "the strip at test brightness. No real config writes."
                    ),
                }
            )
        )
        return
    assert (
        subprocess.run(["pgrep", "-x", "nanoleaf-native"], capture_output=True).returncode == 1
    ), "Quit the native tray first"
    binary, scene = args.binary.resolve(strict=True), args.scene.resolve(strict=True)
    if args.strace:
        args.strace = args.strace.resolve(strict=True)
        assert stat.S_ISCHR(args.hidraw.stat().st_mode), (
            "A real hidraw character device is required"
        )
    original = args.config.read_bytes()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = os.environ.copy()
    for key in [
        "NANOLEAF_STREAM_PARITY",
        "NANOLEAF_VULKAN_VALIDATE",
        "NANOLEAF_EXPLICIT_SYNC",
        "NANOLEAF_PRECISE_CACHE_TIMING",
        "NANOLEAF_BATCH_GPU_WAITS",
    ]:
        env.pop(key, None)
    results = []
    for index, rate in enumerate(order):
        prefix = args.output / f"{index + 1}-{rate}"
        config = prefix.with_suffix(".toml")
        content, replaced = re.subn(
            rb"(?m)^fps[ \t]*=[ \t]*\d+[ \t]*$", f"fps = {rate}".encode(), original, count=1
        )
        assert replaced == 1, "Existing top-level FPS setting required"
        config.write_bytes(content)
        config.chmod(0o600)
        print(f"Starting controlled run {index + 1}/4, existing Target FPS={rate}", flush=True)
        with (
            prefix.with_suffix(".scene.json").open("w") as scene_out,
            prefix.with_suffix(".scene.stderr").open("w") as scene_err,
        ):
            workload = subprocess.Popen(
                [str(scene), str(config), str(args.seconds + 3), args.pattern],
                stdout=scene_out,
                stderr=scene_err,
                env=env,
            )
            try:
                time.sleep(0.75)
                assert workload.poll() is None, "Scene did not stay open"
                with (
                    prefix.with_suffix(".raw.json").open("w") as out,
                    prefix.with_suffix(".stderr").open("w") as err,
                ):
                    command = [str(binary), "--stream-live-probe", str(config), str(args.seconds)]
                    if args.strace:
                        command = [
                            str(args.strace),
                            "-ttt",
                            "-T",
                            "-xx",
                            "-s",
                            "256",
                            "-e",
                            "trace=write",
                            "-P",
                            str(args.hidraw),
                            "-o",
                            str(prefix.with_suffix(".hid.trace")),
                            "--",
                            *command,
                        ]
                    probe = subprocess.Popen(
                        command,
                        stdout=out,
                        stderr=err,
                        env=env,
                    )
                    snapshots = []
                    baseline = last = None
                    try:
                        while probe.poll() is None:
                            try:
                                status = control("status")
                                if status["running"] and status["frames"] >= 75:
                                    actor = children(probe.pid)[0] if args.strace else probe.pid
                                    procs = {
                                        pid: resources(pid) for pid in [actor, *children(actor)]
                                    }
                                    point = (time.monotonic(), procs)
                                    baseline = baseline or point
                                    last = point
                                    snapshots.append(
                                        sum(v["memory_kib"]["Pss"] for v in procs.values())
                                    )
                            except (OSError, KeyError, json.JSONDecodeError):
                                pass
                            time.sleep(0.1)
                        assert probe.wait() == 0, prefix.with_suffix(".stderr").read_text()
                    finally:
                        if probe.poll() is None:
                            # Let the actor perform acknowledged cleanup/restoration.
                            control("quit")
                            probe.wait(timeout=10)
                assert workload.wait(timeout=5) == 0
            finally:
                if workload.poll() is None:
                    workload.terminate()
                    workload.wait(timeout=5)
        raw = json.loads(prefix.with_suffix(".raw.json").read_text())
        scene_result = json.loads(prefix.with_suffix(".scene.json").read_text())
        assert scene_result["completed"], "Scene closed early; comparison invalid"
        assert scene_result["invalid_viewport_paints_after_warmup"] == 0, (
            "Scene lost focus/fullscreen or was obscured/minimized; comparison invalid"
        )
        # A single scheduling hitch is part of a real compositor workload; keep
        # its maximum gap in the result rather than selecting only ideal runs.
        # Reject sustained throttling/occlusion, which changes the workload.
        assert scene_result["unique_logical_ticks"] >= (
            0.95 * scene_result["logical_hz"] * (args.seconds + 3)
        ), "Scene missed more than 5% of logical updates; comparison invalid"
        assert raw["controller_power_brightness_restored"], "Controller restoration failed"
        assert args.config.read_bytes() == original, "Real config changed"
        assert baseline and last and baseline[1].keys() == last[1].keys()
        elapsed = last[0] - baseline[0]
        # Probe records every ACK. Discard startup, preview and cached-work
        # samples; never combine the different fresh/cached clock origins.
        rows = [
            s
            for s in raw["samples"]
            if s["frames"] >= 75
            and not s["last_source_reused"]
            and s["response_clock"] == "capture-work"
        ]
        assert len({s["frames"] for s in rows}) == len(rows)
        if args.pattern == "ramp":
            assert len(rows) >= 100
        resets = []
        previous_age = None
        for sample in raw["samples"]:
            age = sample["source_presentation_age_ms"]
            # Includes cached-work packets representing the NEW source. Such a
            # packet may overwrite its fresh predecessor before the next USB
            # opportunity. Do not measure only packets labelled fresh.
            if age is not None and previous_age is not None and previous_age > 500 and age < 100:
                resets.append(age)
            previous_age = age
        resets = resets[2:]  # Exclude two startup transitions uniformly by scene.
        # KWin may refresh timestamps without changing pixels. Age resets are
        # diagnostics only; only payload-matched tracing measures scene changes.
        result = {
            "target_fps": rate,
            "pattern": args.pattern,
            "fresh_ack_samples": len(rows),
            "software_ms": {
                key: distribution([s[key] for s in rows]) if rows else None
                for key in [
                    "capture_ms",
                    "processing_ms",
                    "prepared_queue_ms",
                    "usb_ms",
                    "response_to_write_ms",
                    "response_ms",
                    "source_presentation_age_ms",
                ]
            },
            "cpu_percent_one_core_app_and_helper": sum(
                last[1][pid]["cpu_seconds"] - value["cpu_seconds"]
                for pid, value in baseline[1].items()
            )
            / elapsed
            * 100,
            "pss_median_kib_app_and_helper": statistics.median(snapshots),
            "measured_resource_seconds": elapsed,
            "controller_restored": True,
            "real_config_byte_identical": True,
            "scene": scene_result,
            "presentation_timestamp_reset_diagnostics_ms": {
                "scope": (
                    "First acknowledged packet with presentation-age reset below 100 ms "
                    "after a packet above 500 ms, including cached-work packets; no evidence "
                    "of changed "
                    "pixels; first two detected transitions excluded. Software metadata, "
                    "not paint-to-light or image-content verification."
                ),
                "samples": len(resets),
                "values": resets,
                "distribution": distribution(resets) if resets else None,
            },
        }
        if args.strace:
            from step_response_trace import analyse

            preflight = json.loads(
                subprocess.check_output([str(binary), "--preflight", str(config)])
            )
            result["paint_to_usb"] = analyse(
                prefix.with_suffix(".hid.trace").read_text(),
                scene_result,
                preflight["manual_strip_zones"],
                raw["status"]["frames"],
            )
        results.append(result)
        (args.output / "summary.json").write_text(
            json.dumps(
                {
                    "scope": (
                        f"Same synthetic neutral SDR {args.pattern}. ABBA Target FPS comparison; "
                        "every fresh ACK after 75-frame warmup. Software clocks only, not optical "
                        "response. CPU/PSS excludes compositor, scene, GPU and power. Other "
                        "desktop/GPU workloads remain uncontrolled."
                    ),
                    "app_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                    "helper_sha256": hashlib.sha256(
                        binary.with_name("nanoleaf-native-capture").read_bytes()
                    ).hexdigest(),
                    "scene_sha256": hashlib.sha256(scene.read_bytes()).hexdigest(),
                    "strace_sha256": (
                        hashlib.sha256(args.strace.read_bytes()).hexdigest()
                        if args.strace
                        else None
                    ),
                    "runs": results,
                },
                indent=2,
            )
            + "\n"
        )
        print(json.dumps(result), flush=True)
    assert subprocess.run(["pgrep", "-x", "nanoleaf-native"], capture_output=True).returncode == 1
    assert args.config.read_bytes() == original


if __name__ == "__main__":
    main()
