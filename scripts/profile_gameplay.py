"""Observe an existing native service without changing capture, output or game focus.

JSONL contains status/timing metadata and process resources, never pixel/RGB data.
Status polls are snapshots, not a complete frame trace; rolling percentiles overlap.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import time
from pathlib import Path


def status():
    path = Path(os.environ["XDG_RUNTIME_DIR"]) / "nanoleaf-native/control.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(2)
        stream.connect(str(path))
        peer_pid, _, _ = struct.unpack(
            "3i", stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )
        stream.sendall(b'{"action":"status"}\n')
        stream.shutdown(socket.SHUT_WR)
        data = bytearray()
        while chunk := stream.recv(16384):
            data.extend(chunk)
        return json.loads(data), peer_pid


def resources(pid):
    root = Path("/proc") / str(pid)
    fields = (root / "stat").read_text().rpartition(")")[2].split()
    return dict(
        pid=pid,
        start_ticks=int(fields[19]),
        cpu_seconds=(int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
        rss_kib=int(fields[21]) * os.sysconf("SC_PAGE_SIZE") // 1024,
        nice=int(fields[16]),
    )


def processes(service_pid):
    # Scope resources to the queried service and its capture children. A settings
    # window or an isolated bundle verifier can use the same executable name.
    root = Path("/proc") / str(service_pid)
    child_ids = (root / "task" / str(service_pid) / "children").read_text().split()
    result = []
    for pid in [service_pid, *map(int, child_ids)]:
        try:
            exe = (Path("/proc") / str(pid) / "exe").resolve().name
            if exe in ("nanoleaf-native", "nanoleaf-native-capture", "nanoleaf-stream-probe"):
                result.append(dict(executable=exe, **resources(pid)))
        except (OSError, ValueError, IndexError):
            continue  # Process may exit between directory and stat reads.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--label", default="uncontrolled-gameplay")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error("Use a bounded observation window of 1..3600 seconds")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    # Exclusive file creation avoids overwriting earlier evidence.
    with args.output.open("x") as output:
        while time.monotonic() - start < args.seconds:
            sample = dict(label=args.label, elapsed=time.monotonic() - start, unix=time.time())
            try:
                state, pid = status()
                sample.update(status=state, processes=processes(pid))
            except (OSError, ValueError) as error:
                sample["error"] = str(error)
            output.write(json.dumps(sample, separators=(",", ":")) + "\n")
            output.flush()
            time.sleep(1)


if __name__ == "__main__":
    main()
