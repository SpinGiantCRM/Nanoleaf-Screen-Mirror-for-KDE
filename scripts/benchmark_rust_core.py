"""Compare the offline Rust core with the recovered Python box sampler.

No user config loading, capture, HID, installation or live runtime changes.
Fixtures are regenerated in a temporary directory. Run from any directory with
the repository's development Python; build the release probe with Cargo first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import statistics
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from nanoleaf_sync.device import protocol
from nanoleaf_sync.runtime.processing import zones_from_config
from nanoleaf_sync.runtime.srgb import srgb_u8_to_linear01
from nanoleaf_sync.runtime.zone_presets import make_edge_weighted_zones
from nanoleaf_sync.runtime.zones import _zone_colors_via_box_filter, edge_anchored_rect

ROOT = Path(__file__).resolve().parents[1]
FRAME_HEADER = struct.Struct("<8sQQQ")
ZONE_HEADER = struct.Struct("<8sQQ")
RECT = struct.Struct("<qqqq")


def write_fixture(directory: Path, frame: np.ndarray, zones: list[tuple[int, int, int, int]]):
    height, width, _ = frame.shape
    # Deliberate row padding tests the explicit-stride contract too.
    stride = width * 3 + 7
    rows = np.full((height, stride), 123, dtype=np.uint8)
    rows[:, : width * 3] = frame.reshape(height, width * 3)
    blob = FRAME_HEADER.pack(b"NSRGB001", width, height, stride) + rows.tobytes()
    frame_path = directory / "frame.bin"
    zone_path = directory / "zones.bin"
    frame_path.write_bytes(blob)
    zone_path.write_bytes(
        ZONE_HEADER.pack(b"NZONE001", len(zones), len(zones))
        + b"".join(RECT.pack(*zone) for zone in zones)
    )
    return frame_path, zone_path, hashlib.sha256(blob).hexdigest()


def metrics(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "samples_ms": samples,
        "median_ms": statistics.median(samples),
        "p95_ms": ordered[round((len(ordered) - 1) * 0.95)],
        "max_ms": max(samples),
    }


def memory_kib() -> dict:
    fields = {}
    for line in Path("/proc/self/smaps_rollup").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"Rss", "Pss"}:
            fields[key.lower()] = int(value.split()[0])
    return fields


def python_probe(frame_path: Path, zone_path: Path, iterations: int, warmup: int) -> dict:
    blob = frame_path.read_bytes()
    magic, width, height, stride = FRAME_HEADER.unpack_from(blob)
    if magic != b"NSRGB001":
        raise ValueError("Expected SDR sRGB RGB8 fixture")
    frame = np.frombuffer(blob, dtype=np.uint8, offset=FRAME_HEADER.size).reshape(height, stride)
    frame = frame[:, : width * 3].reshape(height, width, 3)
    zones_blob = zone_path.read_bytes()
    zone_magic, count, manual_count = ZONE_HEADER.unpack_from(zones_blob)
    if zone_magic != b"NZONE001" or manual_count != count:
        raise ValueError("Invalid manual-count fixture")
    zones = list(RECT.iter_unpack(zones_blob[ZONE_HEADER.size :]))
    if len(zones) != count:
        raise ValueError("Invalid zone fixture length")

    def sample():
        return _zone_colors_via_box_filter(
            frame, zones, edge_locality="tight", edge_anchor=False, use_multi_moment=False
        )

    for _ in range(warmup):
        sample()
    timings = []
    cpu_start = time.process_time()
    for _ in range(iterations):
        started = time.perf_counter()
        colors, variances = sample()
        timings.append((time.perf_counter() - started) * 1000)
    cpu_ms = (time.process_time() - cpu_start) * 1000
    return {
        "metrics": metrics(timings),
        "timed_kernel_cpu_ms": cpu_ms,
        "memory_kib": memory_kib(),
        "rgb": colors.tolist(),
        "variance": variances.tolist(),
    }


def check_protocol(probe: Path) -> int:
    vectors = json.loads((ROOT / "native/fixtures/protocol.json").read_text())
    errors = {
        "short_read": protocol.ProtocolShortReadError,
        "response_type": protocol.ProtocolResponseTypeError,
        "missing_status": protocol.ProtocolMalformedResponseError,
        "command_failed": protocol.ProtocolCommandError,
    }
    checked = 0
    for kind, fixtures in (("request", vectors["requests"]), ("response", vectors["responses"])):
        for fixture in fixtures:
            data = bytes.fromhex(fixture.get("payload", fixture.get("frame", "")))
            command = int(fixture["command"], 16)
            native = subprocess.run(
                [str(probe), kind, fixture["command"], data.hex()],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if "error" in fixture:
                try:
                    protocol.NanoleafTLVProtocol.parse_response(command, data)
                except errors[fixture["error"]]:
                    pass
                else:
                    raise AssertionError("Python did not reject malformed response")
                if native.returncode != 2 or native.stderr.strip() != fixture["error"]:
                    raise AssertionError(f"Rust protocol mismatch: {fixture}")
            else:
                expected = bytes.fromhex(fixture["expected"])
                python = (
                    protocol.NanoleafTLVProtocol.build_request(command, data)
                    if kind == "request"
                    else protocol.NanoleafTLVProtocol.parse_response(command, data)
                )
                if (
                    python != expected
                    or native.returncode != 0
                    or native.stdout.strip() != expected.hex()
                ):
                    raise AssertionError(f"Protocol fixture mismatch: {fixture}")
            checked += 1
    return checked


def check_rejections(probe: Path, directory: Path) -> int:
    frame = FRAME_HEADER.pack(b"NSRGB001", 1, 1, 3) + bytes(3)
    zones = ZONE_HEADER.pack(b"NZONE001", 1, 1) + RECT.pack(0, 0, 1, 1)
    fixtures = [
        (b"NHDR0001" + frame[8:], zones, "expected explicit SDR"),
        (frame[:8], zones, "truncated header"),
        (FRAME_HEADER.pack(b"NSRGB001", 0, 1, 0), zones, "InvalidDimensions"),
        (FRAME_HEADER.pack(b"NSRGB001", 1, 1, 2) + bytes(3), zones, "InvalidStride"),
        (frame[:-1], zones, "TruncatedFrame"),
        (frame, ZONE_HEADER.pack(b"NZONE001", 1, 48) + zones[24:], "manual zone count"),
        (frame, zones[:-1], "invalid zone fixture length"),
        (FRAME_HEADER.pack(b"NSRGB001", 2**64 - 1, 1, 2**64 - 1), zones, "GeometryOverflow"),
    ]
    frame_path, zone_path = directory / "bad-frame.bin", directory / "bad-zones.bin"
    for frame_blob, zone_blob, error in fixtures:
        frame_path.write_bytes(frame_blob)
        zone_path.write_bytes(zone_blob)
        completed = subprocess.run(
            [str(probe), "sample", str(frame_path), str(zone_path), "1", "0"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if completed.returncode != 2 or error not in completed.stderr:
            raise AssertionError(f"Malformed native fixture was not rejected: {error}")
    return len(fixtures)


def cases(quick: bool):
    for width, height in [(33, 37)] if quick else [(640, 360), (2560, 1440), (3840, 2160)]:
        frame = np.random.default_rng(42).integers(0, 256, (height, width, 3), dtype=np.uint8)
        zone_models = make_edge_weighted_zones(
            48, width=width, height=height, edge_locality="tight"
        )
        zones = zones_from_config(zone_models, width, height)
        effective = [edge_anchored_rect(zone, width, height) for zone in zones]
        yield f"seed42_{width}x{height}", frame, effective
    for name, rgb in [
        ("black", (0, 0, 0)),
        ("grey", (128, 128, 128)),
        ("white", (255, 255, 255)),
        ("red", (255, 0, 0)),
        ("green", (0, 255, 0)),
        ("blue", (0, 0, 255)),
    ]:
        frame = np.full((19, 31, 3), rgb, dtype=np.uint8)
        yield name, frame, [(0, 0, 31, 19)]
    frame = np.zeros((33, 37, 3), dtype=np.uint8)
    frame[:, 19:] = 255
    frame[-1, :] = 255
    yield "mixed_neutral_remainders", frame, [(0, 0, 37, 33), (35, 31, 8, 8)]
    frame = np.zeros((13, 17, 3), dtype=np.uint8)
    frame[:, :4] = (200, 0, 0)
    frame[4:9, 5:13] = (0, 0, 255)
    yield "local_edges", frame, [(0, 0, 4, 13), (5, 4, 8, 5), (14, 0, 3, 13)]


def snapshot_user_files() -> dict[Path, bytes | None]:
    config_dir = Path.home() / ".config/nanoleaf-kde-sync"
    paths = [
        config_dir / "config.toml",
        Path.home() / ".local/share/applications/nanoleaf-kde-sync.desktop",
    ]
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def run_comparison(probe: Path, iterations: int, warmup: int, repeats: int, quick: bool) -> dict:
    original_files = snapshot_user_files()
    result = {
        "reference_commit": "6c2bbd5",
        "python": platform.python_version(),
        "kernel": platform.release(),
        "protocol_vectors_passed": check_protocol(probe),
        "iterations": iterations,
        "warmup": warmup,
        "repeats": repeats,
        "cases": [],
        "scope": "SDR CPU zone mean/variance only; not full-app or capture/USB timings",
        "rustc": subprocess.run(
            ["rustc", "--version"], check=True, capture_output=True, text=True
        ).stdout.strip(),
        "probe_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
    }
    with tempfile.TemporaryDirectory(prefix="nanoleaf-core-fixtures-") as temporary:
        result["malformed_fixture_rejections"] = check_rejections(probe, Path(temporary))
        for name, frame, zones in cases(quick):
            frame_path, zone_path, digest = write_fixture(Path(temporary), frame, zones)
            row = {
                "name": name,
                "width": frame.shape[1],
                "height": frame.shape[0],
                "zones": len(zones),
                "frame_sha256": digest,
                "runs": [],
            }
            for repeat in range(repeats):
                # Alternate execution order; no benchmark or test runs concurrently.
                commands = {
                    "rust": [
                        str(probe),
                        "sample",
                        str(frame_path),
                        str(zone_path),
                        str(iterations),
                        str(warmup),
                    ],
                    "python": [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--python-probe",
                        str(frame_path),
                        str(zone_path),
                        str(iterations),
                        str(warmup),
                    ],
                }
                run = {}
                for language in ("rust", "python") if repeat % 2 == 0 else ("python", "rust"):
                    child_cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
                    started = time.perf_counter()
                    completed = subprocess.run(
                        commands[language], check=True, capture_output=True, text=True, timeout=60
                    )
                    child_cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
                    data = json.loads(completed.stdout)
                    data["spawn_load_sample_exit_ms"] = (time.perf_counter() - started) * 1000
                    data["whole_child_cpu_ms"] = (
                        (child_cpu_after.ru_utime + child_cpu_after.ru_stime)
                        - (child_cpu_before.ru_utime + child_cpu_before.ru_stime)
                    ) * 1000
                    run[language] = data
                rust_colors = np.array(
                    [zone["rgb"] for zone in run["rust"]["zones"]], dtype=np.int16
                )
                python_colors = np.array(run["python"]["rgb"], dtype=np.int16)
                delta = int(np.max(np.abs(rust_colors - python_colors)))
                if delta > 1 or (
                    name in {"black", "grey", "white", "red", "green", "blue"} and delta
                ):
                    raise AssertionError(f"RGB parity failed for {name}: {delta}")
                variance_delta = max(
                    abs(float(rust_zone["variance"]) - float(python_variance))
                    for rust_zone, python_variance in zip(
                        run["rust"]["zones"], run["python"]["variance"], strict=True
                    )
                )
                if variance_delta > 0.002:
                    raise AssertionError(f"Variance parity failed for {name}: {variance_delta}")
                max_linear_delta = 0.0
                for rect, rust_zone in zip(zones, run["rust"]["zones"], strict=True):
                    x, y, width, height = rect
                    patch = frame[
                        y : min(y + height, frame.shape[0]), x : min(x + width, frame.shape[1])
                    ]
                    linear = (
                        srgb_u8_to_linear01(patch).astype(np.float64).reshape(-1, 3).mean(axis=0)
                    )
                    max_linear_delta = max(
                        max_linear_delta, float(np.max(np.abs(linear - rust_zone["linear"])))
                    )
                if max_linear_delta > 1e-7:
                    raise AssertionError(
                        f"Linear-light parity failed for {name}: {max_linear_delta}"
                    )
                native_payload = rust_colors[:, [1, 0, 2]].astype(np.uint8).tobytes()
                expected_tlv = protocol.NanoleafTLVProtocol.build_request(2, native_payload).hex()
                if run["rust"]["grb_tlv_hex"] != expected_tlv:
                    raise AssertionError("Native sampled-frame TLV differs from Python encoding")
                run["max_rgb_code_difference"] = delta
                run["max_variance_difference"] = variance_delta
                run["max_linear_difference"] = max_linear_delta
                row["runs"].append(run)
            result["cases"].append(row)
    result["config_and_launcher_bytes_unchanged"] = snapshot_user_files() == original_files
    if not result["config_and_launcher_bytes_unchanged"]:
        raise AssertionError("User configuration/launcher changed during prototype comparison")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe", type=Path, default=ROOT / "native/target/release/nanoleaf-core-probe"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--python-probe", nargs=4, metavar=("FRAME", "ZONES", "ITERATIONS", "WARMUP")
    )
    args = parser.parse_args()
    if args.python_probe:
        frame_path, zone_path, iterations, warmup = args.python_probe
        print(
            json.dumps(
                python_probe(Path(frame_path), Path(zone_path), int(iterations), int(warmup))
            )
        )
        return
    if not (
        1 <= args.iterations <= 100_000 and 0 <= args.warmup <= 10_000 and 1 <= args.repeats <= 100
    ):
        parser.error("invalid offline benchmark iteration/warmup/repeat bounds")
    if not args.output:
        parser.error("--output is required")
    result = run_comparison(
        args.probe.resolve(), args.iterations, args.warmup, args.repeats, args.quick
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
