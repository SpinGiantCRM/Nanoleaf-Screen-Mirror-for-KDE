"""Bounded native tray/USB lifecycle and client resource measurements.

Uses the native probe's brightness limit and restoration; never writes real config.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import socket
import subprocess
import time
from pathlib import Path


def control(action: str, **fields):
    path = Path(os.environ["XDG_RUNTIME_DIR"]) / "nanoleaf-native/control.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(2)
        stream.connect(str(path))
        stream.sendall((json.dumps(dict(action=action, **fields)) + "\n").encode())
        stream.shutdown(socket.SHUT_WR)
        data = bytearray()
        while chunk := stream.recv(16384):
            data.extend(chunk)
        return json.loads(data)


def resources(pid: int):
    root = Path("/proc") / str(pid)
    fields = (root / "stat").read_text().rpartition(")")[2].split()
    ticks = os.sysconf("SC_CLK_TCK")
    memory = {}
    for line in (root / "smaps_rollup").read_text().splitlines():
        if line.startswith(("Rss:", "Pss:", "Private_Clean:", "Private_Dirty:")):
            key, value, *_ = line.split()
            memory[key.rstrip(":")] = int(value)
    return dict(
        cpu_seconds=(int(fields[11]) + int(fields[12])) / ticks,
        memory_kib=memory,
        fd_count=len(list((root / "fd").iterdir())),
    )


def window(pid: int, seconds: float):
    before = resources(pid)
    start = time.monotonic()
    samples = []
    while time.monotonic() - start < seconds:
        samples.append(control("status"))
        time.sleep(0.05)
    after = resources(pid)
    elapsed = time.monotonic() - start
    return dict(
        seconds=elapsed,
        cpu_percent_one_core=(after["cpu_seconds"] - before["cpu_seconds"]) / elapsed * 100,
        before=before,
        after=after,
        samples=samples,
    )


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = control("status")
        if predicate(value):
            return value
        time.sleep(0.02)
    raise AssertionError(f"Native lifecycle condition timed out: {value}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, default=Path("native/app/target/release/nanoleaf-native"))
    p.add_argument(
        "--config", type=Path, default=Path.home() / ".config/nanoleaf-kde-sync/config.toml"
    )
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    originals = {
        args.config: args.config.read_bytes(),
        Path.home() / ".local/share/applications/nanoleaf-kde-sync.desktop": (
            Path.home() / ".local/share/applications/nanoleaf-kde-sync.desktop"
        ).read_bytes(),
    }
    child = subprocess.Popen(
        [str(args.binary.resolve()), "--live-probe", str(args.config), "30"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    result = dict(
        scope=(
            "Real native tray, native-resolution KWin SDR capture and acknowledged USB; "
            "changing desktop, no optical/power measurement."
        ),
        binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest(),
        instrumentation=(
            "20 Hz status polling; process CPU summed across its threads; "
            "compositor/GPU and separate settings UI excluded."
        ),
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                control("status")
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.02)
        wait_for(lambda s: s["frames"] > 0)
        result["active"] = window(child.pid, 5)
        control("stop")
        stopped = wait_for(lambda s: not s["running"] and not s["preview"])
        frames = stopped["frames"]
        time.sleep(0.25)
        result["stopped"] = window(child.pid, 2)
        assert child.poll() is None
        assert all(s["frames"] == frames and not s["running"] for s in result["stopped"]["samples"])
        control("preview", rgb=[24, 0, 0], zone=7)
        preview = wait_for(lambda s: s["preview"] and s["frames"] > frames)
        assert not preview["running"]
        result["preview_exclusive"] = True
        control("stop")
        wait_for(lambda s: not s["preview"])
        control("start")
        restart = wait_for(lambda s: s["running"] and s["frames"] > 0 and s["reconnects"] > 1)
        result["restart"] = window(child.pid, 3)
        result["restart_open_count"] = restart["reconnects"]
        control("quit")
        stdout, stderr = child.communicate(timeout=8)
        if child.returncode:
            raise AssertionError(stderr)
        probe = json.loads(stdout)
        result["probe"] = probe
        assert probe["controller_power_brightness_restored"]
        result["stop_kept_tray_service_alive"] = True
    finally:
        if child.poll() is None:
            with contextlib.suppress(OSError):
                control("quit")
            child.wait(timeout=35)
        result["configuration_and_fallback_launcher_preserved"] = all(
            path.read_bytes() == data for path, data in originals.items()
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        {
            key: value
            for key, value in result.items()
            if key not in {"active", "stopped", "restart", "probe"}
        }
    )
    print({key: result[key]["cpu_percent_one_core"] for key in ["active", "stopped", "restart"]})


if __name__ == "__main__":
    main()
