#!/usr/bin/env python3
"""Synthetic capture-worker protocol fixture; NO screen/GPU/HID access.

For operator recovery tests only: copy a native app into a separate private
directory and place this file beside it as nanoleaf-native-capture. Never
install that directory as an application bundle. The real app's bounded USB
probe supplies exclusive ownership, low brightness and controller restoration.
This helper emits generated phase-invariant grey8 so the service's actual
repeat-suppression, Stop/preview/reconnect and stalled-helper paths can be tested
without covering the user's monitor or disabling saved dithering/calibration.
No calibration is applied to these synthetic downstream protocol values.
"""

import json
import sys
import threading
import time


def main():
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("Operator protocol fixture only: --worker with private config stdin")
    first = sys.stdin.readline(1_048_577)
    if len(first) > 1_048_576:
        raise ValueError("Oversized fixture config")
    count = json.loads(first)["device_zone_count"]
    if not isinstance(count, int) or not 1 <= count <= 512:
        raise ValueError("Authoritative manual count required")
    stop = threading.Event()

    def feedback():
        # Drain real ACK feedback without treating skipped source frames as ACKs.
        for line in sys.stdin:
            if len(line) > 32768:
                break
        stop.set()

    threading.Thread(target=feedback, daemon=True).start()
    began = time.monotonic()
    while not stop.is_set() and time.monotonic() - began < 35:
        row = {
            "schema": 3,
            "colors": [[8, 8, 8]] * count,
            "unquantized_rgb": [[8.0, 8.0, 8.0]] * count,
            "times": {
                "total_ms": 0.0,
                "sampling_ms": 0.0,
                "colour_ms": 0.0,
                "mixed_ms": 0.0,
                "palette_ms": 0.0,
            },
            "capture_ms": 0.0,
            "prepared_age_ms": 0.0,
            "source_pts_ns": None,
            "source_reused": False,
            "frame_started_ns": time.monotonic_ns(),
            "highlight_cache": [0, 0],
            "backend": "xdg-portal / Vulkan DMA-BUF / SYNTHETIC PROTOCOL FIXTURE; NO CAPTURE",
        }
        print(json.dumps(row), flush=True)
        stop.wait(1 / 60)


if __name__ == "__main__":
    main()
