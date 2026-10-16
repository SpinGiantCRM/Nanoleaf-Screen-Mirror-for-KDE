"""Bounded native tray/USB lifecycle and client resource measurements.

Uses the native probe's brightness limit and restoration; never writes real config.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import signal
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


def children(pid: int):
    return [
        int(p)
        for p in (Path("/proc") / str(pid) / "task" / str(pid) / "children").read_text().split()
    ]


def window(pid: int, seconds: float):
    before = resources(pid)
    child_before = {p: resources(p) for p in children(pid)}
    start = time.monotonic()
    samples = []
    while time.monotonic() - start < seconds:
        samples.append(control("status"))
        time.sleep(0.05)
    after = resources(pid)
    child_after = {p: resources(p) for p in children(pid)}
    # A lifecycle window must be stable to attribute capture-child resource use.
    assert child_before.keys() == child_after.keys()
    elapsed = time.monotonic() - start
    return dict(
        seconds=elapsed,
        cpu_percent_one_core=(after["cpu_seconds"] - before["cpu_seconds"]) / elapsed * 100,
        before=before,
        after=after,
        capture_children_before=child_before,
        capture_children_after=child_after,
        capture_children_cpu_percent_one_core=sum(
            child_after[p]["cpu_seconds"] - child_before[p]["cpu_seconds"] for p in child_before
        )
        / elapsed
        * 100,
        samples=samples,
    )


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = control("status")
        if predicate(value):
            return value
        time.sleep(0.02)
    raise AssertionError(f"Native lifecycle condition timed out: {value}")


def wait_children_gone(pid, timeout=3):
    # Status is published before the capture child's asynchronous reap finishes.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not children(pid):
            return
        time.sleep(0.02)
    raise AssertionError("Owned capture child did not exit")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, default=Path("native/app/target/release/nanoleaf-native"))
    p.add_argument(
        "--config", type=Path, default=Path.home() / ".config/nanoleaf-kde-sync/config.toml"
    )
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--stream",
        action="store_true",
        help="Profile explicit portal/Vulkan capture and supervised worker failure",
    )
    args = p.parse_args()
    originals = {args.config: args.config.read_bytes()}
    capture_helper = args.binary.resolve().parent / "nanoleaf-native-capture"
    if not capture_helper.is_file():
        capture_helper = Path("native/stream-probe/target/release/nanoleaf-stream-probe")
    result = dict(
        capture_helper_sha256=(
            hashlib.sha256(capture_helper.read_bytes()).hexdigest() if args.stream else None
        ),
        scope=(
            "Real native tray, display-referred SDR capture and acknowledged USB; "
            "changing desktop, no optical/power measurement."
        ),
        streaming=args.stream,
        binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest(),
        instrumentation=(
            "20 Hz status polling; parent and stable capture-child CPU across their threads; "
            "compositor/GPU and separate settings UI excluded."
        ),
    )
    child = subprocess.Popen(
        # Local operator-selected native build, with separate argv and no shell.
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args  # noqa: E501
        [
            str(args.binary.resolve()),
            "--stream-live-probe" if args.stream else "--live-probe",
            str(args.config),
            "30",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                control("status")
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.02)
        wait_for(lambda s: s["frames"] > 0, timeout=15 if args.stream else 5)
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
        if args.stream:
            capture_pids = children(child.pid)
            assert len(capture_pids) == 1
            os.kill(capture_pids[0], signal.SIGTERM)
            failed = wait_for(
                lambda s: not s["running"] and "Screen sharing stopped" in s["message"]
            )
            assert child.poll() is None and not failed["preview"]
            wait_children_gone(child.pid)
            result["worker_failure_stopped_service"] = window(child.pid, 2)
            assert not children(child.pid)
            assert all(
                not s["running"] for s in result["worker_failure_stopped_service"]["samples"]
            )
            result["worker_failure_requires_explicit_restart"] = True
            control("start")
            wait_for(lambda s: s["running"] and s["frames"] > 0)
            result["worker_failure_recovery"] = window(child.pid, 2)
            capture_pids = children(child.pid)
            assert len(capture_pids) == 1
            stalled_at = time.monotonic()
            os.kill(capture_pids[0], signal.SIGSTOP)
            stalled = wait_for(
                lambda s: not s["running"] and "Screen sharing stopped" in s["message"],
                timeout=8,
            )
            result["worker_stall_to_stop_seconds"] = time.monotonic() - stalled_at
            assert child.poll() is None and not stalled["preview"]
            wait_children_gone(child.pid)
            result["worker_stall_stopped_service"] = window(child.pid, 1)
            assert not children(child.pid)
            assert all(
                not s["running"] and s["frames"] == stalled["frames"]
                for s in result["worker_stall_stopped_service"]["samples"]
            )
            result["worker_stall_requires_explicit_restart"] = True
            control("start")
            wait_for(lambda s: s["running"] and s["frames"] > 0)
            result["worker_stall_recovery"] = window(child.pid, 1)
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
            # Drain the report even on failure: waiting with unread PIPE output
            # can block a correctly stopped service while it writes diagnostics.
            stdout, stderr = child.communicate(timeout=35)
        else:
            stdout, stderr = child.communicate()
        # Keep failures as evidence too: a rejected compositor can stop before
        # the first ACK, yet still complete controller restoration on Quit.
        result["probe_exit_code"] = child.returncode
        result["probe_stderr"] = stderr
        try:
            result.setdefault("probe", json.loads(stdout))
        except json.JSONDecodeError:
            result["probe_report_unavailable"] = True
        result["configuration_preserved"] = all(
            path.read_bytes() == data for path, data in originals.items()
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        {
            key: value
            for key, value in result.items()
            if key
            not in {
                "active",
                "stopped",
                "restart",
                "probe",
                "worker_failure_stopped_service",
                "worker_failure_recovery",
                "worker_stall_stopped_service",
                "worker_stall_recovery",
            }
        }
    )
    print({key: result[key]["cpu_percent_one_core"] for key in ["active", "stopped", "restart"]})


if __name__ == "__main__":
    main()
