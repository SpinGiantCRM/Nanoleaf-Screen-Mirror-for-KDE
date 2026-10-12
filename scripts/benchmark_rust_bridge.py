"""Paired offline replay of the optional bridge and complete Python colour path.

Copies, privacy masking, anchoring, native/Python marshalling, calibration,
smoothing, device mapping and GRB TLV construction are included. No capture or
USB writes. Fixed history and deterministic state isolate the sampler change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from nanoleaf_sync.config.model import AppConfig, PrivacyZone
from nanoleaf_sync.runtime.color_pipeline import build_pipeline_params_from_config
from nanoleaf_sync.runtime.color_processing import LedCalibration
from nanoleaf_sync.runtime.engine_frame import process_frame
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.rust_sampling import load_rust_box_sampler
from nanoleaf_sync.runtime.zone_presets import make_edge_weighted_zones
from nanoleaf_sync.runtime.zones import _zone_colors_via_box_filter
from nanoleaf_sync.tools.benchmark import _build_hid_zone_frame


def metrics(values: list[float]) -> dict:
    return {
        "median_ms": statistics.median(values),
        "p95_ms": sorted(values)[round((len(values) - 1) * 0.95)],
        "samples_ms": values,
    }


def user_snapshot() -> dict[Path, str]:
    root = Path.home() / ".config/nanoleaf-kde-sync"
    paths = list(root.rglob("*")) if root.exists() else []
    paths.append(Path.home() / ".local/share/applications/nanoleaf-kde-sync.desktop")
    return {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()}


def run(bridge: Path, iterations: int, warmup: int, repeats: int, quick: bool) -> dict:
    before = user_snapshot()
    native = load_rust_box_sampler(bridge)
    baseline = replace(
        build_pipeline_params_from_config(AppConfig()),
        # These features use global mutable state or time/frame dependent dither.
        # Both paths use fixed input/history for a reproducible CPU comparison.
        zone_temporal_accumulation=False,
        blue_noise_dither=False,
        # Synthetic sRGB input is unrelated to the running compositor's HDR mode.
        compositor_hdr_mode=False,
        sdr_boost_nits=80.0,
    )
    calibrated = LedCalibration(
        red_gain=0.85,
        green_gain=1.05,
        blue_gain=0.9,
        led_gamma=1.1,
        color_matrix=(0.95, 0.03, 0.02, 0.01, 0.98, 0.01, 0.02, 0.03, 0.95),
    )
    report = {
        "scope": "Offline in-process SDR replay; no capture, USB I/O or power measurement",
        "reference_commit": "6c2bbd5",
        "python": platform.python_version(),
        "kernel": platform.release(),
        "compiler": native.compiler,
        "bridge_sha256": hashlib.sha256(bridge.read_bytes()).hexdigest(),
        "iterations": iterations,
        "warmup": warmup,
        "repeats": repeats,
        "history": "fixed output history (0,0,0); accumulator/dither disabled equally",
        "order": "paired calls alternate order per iteration/repeat; no concurrent builds/tests",
        "cases": [],
    }
    sizes = [(73, 41)] if quick else [(640, 360), (2560, 1440), (3840, 2160)]
    for width, height in sizes:
        frame = np.random.default_rng(42).integers(0, 256, (height, width, 3), dtype=np.uint8)
        zones = zones_from_config(
            make_edge_weighted_zones(48, width=width, height=height),
            width,
            height,
        )
        profiles = ["box", "calibrated_privacy_letterbox"]
        if quick or width == 640:
            profiles.append("default_colour_modes_control")
        for profile in profiles:
            params = (
                baseline
                if profile == "default_colour_modes_control"
                else replace(
                    baseline,
                    sampling_mode="area_average",
                    use_zone_box_filter=True,
                    multi_moment_zone_colors=False,
                )
            )
            image = frame.copy()
            if profile == "calibrated_privacy_letterbox":
                params = replace(
                    params,
                    led_calibration=calibrated,
                    privacy_zones=[PrivacyZone(x=0.15, y=0.2, w=0.3, h=0.4)],
                )
                image[: max(1, height // 12)] = 0
                image[-max(1, height // 12) :] = 0
            rust_params = replace(params, box_sampler=native)
            row = {
                "size": [width, height],
                "zones": 48,
                "profile": profile,
                "frame_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                "runs": [],
            }
            for repeat in range(repeats):
                starts = native.successful_calls

                def full(
                    use_rust: bool, image=image, zones=zones, params=params, rust_params=rust_params
                ) -> bytes:
                    # Reverse calibrated mapping verifies the sampler cannot change it.
                    colors = process_frame(
                        frame=image,
                        prev_smoothed_colors=[(0, 0, 0)] * 48,
                        zones_px=zones,
                        device_zone_indices=list(reversed(range(48))),
                        params=rust_params if use_rust else params,
                    )
                    return _build_hid_zone_frame(colors, channel_indices=(1, 0, 2))

                def sample(
                    use_rust: bool, image=image, zones=zones, params=params
                ) -> tuple[np.ndarray, np.ndarray]:
                    return _zone_colors_via_box_filter(
                        image,
                        zones,
                        edge_locality="balanced",
                        use_multi_moment=False,
                        privacy_zones=params.privacy_zones,
                        box_sampler=native if use_rust else None,
                    )

                for _ in range(warmup):
                    if full(False) != full(True):
                        raise AssertionError("Warmup calibrated GRB TLV parity failed")
                    sample(False)
                    sample(True)
                raw = {
                    f"{path}_{stage}": []
                    for path in ["python", "rust"]
                    for stage in ["sample", "pipeline_tlv", "cpu_pipeline_tlv"]
                }
                copies = []
                full_start = native.successful_calls
                for index in range(iterations):
                    order = [False, True] if (index + repeat) % 2 == 0 else [True, False]
                    outputs, samples = {}, {}
                    for side in order:
                        path = "rust" if side else "python"
                        started = time.perf_counter()
                        samples[side] = sample(side)
                        raw[f"{path}_sample"].append((time.perf_counter() - started) * 1000)
                        cpu = time.process_time()
                        started = time.perf_counter()
                        outputs[side] = full(side)
                        raw[f"{path}_pipeline_tlv"].append((time.perf_counter() - started) * 1000)
                        raw[f"{path}_cpu_pipeline_tlv"].append((time.process_time() - cpu) * 1000)
                    if outputs[False] != outputs[True]:
                        raise AssertionError("Calibrated GRB TLV parity failed")
                    np.testing.assert_array_equal(samples[False][0], samples[True][0])
                    np.testing.assert_allclose(
                        samples[False][1], samples[True][1], rtol=0, atol=0.002
                    )
                    started = time.perf_counter()
                    copied = image.tobytes(order="C")
                    copies.append((time.perf_counter() - started) * 1000)
                    if len(copied) != image.size:
                        raise AssertionError("Invalid copy")
                # Every standalone sample invokes native once. Additional calls
                # prove how often the full colour mode actually used the bridge.
                full_calls = native.successful_calls - full_start - iterations
                if profile != "default_colour_modes_control" and full_calls != iterations:
                    raise AssertionError("Measured box pipeline did not use native on every call")
                if native.disabled_reason is not None:
                    raise AssertionError(f"Native bridge fell back: {native.disabled_reason}")
                row["runs"].append(
                    {
                        "metrics": {key: metrics(value) for key, value in raw.items()},
                        "frame_copy": metrics(copies),
                        "native_full_pipeline_calls": full_calls,
                        "native_total_calls_including_warmup": native.successful_calls - starts,
                        "exact_sample_rgb_and_grb_tlv_parity": True,
                    }
                )
            report["cases"].append(row)
    report["config_calibration_launcher_hashes_unchanged"] = before == user_snapshot()
    if not report["config_calibration_launcher_hashes_unchanged"]:
        raise AssertionError("User files changed during replay")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    if not (
        1 <= args.iterations <= 10000 and 0 <= args.warmup <= 1000 and 1 <= args.repeats <= 100
    ):
        parser.error("Invalid iteration/warmup/repeat bounds")
    result = run(args.bridge.resolve(), args.iterations, args.warmup, args.repeats, args.quick)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
