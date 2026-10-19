"""Audit generated worker-to-HID traces, including retained tail/dither state.

Only for tools/prefix-fixture-helper.py. Never feed it private screen captures.
Results contain counts/timings, not payloads or saved calibration. Wire completion
is host-observed, not LED presentation. No assumption that an ACK is optical.
"""

import math
import re
import statistics
from decimal import Decimal


def ns(value):
    return int(Decimal(value) * 1_000_000_000)


def frames(text, count):
    pending = bytearray()
    state = None
    result = []
    for line in text.splitlines():
        if "write(" not in line and "read(" not in line:
            continue
        match = re.fullmatch(
            r'(\d+\.\d+)\s+(write|read)\(\d+, "((?:\\x[0-9a-f]{2})*)", (\d+)\)'
            r"\s+= (\d+)\s+<(\d+\.\d+)>",
            line.strip(),
        )
        if not match:
            raise ValueError("Failed/interrupted/unrecognised write")
        when, operation, escaped, requested, returned, elapsed = match.groups()
        report = bytes.fromhex(escaped.replace("\\x", ""))
        if int(returned) != len(report) or (
            len(report) != int(requested) if operation == "write" else len(report) > int(requested)
        ):
            raise ValueError("Uncertain short write")
        if operation == "read":
            response = report[1:] if report[:1] == b"\0" else report
            if len(response) < 3:
                raise ValueError("Truncated response")
            length = int.from_bytes(response[1:3], "big")
            if len(response) < length + 3 or any(response[length + 3 :]):
                raise ValueError("Incomplete/concatenated response")
            if response[0] == 0x82:
                if response[3 : 3 + length] != b"\0":
                    raise ValueError("Failed/malformed ACK")
                if not result or "ack_when" in result[-1]:
                    raise ValueError("Extra frame ACK")
                result[-1]["ack_when"] = ns(when) + ns(elapsed)
                if result[-1]["ack_when"] < result[-1]["when"]:
                    raise ValueError("ACK before complete write")
            continue
        if not 2 <= len(report) <= 65 or report[0] != 0:
            raise ValueError("Bad HID report")
        pending.extend(report[1:])
        if len(pending) < 3:
            raise ValueError("Missing TLV header")
        size = 3 + int.from_bytes(pending[1:3], "big")
        if size > 1540 or len(pending) > size:
            raise ValueError("Unbounded/overrun TLV")
        if len(pending) < size:
            continue
        if pending[0] == 2:
            payload = pending[3:]
            if not payload or len(payload) % 3 or len(payload) > count * 3:
                raise ValueError("Invalid prefix")
            if state is None:
                if len(payload) != count * 3:
                    raise ValueError("Unknown retained state before first full frame")
                state = bytearray(payload)
            state[: len(payload)] = payload
            result.append(
                {"when": ns(when) + ns(elapsed), "zones": len(payload) // 3, "state": bytes(state)}
            )
        pending.clear()
    if pending:
        raise ValueError("Incomplete final TLV")
    return result


def analyse(text, events, mode, acknowledged):
    output = frames(text, 48)
    if len(output) != acknowledged + 1 or output[-1]["zones"] != 48 or any(output[-1]["state"]):
        raise ValueError("Expected every ACKed update and full cleanup black")
    acked = ["ack_when" in f for f in output]
    if any(acked) and not all(acked):
        raise ValueError("Missing ACK in traced stream")
    has_acks = all(acked)
    output = output[:-1]
    for index, frame in enumerate(output):
        c = frame["state"]
        if c[0] not in (8, 64) or c[:36] != bytes([c[0]]) * 36:
            raise ValueError("Unexpected generated prefix")
        tail = c[0] if mode == "full" else 8
        if c[36:141] != bytes([tail]) * 105:
            raise ValueError("Retained tail differs from full reference")
        # Independent exact ties-even oracle; fixture values/noise are binary
        # fractions, so there is no f32/f64 approximation difference here.
        last = round(8.25 + (((index + 47 * 3) % 8 + 0.5) / 8 - 0.5))
        if c[141:] != bytes([last if mode == "fractional" else tail]) * 3:
            raise ValueError("Wrong ACK-cadenced fractional tail")
    if len(events) < 20:
        raise ValueError("Insufficient generated transitions")
    epochs = [e["unix_ns"] - e["monotonic_ns"] for e in events]
    if max(epochs) - min(epochs) > 2_000_000:
        raise ValueError("Clock drift exceeds two milliseconds")
    begin, end = output[0]["when"] + 1_000_000_000, output[-1]["when"] - 500_000_000
    delays = []
    ack_delays = []
    for event, following in zip(events, events[1:], strict=False):
        when = event["unix_ns"]
        if not begin <= when <= end:
            continue
        target = 64 if event["high"] else 8
        before = [f for f in output if f["when"] < when]
        if not before or before[-1]["state"][0] == target:
            raise ValueError("Missing opposite previous state")
        matching = next((f for f in output if f["when"] >= when and f["state"][0] == target), None)
        if matching is None or matching["when"] >= following["unix_ns"]:
            raise ValueError("Dropped/missing generated transition")
        delays.append((matching["when"] - when) / 1_000_000)
        if has_acks:
            ack_delays.append((matching["ack_when"] - when) / 1_000_000)
    if len(delays) < 20:
        raise ValueError("Too few independently matched transitions")
    values = sorted(delays)
    result = {
        "scope": (
            "Generated worker event to actual host HID write return; "
            "real actor/HID, no capture or optical timing"
        ),
        "matched_transitions": len(delays),
        "event_to_write_ms": {
            "min": values[0],
            "median": statistics.median(values),
            "p95": values[math.ceil(0.95 * len(values)) - 1],
            "max": values[-1],
        },
        "all_event_to_write_ms": delays,
        "full_state_exact_comparisons": len(output),
        "shortened_transactions": sum(f["zones"] < 48 for f in output),
        "full_transactions": sum(f["zones"] == 48 for f in output),
        "prefix_lengths": sorted({f["zones"] for f in output}),
        "cleanup_full_black": True,
        "clock_epoch_range_ns": max(epochs) - min(epochs),
    }
    if has_acks:
        values = sorted(ack_delays)
        result["event_to_ack_ms"] = {
            "min": values[0],
            "median": statistics.median(values),
            "p95": values[math.ceil(0.95 * len(values)) - 1],
            "max": values[-1],
        }
        result["all_event_to_ack_ms"] = ack_delays
        result["all_frame_acks_traced"] = True
    return result
