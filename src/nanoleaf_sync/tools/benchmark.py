from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np

from nanoleaf_sync.color._types import RGBTuple
from nanoleaf_sync.device.protocol import CMD_SET_ZONE_COLORS, NanoleafTLVProtocol
from nanoleaf_sync.runtime.engine import process_frame
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.zone_presets import make_edge_weighted_zones
from nanoleaf_sync.runtime.zones import zone_colors_array

RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class BenchmarkPreset:
    width: int
    height: int
    zone_count: int
    iterations: int
    warmup: int


_PRESETS: dict[str, BenchmarkPreset] = {
    "production": BenchmarkPreset(
        width=640,
        height=360,
        zone_count=48,
        iterations=120,
        warmup=10,
    ),
}


def _p95_ms(samples_ms: Sequence[float]) -> float:
    if not samples_ms:
        return 0.0
    ordered = sorted(float(v) for v in samples_ms)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95))))
    return float(ordered[index])


def _timed_samples(
    fn: Callable[[], object],
    *,
    iterations: int,
    warmup: int,
) -> list[float]:
    for _ in range(max(0, warmup)):
        fn()
    samples: list[float] = []
    for _ in range(max(1, iterations)):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples


def _metric_block(samples_ms: Sequence[float]) -> dict[str, float | int]:
    return {
        "p95_ms": _p95_ms(samples_ms),
        "median_ms": float(statistics.median(samples_ms)) if samples_ms else 0.0,
        "max_ms": float(max(samples_ms)) if samples_ms else 0.0,
        "samples": len(samples_ms),
    }


def _build_hid_zone_frame(
    colors: Sequence[RGBTuple],
    *,
    channel_indices: tuple[int, int, int],
) -> bytes:
    normalized = [
        (max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b))))
        for r, g, b in colors
    ]
    payload_buffer = bytearray(len(normalized) * 3)
    write_idx = 0
    for rgb in normalized:
        for channel_idx in channel_indices:
            payload_buffer[write_idx] = rgb[channel_idx]
            write_idx += 1
    return NanoleafTLVProtocol.build_request(CMD_SET_ZONE_COLORS, bytes(payload_buffer))


def run_benchmark(*, preset_name: str) -> dict[str, Any]:
    preset = _PRESETS.get(str(preset_name).strip().lower())
    if preset is None:
        supported = ", ".join(sorted(_PRESETS))
        raise ValueError(f"Unknown benchmark preset '{preset_name}'. Supported: {supported}")

    width = preset.width
    height = preset.height
    zone_count = preset.zone_count
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, : width // 2, :] = (220, 40, 30)
    frame[:, width // 2 :, :] = (30, 180, 220)

    zone_models = make_edge_weighted_zones(
        zone_count,
        width=width,
        height=height,
        edge_locality="balanced",
    )
    zones_px = zones_from_config(zone_models, width, height)
    device_zone_indices = list(range(zone_count))
    prev_smoothed: list[RGB] = [(0, 0, 0)] * zone_count

    zone_samples = _timed_samples(
        lambda: zone_colors_array(
            frame,
            zones_px,
            sample_step=1,
            mode="balanced",
            sampling_mode="area_average",
            use_zone_box_filter=True,
        ),
        iterations=preset.iterations,
        warmup=preset.warmup,
    )

    pipeline_samples = _timed_samples(
        lambda: process_frame(
            frame=frame,
            prev_smoothed_colors=prev_smoothed,
            zones_px=zones_px,
            device_zone_indices=device_zone_indices,
            brightness=1.0,
            smoothing=0.85,
            edge_locality="balanced",
            motion_preset="responsive",
            color_style="natural",
            compositor_hdr_mode=False,
            sdr_boost_nits=80.0,
            hdr_max_nits=1000.0,
        ),
        iterations=preset.iterations,
        warmup=preset.warmup,
    )

    colors = [(int(r), int(g), int(b)) for r, g, b in prev_smoothed]
    hid_samples = _timed_samples(
        lambda: _build_hid_zone_frame(colors, channel_indices=(0, 1, 2)),
        iterations=preset.iterations,
        warmup=preset.warmup,
    )

    return {
        "preset": preset_name,
        "width": width,
        "height": height,
        "zone_count": zone_count,
        "iterations": preset.iterations,
        "warmup": preset.warmup,
        "metrics": {
            "zone_sampling": _metric_block(zone_samples),
            "colour_pipeline": _metric_block(pipeline_samples),
            "hid_frame_build": _metric_block(hid_samples),
        },
    }


def _load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def compare_against_baseline(
    result: dict[str, Any],
    baseline: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    result_metrics = result.get("metrics")
    baseline_metrics = baseline.get("metrics")
    if not isinstance(result_metrics, dict) or not isinstance(baseline_metrics, dict):
        return ["Benchmark result or baseline is missing a metrics object."]

    for name, limits in baseline_metrics.items():
        if not isinstance(limits, dict):
            continue
        actual_block = result_metrics.get(name)
        if not isinstance(actual_block, dict):
            failures.append(f"{name}: missing from benchmark result")
            continue
        actual_p95 = float(actual_block.get("p95_ms", 0.0) or 0.0)
        max_p95 = limits.get("p95_ms_max", limits.get("max_p95_ms"))
        if max_p95 is None:
            continue
        if actual_p95 > float(max_p95):
            failures.append(
                f"{name}: p95 {actual_p95:.3f}ms exceeds baseline budget {float(max_p95):.3f}ms"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline performance benchmark for nanoleaf-kde-sync hot paths."
    )
    parser.add_argument(
        "--preset",
        default="production",
        choices=sorted(_PRESETS),
        help="Benchmark preset (default: production).",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default="-",
        help="Write JSON results to this path ('-' for stdout).",
    )
    parser.add_argument(
        "--compare",
        dest="baseline_path",
        default="",
        help="Compare result p95 metrics against this baseline JSON (non-zero exit on regression).",
    )
    args = parser.parse_args(argv)

    try:
        result = run_benchmark(preset_name=str(args.preset))
    except ValueError as exc:
        print(str(exc))
        return 2

    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.json_path == "-":
        print(payload)
    else:
        out_path = Path(args.json_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(f"{payload}\n", encoding="utf-8")

    if args.baseline_path:
        baseline = _load_json(Path(args.baseline_path))
        failures = compare_against_baseline(result, baseline)
        if failures:
            for line in failures:
                print(line)
            return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
