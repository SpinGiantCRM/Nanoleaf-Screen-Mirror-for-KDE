"""Validate and aggregate the retained 384-command packet-layout experiment."""

import argparse
import collections
import json
import math
import statistics
from pathlib import Path


def summarise(recording):
    if not (
        recording["outcome"]["error"] is None
        and recording["outcome"]["controller_restored"] is True
        and recording["outcome"]["black_cleanup_acknowledged"] is True
    ):
        raise ValueError("Failed experiment cannot be pooled as successful")
    groups = collections.defaultdict(list)
    cases = recording["cases"]
    expected = [
        (pattern, candidate, shape)
        for pattern in ("black", "neutral-8", "neutral-64", "varied")
        for candidate in (1, 2, 3)
        for shape in (0, candidate, candidate, 0)
    ]
    if [(c["pattern"], c["candidate_shape"], c["shape"]) for c in cases] != expected:
        raise ValueError("Unexpected ABBA case sequence")
    for case in cases:
        if len(case["samples"]) != 8:
            raise ValueError("Expected eight commands per case")
        for sample in case["samples"]:
            if not (
                sample["sent_zones"] == 48
                and sample["written_reports"] == 3
                and sample["response_reports"] == 1
                and sample["drained_reports"] == 0
                and sample["unrelated_response"] is False
            ):
                raise ValueError("Unexpected transaction traffic")
            for key in ("write_ms", "ack_wait_ms", "total_ms"):
                if not math.isfinite(sample[key]) or sample[key] < 0:
                    raise ValueError("Invalid timing")
        groups[case["pattern"], case["candidate_shape"], case["shape"]].extend(case["samples"][2:])
    comparisons = []
    for (pattern, candidate, shape), samples in groups.items():
        row = {"pattern": pattern, "candidate_shape": candidate, "shape": shape}
        for key in ("write_ms", "ack_wait_ms", "total_ms"):
            values = sorted(sample[key] for sample in samples)
            row[key] = {
                "n": len(values),
                "p50_ms": statistics.median(values),
                "p95_ms": values[math.ceil(0.95 * len(values)) - 1],
                "min_ms": values[0],
                "max_ms": values[-1],
            }
        comparisons.append(row)
    return {
        "scope": "Generated full 48-zone raw USB commands; no capture or optical timing",
        "successful_measured_commands_including_warmups": 384,
        "warmups_per_case": 2,
        "comparisons": comparisons,
        "daily_path_changed": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).with_name("packet-shape.json")
    recording = json.loads(path.read_text())
    result = summarise(recording)
    if args.check:
        if result != json.loads(path.with_name("packet-shape-summary.json").read_text()):
            raise ValueError("Stored aggregates disagree with recording")
        # A failed response cannot be silently admitted by the aggregator.
        recording["cases"][0]["samples"][0]["response_reports"] = 0
        try:
            summarise(recording)
        except ValueError:
            print("Packet-layout aggregates match; missing-ACK negative control rejected")
        else:
            raise AssertionError("Missing ACK admitted")
    else:
        print(json.dumps(result, indent=2))
