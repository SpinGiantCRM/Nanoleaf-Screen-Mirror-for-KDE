"""Paired complete SDR replays; generated pixels only, no capture or HID output."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import struct
import subprocess
import tempfile
from pathlib import Path

from benchmark_rust_adaptive import fixtures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=6)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    if not 2 <= args.pairs <= 20:
        parser.error("Use 2 to 20 alternating-order pairs")
    binaries = {"before": args.before.resolve(), "after": args.after.resolve()}
    result = dict(
        scope=(
            "Generated SDR RGB8, full processing/TLV; excludes frame I/O, capture, "
            "USB, UI, optical response and power"
        ),
        pairs=args.pairs,
        order="Alternating AB/BA; independent fresh pipelines, 3 warmup frames per process",
        binary_sha256={k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in binaries.items()},
        intentional_differences=(
            "Linear blending and final device gamma; sampled pixels must remain exact"
        ),
        cases=[],
    )
    for w, h in [(96, 64)] if args.quick else [(640, 360), (3840, 2160)]:
        with tempfile.TemporaryDirectory(prefix="nanoleaf-colour-refinement-") as directory:
            root = Path(directory)
            frames = []
            hashes = []
            for i, rgb in enumerate(fixtures(w, h, "flashes_scene_cuts_neutrals", 12)):
                data = rgb.tobytes()
                path = root / f"frame-{i}.rgb"
                path.write_bytes(b"NSRGB001" + struct.pack("<QQQ", w, h, w * 3) + data)
                hashes.append(hashlib.sha256(data).hexdigest())
                frames.append(str(path))
            for style in ("reference", "ambient"):
                for gamma in (1.0, 2.2):
                    config = root / "config.toml"
                    config.write_text(
                        "schema_version=2\ndevice_zone_count=48\n"
                        f'color_style="{style}"\nbrightness=0.6\nblue_noise_dither=true\n'
                        "zone_temporal_accumulation=false\nletterbox_detection=false\n"
                        "corner_anchor_top_left=2\ncorner_anchor_top_right=17\n"
                        "corner_anchor_bottom_right=26\ncorner_anchor_bottom_left=41\n"
                        f"[led_calibration_profile_sdr]\nled_gamma={gamma}\n"
                    )
                    manifest = root / "manifest.json"
                    manifest.write_text(
                        json.dumps(dict(config=str(config), frames=frames, repeats=1, warmup=3))
                    )
                    values = {k: [] for k in binaries}
                    colour_values = {k: [] for k in binaries}
                    pairs = []
                    maximum_sample_delta = maximum_output_delta = 0
                    for pair in range(args.pairs):
                        outputs = {}
                        order = ["before", "after"] if pair % 2 == 0 else ["after", "before"]
                        for label in order:
                            # Local operator-selected replay programs, separate argv, no shell.
                            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args  # noqa: E501
                            raw_output = subprocess.check_output(
                                [str(binaries[label]), str(manifest)], timeout=60
                            )
                            outputs[label] = json.loads(raw_output)
                            rows = outputs[label]["runs"][0]
                            values[label].extend(row["total_ms"] for row in rows)
                            colour_values[label].extend(row["colour_ms"] for row in rows)
                        a, b = (outputs[k]["runs"][0] for k in ("before", "after"))
                        for old, new in zip(a, b, strict=True):
                            for key in ("sampled", "colors"):
                                delta = max(
                                    abs(x - y)
                                    for p, q in zip(old[key], new[key], strict=True)
                                    for x, y in zip(p, q, strict=True)
                                )
                                if key == "sampled":
                                    maximum_sample_delta = max(maximum_sample_delta, delta)
                                else:
                                    maximum_output_delta = max(maximum_output_delta, delta)
                        assert maximum_sample_delta == 0
                        assert b[-1]["colors"] == [[0, 0, 0]] * 48
                        pairs.append(
                            dict(
                                order=order,
                                before_total_ms=[r["total_ms"] for r in a],
                                after_total_ms=[r["total_ms"] for r in b],
                            )
                        )
                    case = dict(
                        width=w,
                        height=h,
                        style=style,
                        gamma=gamma,
                        frame_sha256=hashes,
                        maximum_sample_code_delta=maximum_sample_delta,
                        maximum_output_code_delta=maximum_output_delta,
                        total_median_ms={k: statistics.median(v) for k, v in values.items()},
                        colour_median_ms={
                            k: statistics.median(v) for k, v in colour_values.items()
                        },
                        pairs=pairs,
                    )
                    result["cases"].append(case)
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(result, indent=2) + "\n")
                    print(
                        {
                            k: case[k]
                            for k in (
                                "width",
                                "height",
                                "style",
                                "gamma",
                                "total_median_ms",
                                "colour_median_ms",
                            )
                        },
                        flush=True,
                    )


if __name__ == "__main__":
    main()
