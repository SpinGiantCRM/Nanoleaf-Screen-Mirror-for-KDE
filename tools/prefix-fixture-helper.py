#!/usr/bin/env python3
"""Generated worker fixture for prefix transport; NO capture/GPU/calibration.

Use only beside a COPIED app in a private operator test directory. Never install
this as a real capture helper. The app's bounded probe owns/restores actual HID.
Optional event timestamps contain only generated states, never user config/RGB.
"""

import contextlib
import json
import os
import sys
import threading
import time
from pathlib import Path


def main():
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("Private operator fixture requires --worker")
    line = sys.stdin.readline(1_048_577)
    if len(line) > 1_048_576:
        raise ValueError("Oversized config")
    count = json.loads(line)["device_zone_count"]
    if count != 48:
        raise ValueError("This controlled fixture requires manual48")
    mode = os.environ.get("NANOLEAF_PREFIX_FIXTURE", "integer")
    if mode not in {"integer", "fractional", "full"}:
        raise ValueError("Unknown fixture")
    events = os.environ.get("NANOLEAF_PREFIX_EVENTS")
    stop = threading.Event()

    def feedback():
        for line in sys.stdin:
            if len(line) > 32768:
                break
        stop.set()

    threading.Thread(target=feedback, daemon=True).start()
    began = time.monotonic()
    deadline = began
    previous = None
    with contextlib.ExitStack() as stack:
        sink = stack.enter_context(Path(events).open("x")) if events else None
        while not stop.is_set() and time.monotonic() - began < 35:
            high = int((time.monotonic() - began) / 0.137) % 2
            mono, unix = time.monotonic_ns(), time.time_ns()
            if high != previous and sink:
                sink.write(json.dumps({"monotonic_ns": mono, "unix_ns": unix, "high": high}) + "\n")
                sink.flush()
            previous = high
            raw = [[8.0, 8.0, 8.0] for _ in range(count)]
            for i in range(count if mode == "full" else count // 4):
                raw[i] = [64.0 if high else 8.0] * 3
            if mode == "fractional":
                raw[-1] = [8.25, 8.25, 8.25]
            print(
                json.dumps(
                    {
                        "schema": 3,
                        "colors": [[round(v) for v in rgb] for rgb in raw],
                        "unquantized_rgb": raw,
                        "times": {
                            "total_ms": 0,
                            "sampling_ms": 0,
                            "colour_ms": 0,
                            "mixed_ms": 0,
                            "palette_ms": 0,
                        },
                        "capture_ms": 0,
                        "prepared_age_ms": 0,
                        "source_pts_ns": None,
                        "source_reused": False,
                        "frame_started_ns": mono,
                        "highlight_cache": [0, 0],
                        "backend": "xdg-portal / Vulkan DMA-BUF / SYNTHETIC; NO CAPTURE",
                    }
                ),
                flush=True,
            )
            deadline += 1 / 60
            stop.wait(max(0, deadline - time.monotonic()))


if __name__ == "__main__":
    main()
