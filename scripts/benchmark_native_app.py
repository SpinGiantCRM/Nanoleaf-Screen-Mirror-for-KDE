"""Full Rust frame pipeline vs the preserved Python oracle, without capture/USB."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import struct
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from benchmark_rust_adaptive import fixtures

from nanoleaf_sync.config.model import AppConfig, PrivacyZone
from nanoleaf_sync.runtime.anchor_calibration import derive_anchor_zone_map
from nanoleaf_sync.runtime.color_pipeline import (
    build_pipeline_params_from_config,
    process_zone_colors,
    zone_sample_motion,
)
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.zone_presets import edge_side_counts, make_edge_weighted_zones
from nanoleaf_sync.tools.benchmark import _build_hid_zone_frame


def python_run(c, frames, w, h):
    params = replace(
        build_pipeline_params_from_config(
            c, capture_display_referred=True, skip_display_gamut_adaptation=True
        ),
        compositor_hdr_mode=False,
    )
    zones = zones_from_config(make_edge_weighted_zones(48, width=w, height=h), w, h)
    mapping = derive_anchor_zone_map(
        zone_count=48,
        device_zone_count=48,
        anchors=dict(
            zip(
                ("top_left", "top_right", "bottom_right", "bottom_left"),
                (2, 17, 26, 41),
                strict=True,
            )
        ),
        source_side_counts=edge_side_counts(zone_count=48, width=w, height=h),
    ).mapping
    process_zone_colors._zone_accumulator = None
    history = []
    samples = []
    for index, frame in enumerate(frames):
        cpu = time.process_time()
        start = time.perf_counter()
        colors, raw, _, _, times, smooth, sent = process_zone_colors(
            frame=frame,
            precomputed_zone_colors=None,
            prev_smoothed_colors=history,
            zones_px=zones,
            device_zone_indices=mapping,
            params=replace(params, return_diagnostics=True),
        )
        payload = _build_hid_zone_frame(colors, channel_indices=(1, 0, 2))
        samples.append(
            dict(
                total_ms=(time.perf_counter() - start) * 1000,
                cpu_ms=(time.process_time() - cpu) * 1000,
                sampling_ms=times.zone_sampling_ms,
                colors=colors,
                sampled=raw.tolist(),
                modes=times.per_zone_sampling_mode,
                tlv=list(payload),
            )
        )
        params = replace(
            params,
            palette_frame_index=index + 1,
            prev_sampled_zone_colors=[tuple(int(x) for x in row) for row in raw.tolist()],
            previous_palette_algorithms=times.per_zone_sampling_mode,
            zone_palette_temporal_states=times.per_zone_palette_temporal_states,
            prev_smooth_float_colors=smooth,
            prev_sent_colors=sent,
            prior_zone_sample_motion=zone_sample_motion(
                raw, params.prev_sampled_zone_colors or None
            ),
            prior_area_average_mode=times.area_average_active,
            sampling_mode_dwell_remaining=times.sampling_mode_dwell_remaining,
            dark_zone_stabilize_hold=times.dark_zone_stabilize_hold,
            blend_hysteresis=times.blend_hysteresis,
            output_quantization_prev_hold=times.output_quantization_prev_hold,
        )
        history = colors
    process_zone_colors._zone_accumulator = None
    return samples


def metrics(values):
    return dict(
        median_ms=statistics.median(values),
        p95_ms=sorted(values)[round((len(values) - 1) * 0.95)],
        samples_ms=values,
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--frames", type=int, default=12)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--quick", action="store_true")
    p.add_argument(
        "--no-accumulation",
        action="store_true",
        help=(
            "Compare production spatial/colour processing without the corrected "
            "temporal accumulator"
        ),
    )
    p.add_argument(
        "--legacy-black-hold-oracle",
        action="store_true",
        help=(
            "Verify historical Python arithmetic, including black glow and chroma-control bugs; "
            "not production timings"
        ),
    )
    p.add_argument(
        "--production-comparison",
        action="store_true",
        help="Measure corrected production colours and record intentional differences from Python",
    )
    p.add_argument(
        "--sampling-mode", choices=("auto", "peak_luma", "vivid_weighted"), default="auto"
    )
    p.add_argument("--quality", choices=("high", "balanced", "low"), default="high")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--binary", type=Path, default=Path("native/app/target/release/replay"))
    args = p.parse_args()
    if args.production_comparison == args.legacy_black_hold_oracle:
        p.error("Select exactly one of --production-comparison or --legacy-black-hold-oracle")
    if args.production_comparison and not args.no_accumulation:
        p.error(
            "Use --no-accumulation to isolate production colour corrections from temporal changes"
        )
    result = dict(
        scope=(
            "Complete offline colour + GRB TLV. "
            "Capture, USB, GUI, power and optical response excluded."
        ),
        reference_commit="d982cf9",
        native_legacy_black_hold_oracle=args.legacy_black_hold_oracle,
        comparison_kind=(
            "production_colour_difference_measurement"
            if args.production_comparison
            else "historical_python_parity"
        ),
        temporal_accumulation=not args.no_accumulation,
        dither=(
            "Disabled equally for parity; native corrected sub-code dither is tested separately."
        ),
        frames=args.frames,
        repeats=args.repeats,
        quality=args.quality,
        sampling_mode=args.sampling_mode,
        host=dict(platform=platform.platform(), python=platform.python_version()),
        source_sha256={
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for root, suffix in [
                ("native/core/src", "*.rs"),
                ("native/app/src", "*.rs"),
                ("src/nanoleaf_sync", "*.py"),
            ]
            for path in sorted(Path(root).rglob(suffix))
        },
        binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        cases=[],
    )
    for w, h in [(96, 64)] if args.quick else [(640, 360), (2560, 1440), (3840, 2160)]:
        for style in ("reference", "ambient"):
            for name in (
                "flashes_scene_cuts_neutrals",
                "mixed_dark_noise",
                "calibrated_privacy_letterbox",
            ):
                c = AppConfig(
                    color_style=style,
                    device_zone_count=48,
                    blue_noise_dither=False,
                    sampling_quality=args.quality,
                    sampling_mode=args.sampling_mode,
                    zone_temporal_accumulation=not args.no_accumulation,
                )
                if name == "calibrated_privacy_letterbox":
                    c.privacy_zones = [PrivacyZone(x=0.15, y=0.2, w=0.3, h=0.4)]
                with tempfile.TemporaryDirectory(prefix="nanoleaf-native-replay-") as directory:
                    root = Path(directory)
                    paths = []
                    hashes = []
                    for i, frame in enumerate(fixtures(w, h, name, args.frames)):
                        file = root / f"frame-{i:03d}.rgb"
                        data = frame.tobytes()
                        file.write_bytes(b"NSRGB001" + struct.pack("<QQQ", w, h, w * 3) + data)
                        paths.append(file)
                        hashes.append(hashlib.sha256(data).hexdigest())
                    cfg = root / "config.toml"
                    text = (
                        "schema_version=2\ndevice_zone_count=48\n"
                        f'color_style="{style}"\nblue_noise_dither=false\n'
                        f'sampling_quality="{args.quality}"\nsampling_mode="{args.sampling_mode}"\ncorner_anchor_top_left=2\n'
                        "corner_anchor_top_right=17\ncorner_anchor_bottom_right=26\n"
                        "corner_anchor_bottom_left=41\n"
                    )
                    if args.no_accumulation:
                        text += "zone_temporal_accumulation=false\n"
                    if c.privacy_zones:
                        text += "privacy_zones=[{x=0.15,y=0.2,w=0.3,h=0.4}]\n"
                    cfg.write_text(text)
                    manifest = root / "manifest.json"
                    manifest.write_text(
                        json.dumps(
                            dict(
                                config=str(cfg),
                                frames=list(map(str, paths)),
                                warmup=3,
                                repeats=1,
                                legacy_black_hold_oracle=args.legacy_black_hold_oracle,
                            )
                        )
                    )
                    python_run(c, fixtures(w, h, name, min(3, args.frames)), w, h)
                    runs = []
                    for repeat in range(args.repeats):
                        results = {}
                        for side in ("python", "rust") if repeat % 2 == 0 else ("rust", "python"):
                            if side == "python":
                                results[side] = python_run(
                                    c, fixtures(w, h, name, args.frames), w, h
                                )
                            else:
                                native = json.loads(
                                    subprocess.check_output(
                                        # The local operator deliberately selects the replay
                                        # executable; argv stays separate and no shell runs.
                                        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-tainted-env-args.dangerous-subprocess-use-tainted-env-args  # noqa: E501
                                        [str(args.binary.resolve()), str(manifest)],
                                        text=True,
                                        shell=False,
                                    )
                                )
                                results[side] = native["runs"][0]
                        sample_delta = 0
                        output_delta = 0
                        exact_packets = 0
                        for py, rs in zip(results["python"], results["rust"], strict=True):
                            sample_delta = max(
                                sample_delta,
                                int(
                                    np.max(
                                        np.abs(np.asarray(py["sampled"], dtype=int) - rs["sampled"])
                                    )
                                ),
                            )
                            output_delta = max(
                                output_delta,
                                int(
                                    np.max(
                                        np.abs(np.asarray(py["colors"], dtype=int) - rs["colors"])
                                    )
                                ),
                            )
                            exact_packets += py["tlv"] == rs["tlv"]
                        if sample_delta > 1 or (
                            output_delta > 1 and not args.production_comparison
                        ):
                            args.output.with_suffix(".failure.json").write_text(
                                json.dumps(
                                    dict(
                                        size=[w, h],
                                        style=style,
                                        sequence=name,
                                        quality=args.quality,
                                        results=results,
                                    ),
                                    indent=2,
                                )
                                + "\n"
                            )
                            raise AssertionError(
                                f"{w} {style} {name}: sampled {sample_delta}, output {output_delta}"
                            )
                        runs.append(
                            dict(
                                max_sampled_code_delta=sample_delta,
                                max_output_code_delta=output_delta,
                                exact_packets=exact_packets,
                                metrics={
                                    side: metrics([s["total_ms"] for s in data])
                                    for side, data in results.items()
                                },
                                native_stages={
                                    key: metrics([s[key] for s in results["rust"]])
                                    for key in (
                                        "sampling_ms",
                                        "colour_ms",
                                        "mixed_ms",
                                        "palette_ms",
                                    )
                                },
                                native_memory=native["memory"],
                            )
                        )
                    row = dict(
                        size=[w, h], style=style, sequence=name, frame_hashes=hashes, runs=runs
                    )
                    result["cases"].append(row)
                    py = statistics.median([run["metrics"]["python"]["median_ms"] for run in runs])
                    rs = statistics.median([run["metrics"]["rust"]["median_ms"] for run in runs])
                    print(
                        f"{w}x{h} {style} {name}: {py:.3f} -> {rs:.3f} ms ({py / rs:.2f}x)",
                        flush=True,
                    )
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
