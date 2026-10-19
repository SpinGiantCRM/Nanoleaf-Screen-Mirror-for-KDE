"""Decode operator-only HID write traces of a controlled two-grey scene.

Raw trace bytes stay private. Returned results contain only numeric timing and
validation counts, never screen pixels, LED colours or calibration. Measures a
client paint request to final HID write returning, not monitor/LED presentation.
"""

import math
import re
import statistics
from decimal import Decimal


def _nanoseconds(value):
    return int(Decimal(value) * 1_000_000_000)


def writes(text, manual):
    """Read single-main-thread strace -ttt -T -xx -s256 -e write -P HIDRAW."""
    frames = []
    pending = bytearray()
    expected = None
    lines = 0
    for line in text.splitlines():
        if "write(" not in line:
            continue
        match = re.fullmatch(
            r'(\d+\.\d+)\s+write\(\d+, "((?:\\x[0-9a-f]{2})*)", (\d+)\)'
            r"\s+= (\d+)\s+<(\d+\.\d+)>",
            line.strip(),
        )
        if not match:
            raise ValueError("Unsupported, interrupted or failed HID write trace")
        when, escaped, size, returned, duration = match.groups()
        report = bytes.fromhex(escaped.replace("\\x", ""))
        if int(size) != len(report) or int(returned) != len(report):
            raise ValueError("Short/truncated HID write")
        if not 2 <= len(report) <= 65 or report[0] != 0:
            raise ValueError("Unexpected HID report ID/size")
        lines += 1
        pending.extend(report[1:])
        if expected is None:
            if len(pending) < 3:
                raise ValueError("Truncated TLV header")
            expected = 3 + int.from_bytes(pending[1:3], "big")
            if expected > 1540:
                raise ValueError("Unbounded TLV length")
        if len(pending) >= expected:
            if len(pending) != expected:
                raise ValueError("Unexpected trailing HID payload")
            if pending[0] == 0x02:
                if expected != 3 + manual * 3:
                    raise ValueError("Frame differs from authoritative manual count")
                frames.append(
                    {
                        "written_ns": _nanoseconds(when) + _nanoseconds(duration),
                        "mean_code": statistics.mean(pending[3:]),
                    }
                )
            pending.clear()
            expected = None
    if pending:
        raise ValueError("Incomplete final HID transaction")
    return frames, lines


def analyse(text, scene, manual, acknowledged):
    frames, lines = writes(text, manual)
    if len(frames) != acknowledged + 1:
        raise ValueError("Trace must contain every acknowledged frame plus one cleanup black")
    requests = scene["step_paint_requests"]
    if len(requests) < 8:
        raise ValueError("Not enough deliberate scene steps")
    epoch = requests[0]["unix_ns"] - requests[0]["elapsed_ns"]
    if any(abs((r["unix_ns"] - r["elapsed_ns"]) - epoch) > 2_000_000 for r in requests):
        raise ValueError("Realtime/elapsed clock drift exceeds two milliseconds")
    # Exclude startup, final scene/actor closure, and cleanup black from clustering.
    start = epoch + 3_000_000_000
    stop = min(requests[-1]["unix_ns"], frames[-1]["written_ns"] - 500_000_000)
    stable = [f for f in frames if start <= f["written_ns"] <= stop]
    if len(stable) < 100:
        raise ValueError("Not enough stable USB frames")
    low, high = min(f["mean_code"] for f in stable), max(f["mean_code"] for f in stable)
    for _ in range(5):
        midpoint = (low + high) / 2
        groups = [
            [f["mean_code"] for f in stable if (f["mean_code"] > midpoint) == b]
            for b in [False, True]
        ]
        if min(map(len, groups)) < 20:
            raise ValueError("Both grey states must have substantial output")
        low, high = map(statistics.median, groups)
    if high - low < 4 or any(
        min(abs(f["mean_code"] - low), abs(f["mean_code"] - high)) > 2 for f in stable
    ):
        raise ValueError("USB output does not match two stable grey states")
    midpoint = (low + high) / 2
    delays = []
    for request in requests:
        when = request["unix_ns"]
        if not start <= when <= stop:
            continue
        target = request["requested_grey_code"] == 192
        previous = [f for f in frames if f["written_ns"] < when]
        if not previous or (previous[-1]["mean_code"] > midpoint) == target:
            raise ValueError("Previous written scene did not have the opposite grey state")
        matching = next(
            (
                f
                for f in frames
                if f["written_ns"] >= when and (f["mean_code"] > midpoint) == target
            ),
            None,
        )
        if matching is None or matching["written_ns"] - when > 500_000_000:
            raise ValueError("Missing or delayed scene step in USB output")
        delays.append((matching["written_ns"] - when) / 1_000_000)
    if len(delays) < 6:
        raise ValueError("Too few matched paint-to-write transitions")
    ordered = sorted(delays)
    return {
        "scope": (
            "Controlled static grey paint request to final host HID write returning. "
            "Output transitions matched from complete actual USB payloads; no optical or "
            "panel-presentation timing. Single actor thread ptrace adds overhead. Raw "
            "LED codes stay private. Startup/cleanup excluded; occasional compositor "
            "hitches retained. Realtime/elapsed drift bounded to two milliseconds."
        ),
        "matched_steps": len(delays),
        "request_to_write_ms": delays,
        "distribution_ms": {
            f"p{p}": ordered[math.ceil(len(ordered) * p / 100) - 1] for p in [50, 95, 99]
        },
        "complete_colour_frames_written": len(frames),
        "successful_hid_report_writes": lines,
        "truncated_failed_or_unmatched_output": False,
    }
