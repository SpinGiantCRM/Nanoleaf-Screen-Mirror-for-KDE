"""Offline default adaptive-colour replay: profile, parity and complete-path timings."""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import platform
import pstats
import statistics
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np

from nanoleaf_sync.config.model import AppConfig, PrivacyZone
from nanoleaf_sync.runtime.color_pipeline import (
    build_pipeline_params_from_config,
    process_zone_colors,
    zone_sample_motion,
)
from nanoleaf_sync.runtime.color_processing import LedCalibration
from nanoleaf_sync.runtime.engine_frame import process_frame
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.rust_sampling import load_rust_box_sampler
from nanoleaf_sync.runtime.zone_presets import make_edge_weighted_zones
from nanoleaf_sync.tools.benchmark import _build_hid_zone_frame


def fixtures(width: int, height: int, name: str, length: int):
    for index in range(length):
        phase = index % 12
        frame = np.full((height, width, 3), (25, 170, 45), dtype=np.uint8)
        if name == "mixed_dark_noise":
            if phase < 4:
                frame[:, width // 2 :] = (180, 15, 40)
            elif phase < 8:
                frame[:] = np.random.default_rng(index).integers(0, 32, frame.shape, dtype=np.uint8)
            else:
                frame[:] = np.random.default_rng(index).integers(
                    0, 256, frame.shape, dtype=np.uint8
                )
        else:
            if phase in {1, 3, 5}:
                frame[height // 4 : height // 2, width // 5 : width // 2] = 255
            if phase >= 6:
                frame[:] = (210, 20, 25)
            if phase == 10:
                frame[:] = 128
            if phase == 11:
                frame[:] = 0
        if name == "calibrated_privacy_letterbox" and phase < 3:
            frame[: max(1, height // 12)] = 0
            frame[-max(1, height // 12) :] = 0
        yield frame


def replay(width: int, height: int, name: str, length: int, native=None) -> dict:
    params = replace(
        build_pipeline_params_from_config(AppConfig()),
        compositor_hdr_mode=False,
        sdr_boost_nits=80.0,
        adaptive_prepass=native.adaptive_prepass if native else None,
    )
    if name == "calibrated_privacy_letterbox":
        params = replace(
            params,
            privacy_zones=[PrivacyZone(x=0.15, y=0.2, w=0.3, h=0.4)],
            led_calibration=LedCalibration(
                red_gain=0.85,
                green_gain=1.05,
                blue_gain=0.9,
                led_gamma=1.1,
                color_matrix=(0.95, 0.03, 0.02, 0.01, 0.98, 0.01, 0.02, 0.03, 0.95),
            ),
        )
    zones = zones_from_config(
        make_edge_weighted_zones(48, width=width, height=height), width, height
    )
    calls_before = native.adaptive_calls if native else 0
    uncertain_before = native.adaptive_reference_zones if native else 0
    wall, cpu, outputs, modes, state_rows, hashes, sampled = [], [], [], [], [], [], []
    sampling_times = []
    history = [(0, 0, 0)] * 48
    process_zone_colors._zone_accumulator = None
    try:
        for index, frame in enumerate(fixtures(width, height, name, length)):
            # Frame generation/hashing are outside timed work, on both paths.
            hashes.append(hashlib.sha256(frame.tobytes()).hexdigest())
            cpu_start = time.process_time()
            started = time.perf_counter()
            colors, raw, _, _, timings, smooth, sent = process_frame(
                frame=frame,
                prev_smoothed_colors=history,
                zones_px=zones,
                device_zone_indices=list(reversed(range(48))),
                params=params,
                return_diagnostics=True,
            )
            payload = _build_hid_zone_frame(colors, channel_indices=(1, 0, 2))
            wall.append((time.perf_counter() - started) * 1000)
            cpu.append((time.process_time() - cpu_start) * 1000)
            sampling_times.append(timings.zone_sampling_ms)
            outputs.append(payload.hex())
            sampled.append(raw.tolist())
            modes.append(list(timings.per_zone_sampling_mode))
            state_rows.append(list(timings.per_zone_palette_temporal_states))
            previous_samples = [tuple(int(c) for c in row) for row in raw.tolist()]
            # Replay the colour history contract used by engine_loop_process.
            params = replace(
                params,
                palette_frame_index=index + 1,
                prev_sampled_zone_colors=previous_samples,
                previous_palette_algorithms=timings.per_zone_sampling_mode,
                zone_palette_temporal_states=timings.per_zone_palette_temporal_states,
                prev_smooth_float_colors=smooth,
                prev_sent_colors=sent,
                prior_zone_sample_motion=zone_sample_motion(
                    raw, params.prev_sampled_zone_colors or None
                ),
                prior_area_average_mode=timings.area_average_active,
                sampling_mode_dwell_remaining=timings.sampling_mode_dwell_remaining,
                dark_zone_stabilize_hold=timings.dark_zone_stabilize_hold,
                blend_hysteresis=timings.blend_hysteresis,
                output_quantization_prev_hold=timings.output_quantization_prev_hold,
                prev_zone_variance=timings.per_zone_variance or params.prev_zone_variance,
            )
            history = colors
    finally:
        process_zone_colors._zone_accumulator = None
    return dict(
        samples_ms=wall,
        cpu_ms=cpu,
        sampling_ms=sampling_times,
        tlv=outputs,
        sampled_rgb=sampled,
        modes=modes,
        temporal_states=state_rows,
        frame_hashes=hashes,
        native_calls=native.adaptive_calls - calls_before if native else 0,
        reference_zones=native.adaptive_reference_zones - uncertain_before if native else 0,
    )


def metrics(values: list[float]) -> dict:
    return dict(
        median_ms=statistics.median(values),
        p95_ms=sorted(values)[round((len(values) - 1) * 0.95)],
        samples_ms=values,
    )


def snapshot() -> dict[Path, str]:
    root = Path.home() / ".config/nanoleaf-kde-sync"
    files = list(root.rglob("*")) if root.exists() else []
    files.append(Path.home() / ".local/share/applications/nanoleaf-kde-sync.desktop")
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}


def run(bridge: Path, length: int, repeats: int, quick: bool, profile: bool) -> dict:
    before = snapshot()
    native = load_rust_box_sampler(bridge)
    result = dict(
        reference_commit="920f575",
        scope="Offline SDR default modes; no capture/USB I/O",
        python=platform.python_version(),
        numpy=np.__version__,
        compiler=native.compiler,
        bridge_sha256=hashlib.sha256(bridge.read_bytes()).hexdigest(),
        frames=length,
        repeats=repeats,
        state="evolving palette/colour history, accumulation and dither",
        order="alternate complete replay order per repeat; isolated global accumulator",
        cases=[],
    )
    for width, height in [(73, 41)] if quick else [(640, 360), (2560, 1440), (3840, 2160)]:
        for name in [
            "flashes_scene_cuts_neutrals",
            "mixed_dark_noise",
            "calibrated_privacy_letterbox",
        ]:
            # Untimed warmup, discarded; each measured replay starts fresh state.
            replay(width, height, name, min(3, length))
            replay(width, height, name, min(3, length), native)
            case = dict(size=[width, height], sequence=name, zones=48, runs=[])
            for repeat in range(repeats):
                runs = {}
                for side in [False, True] if repeat % 2 == 0 else [True, False]:
                    path = "rust" if side else "python"
                    if profile:
                        profiler = cProfile.Profile()
                        data = profiler.runcall(
                            replay, width, height, name, length, native if side else None
                        )
                        rows = []
                        for (file, line, fn), (_, nc, tt, ct, _) in pstats.Stats(
                            profiler
                        ).stats.items():
                            rows.append(
                                dict(
                                    file=file.replace(str(Path.cwd()), "."),
                                    line=line,
                                    name=fn,
                                    calls=nc,
                                    self_seconds=tt,
                                    cumulative_seconds=ct,
                                )
                            )
                        data["profile"] = sorted(rows, key=lambda row: -row["cumulative_seconds"])
                    else:
                        data = replay(width, height, name, length, native if side else None)
                    runs[path] = data
                for key in ["tlv", "sampled_rgb", "modes", "temporal_states", "frame_hashes"]:
                    if runs["python"][key] != runs["rust"][key]:
                        raise AssertionError(f"Adaptive parity failed for {name}: {key}")
                if native.disabled_reason:
                    raise AssertionError(native.disabled_reason)
                row = dict(
                    exact_parity=True,
                    native_calls=runs["rust"]["native_calls"],
                    reference_zones=runs["rust"]["reference_zones"],
                    modes=dict(
                        Counter(mode for frame in runs["python"]["modes"] for mode in frame)
                    ),
                    frame_hashes=runs["python"]["frame_hashes"],
                    metrics={},
                )
                for path, data in runs.items():
                    for key in ["samples_ms", "cpu_ms", "sampling_ms"]:
                        row["metrics"][path + "_" + key] = metrics(data[key])
                    if profile:
                        row[path + "_profile"] = data["profile"]
                case["runs"].append(row)
            result["cases"].append(case)
    result["config_calibration_launcher_unchanged"] = snapshot() == before
    if not result["config_calibration_launcher_unchanged"]:
        raise AssertionError("User files changed during offline replay")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    if not (1 <= args.frames <= 1000 and 1 <= args.repeats <= 100):
        parser.error("Invalid replay bounds")
    result = run(args.bridge.resolve(), args.frames, args.repeats, args.quick, args.profile)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
