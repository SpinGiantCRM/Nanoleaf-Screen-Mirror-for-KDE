"""Bounded audit measurements; never save screen pixels or user configuration.

Run with the repository venv. --live exercises capture and low-brightness USB
output for ten seconds; only run with the strip otherwise unused.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path


def memory_kib() -> dict[str, int]:
    fields = {}
    for line in Path("/proc/self/smaps_rollup").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"Rss", "Pss", "Private_Dirty", "Private_Clean"}:
            fields[key] = int(value.split()[0])
    return fields


def summary(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    if not ordered:
        return {"samples": 0}
    return {
        "samples": len(values),
        "median_ms": statistics.median(values),
        "p95_ms": ordered[round((len(ordered) - 1) * 0.95)],
        "max_ms": max(values),
    }


def import_probe(code: str) -> dict:
    child = f"""
import json, time
from pathlib import Path
t = time.perf_counter()
{code}
ready = time.perf_counter()
fields = {{}}
for line in Path('/proc/self/smaps_rollup').read_text().splitlines():
    key, _, value = line.partition(':')
    if key in {{'Rss', 'Pss'}}:
        fields[key] = int(value.split()[0])
cpu = time.process_time()
time.sleep(2)
print(json.dumps({{'import_ms': (ready-t)*1000, 'memory_kib': fields,
                 'sleep_idle_cpu_percent_one_core': (time.process_time()-cpu)/2*100}}))
"""
    start = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-c", child],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    data = json.loads(result.stdout)
    # Includes interpreter, process creation and teardown; subtract the fixed sleep.
    data["spawn_import_exit_minus_sleep_ms"] = (time.perf_counter() - start - 2) * 1000
    return data


def offline() -> dict:
    from nanoleaf_sync.tools.benchmark import run_benchmark

    result = {
        "kind": "offline-synthetic-and-import-baseline",
        "python": platform.python_version(),
        "kernel": platform.release(),
        "imports": {
            name: import_probe(code)
            for name, code in {
                "interpreter": "pass",
                "numpy": "import numpy",
                "service_import": "import nanoleaf_sync.service",
                "tray_import": "import nanoleaf_sync.ui.tray_app",
                "qt_application_only": (
                    "from PyQt6.QtWidgets import QApplication; app = QApplication([])"
                ),
            }.items()
        },
    }
    result["production_runs"] = [run_benchmark(preset_name="production") for _ in range(3)]
    return result


def live(fps_override: int | None = None) -> dict:
    from dataclasses import asdict

    from nanoleaf_sync.config.store import ConfigManager
    from nanoleaf_sync.device.interfaces import NanoleafUSBIds
    from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver
    from nanoleaf_sync.runtime import engine_loop_process
    from nanoleaf_sync.service import NanoleafSyncService

    cfg = ConfigManager().load()
    if fps_override is not None:
        cfg.fps = fps_override
    processing_samples = []
    original_process = engine_loop_process.process_frame

    def measured_process(**kwargs):
        started = time.perf_counter()
        output = original_process(**kwargs)
        processing_samples.append(
            {
                "call_ms": (time.perf_counter() - started) * 1000,
                "timings": {
                    key: value for key, value in asdict(output[4]).items() if key.endswith("_ms")
                },
            }
        )
        return output

    engine_loop_process.process_frame = measured_process
    driver = NanoleafUSBDriver(
        ids=NanoleafUSBIds(cfg.device_vid, cfg.device_pid),
        configured_zone_count=cfg.device_zone_count,
        output_channel_order=cfg.output_channel_order,
        prefer_write_only_live_send=False,
    )
    result: dict = {
        "kind": "live-service-baseline",
        "runtime_seconds": 10,
        "fps_override": fps_override,
        "processing_instrumented": True,
    }
    original_on = None
    original_brightness = None
    service = None
    try:
        start = time.perf_counter()
        driver.initialize()
        result["usb_initialize_ms"] = (time.perf_counter() - start) * 1000
        result["device_model"] = driver.model_number
        result["manual_zone_count"] = cfg.device_zone_count
        original_on = driver.get_on_off_state()
        original_brightness = driver.get_brightness()
        driver.set_brightness(16)
        driver.set_on_off_state(True)
        usb_timings = []
        for rgb in [(0, 0, 0), (24, 24, 24), (24, 0, 0), (0, 24, 0), (0, 0, 24)]:
            for _ in range(6):
                started = time.perf_counter()
                driver.send_frame([rgb] * cfg.device_zone_count)
                usb_timings.append(
                    {
                        "rgb": rgb,
                        "call_ms": (time.perf_counter() - started) * 1000,
                        "driver": dict(driver.last_send_timing),
                    }
                )
                time.sleep(0.05)
        result["usb_pattern_samples"] = usb_timings
        service = NanoleafSyncService(config=cfg, driver_override=driver)
        started = time.perf_counter()
        cpu_start = time.process_time()
        result["start_returned"] = service.start()
        result["service_start_call_ms"] = (time.perf_counter() - started) * 1000
        result["start_process_cpu_ms"] = (time.process_time() - cpu_start) * 1000
        cpu = time.process_time()
        window_start = time.perf_counter()
        time.sleep(10)
        elapsed = time.perf_counter() - window_start
        result["window_seconds"] = elapsed
        result["cpu_percent_one_core"] = (time.process_time() - cpu) / elapsed * 100
        result["memory_kib"] = memory_kib()
        status = service.get_status()
        result["processing_samples"] = processing_samples
        # Keep only operational fields, no paths, screen images, restore tokens or EDID.
        result["status"] = {
            k: v
            for k, v in status.items()
            if k
            in {
                "running",
                "frames_sent",
                "frames_captured",
                "frames_processed",
                "last_error",
                "last_error_kind",
                "last_error_guidance",
                "lifecycle_state",
                "startup_state",
                "effective_capture_backend",
                "capture_backend",
                "capture_path",
                "latency_measurement",
                "fps",
                "target_fps",
                "actual_fps",
                "stale_output_dropped_frames",
                "duplicate_output_skipped_frames",
                "capture_buffer_dropped_frames",
                "process_buffer_dropped_frames",
            }
        }
        started = time.perf_counter()
        result["stop_returned"] = service.stop(timeout=6)
        result["stop_call_ms"] = (time.perf_counter() - started) * 1000
        result["running_after_stop"] = service.is_running()
        service.join(timeout=2)
        cpu = time.process_time()
        time.sleep(2)
        result["stopped_service_idle_cpu_percent_one_core"] = (time.process_time() - cpu) / 2 * 100
    finally:
        engine_loop_process.process_frame = original_process
        if service is not None and service.is_running():
            service.stop(timeout=6)
        # stop() closes the override too. Reopen solely to black out and restore state.
        driver.close()
        if original_on is not None and original_brightness is not None:
            try:
                driver.initialize()
                driver.send_frame([(0, 0, 0)] * cfg.device_zone_count)
                driver.set_brightness(original_brightness)
                driver.set_on_off_state(original_on)
            finally:
                driver.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--fps-override",
        type=int,
        default=None,
        help="Live A/B only: override existing Target FPS in memory.",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = live(args.fps_override) if args.live else offline()
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
