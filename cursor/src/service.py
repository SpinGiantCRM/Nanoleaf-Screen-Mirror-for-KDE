from __future__ import annotations

import signal
import threading
import time
from typing import List, Optional, Sequence, Tuple

from capture.factory import create_capture_backend
from color.analyzer import zone_colors
from color.zone_mapper import map_colors_to_device_zones
from config import AppConfig, ConfigManager, ZoneConfig
from device.nanoleaf_usb import MockNanoleafUSBDriver, NanoleafUSBDriver, NanoleafUSBIds


RGBTuple = Tuple[int, int, int]


def _clamp_u8(x: float) -> int:
    if x <= 0:
        return 0
    if x >= 255:
        return 255
    return int(round(x))


def _apply_brightness(colors: Sequence[RGBTuple], brightness: float) -> List[RGBTuple]:
    b = max(0.0, min(1.0, float(brightness)))
    if b == 1.0:
        return list(colors)
    out: List[RGBTuple] = []
    for r, g, bb in colors:
        out.append((_clamp_u8(r * b), _clamp_u8(g * b), _clamp_u8(bb * b)))
    return out


def _ema_smooth(
    prev: Sequence[RGBTuple],
    current: Sequence[RGBTuple],
    alpha: float,
) -> List[RGBTuple]:
    """
    Exponential moving average.

    ema = alpha * current + (1-alpha) * prev
    """

    a = max(0.0, min(1.0, float(alpha)))
    if not prev:
        return list(current)
    out: List[RGBTuple] = []
    for (pr, pg, pb), (cr, cg, cb) in zip(prev, current):
        out.append(
            (
                _clamp_u8(a * cr + (1.0 - a) * pr),
                _clamp_u8(a * cg + (1.0 - a) * pg),
                _clamp_u8(a * cb + (1.0 - a) * pb),
            )
        )
    return out


def _zones_from_config(zones: Sequence[ZoneConfig], width: int, height: int) -> List[Tuple[int, int, int, int]]:
    if not zones:
        # Default single zone covering entire screen.
        return [(0, 0, width, height)]

    out: List[Tuple[int, int, int, int]] = []
    for z in zones:
        x = int(z.x * width)
        y = int(z.y * height)
        w = int(z.w * width)
        h = int(z.h * height)
        out.append((x, y, w, h))
    return out


class NanoleafSyncService:
    """
    Main service loop:
    - capture frame
    - extract per-zone colors
    - apply brightness + smoothing
    - send frame over USB HID (protocol stub)
    """

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        *,
        capture_backend_override=None,
        driver_override=None,
    ) -> None:
        self.config = config or AppConfig()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._driver = None
        self._capture = None

        self._prev_smoothed_colors: List[RGBTuple] = []

        self._capture_backend_override = capture_backend_override
        self._driver_override = driver_override

        self._consecutive_errors = 0
        self.last_error: Optional[str] = None

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self.run, name="nanoleaf-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is None:
            return
        self._thread.join(timeout=timeout)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_status(self) -> dict:
        """
        Lightweight status for debugging and UI.

        Avoids requiring the UI to touch private thread internals.
        """

        capture_backend_name = getattr(self._capture, "name", None) if self._capture is not None else None
        capture_path = getattr(self._capture, "last_capture_path", None) if self._capture is not None else None
        return {
            "running": self.is_running(),
            "last_error": self.last_error,
            "capture_backend": capture_backend_name,
            "capture_path": capture_path,
            "consecutive_errors": self._consecutive_errors,
        }

    def _make_device_driver(self):
        # Placeholder VID/PID values until official spec arrives.
        ids = NanoleafUSBIds(vid=self.config.device_vid, pid=self.config.device_pid)
        if self.config.use_mock_device:
            return MockNanoleafUSBDriver(ids=ids)
        return NanoleafUSBDriver(ids=ids)

    def _install_drivers(self, width: int, height: int) -> None:
        if self._capture_backend_override is not None:
            self._capture = self._capture_backend_override
        else:
            self._capture = create_capture_backend(
                width=width,
                height=height,
                use_mock_capture=self.config.use_mock_capture,
                prefer_backend=self.config.prefer_backend,
                allow_fallback=getattr(self.config, "allow_capture_fallback", True),
                hdr_max_nits=self.config.hdr_max_nits,
                hdr_transfer=self.config.hdr_transfer,
                hdr_primaries=self.config.hdr_primaries,
            )

        if self._driver_override is not None:
            self._driver = self._driver_override
        else:
            self._driver = self._make_device_driver()

        self._driver.initialize()

        # Refresh status fields based on chosen backends.
        # (No allocations; just reads metadata for debugging.)
        _ = self.get_status()

    def run(self) -> None:
        self._prev_smoothed_colors = []
        self._consecutive_errors = 0
        self.last_error = None

        # Initial capture dimensions: KMSGrabCapture requires width/height.
        # We start from a conservative default and allow future enhancement to
        # auto-detect monitor size.
        width = 1920
        height = 1080
        self._install_drivers(width, height)

        fps = max(1, int(self.config.fps))
        interval_s = 1.0 / fps

        next_deadline = time.perf_counter()
        last_log = 0.0
        last_sent_zone_count = 0

        # Main loop
        while not self._stop_event.is_set():
            start = time.perf_counter()
            if start < next_deadline:
                # If we're early, wait a bit to keep capture rate stable.
                # (time.sleep is coarse on some systems; keep it short.)
                time.sleep(min(0.002, next_deadline - start))

            try:
                # Step 1: capture
                frame = self._capture.capture()
                # Ensure expected dtype/shape.
                if frame is None:
                    continue
                if frame.ndim != 3 or frame.shape[2] != 3:
                    raise RuntimeError(
                        f"Capture returned unexpected frame shape: {getattr(frame, 'shape', None)}"
                    )

                img_h, img_w, _ = frame.shape

                # Step 2: per-zone colors
                zones_px = _zones_from_config(self.config.zones, img_w, img_h)
                raw_colors = zone_colors(frame, zones_px)

                # Step 3: calibration mapping (sampled screen zones -> device zones)
                device_zone_count = self.config.device_zone_count or len(raw_colors)
                mapped_colors = map_colors_to_device_zones(
                    raw_colors,
                    device_zone_count=device_zone_count,
                    zone_offset=self.config.zone_offset,
                    reverse=self.config.reverse_zones,
                    explicit_zone_map=self.config.explicit_zone_map or None,
                )

                # Step 4: brightness + smoothing
                bright_colors = _apply_brightness(mapped_colors, self.config.brightness)
                smoothed_colors = _ema_smooth(
                    self._prev_smoothed_colors,
                    bright_colors,
                    alpha=self.config.smoothing,
                )
                self._prev_smoothed_colors = smoothed_colors

                # Step 5: send to device
                self._driver.send_frame(smoothed_colors)

                self._consecutive_errors = 0
                self.last_error = None
                last_sent_zone_count = len(smoothed_colors)
            except Exception as e:
                self._consecutive_errors += 1
                self.last_error = str(e)
                if self.config.verbose:
                    print(f"[service] frame error #{self._consecutive_errors}: {e}")

                # Try to recover after a small number of consecutive failures.
                if self._consecutive_errors >= 5:
                    try:
                        if self._driver is not None:
                            self._driver.close()
                    except Exception:
                        pass

                    try:
                        # Re-install both capture and driver via the same selection path.
                        self._install_drivers(width=1920, height=1080)
                    except Exception:
                        # If recovery fails, keep looping; error counters will continue.
                        pass
                    self._consecutive_errors = 0

            # Step 6: maintain FPS / low latency
            next_deadline += interval_s
            now = time.perf_counter()
            if now - last_log > 5.0:
                last_log = now
                if self.config.verbose:
                    elapsed_ms = (now - start) * 1000.0
                    print(
                        f"[service] tick fps={fps} elapsed_ms={elapsed_ms:.2f} zones={last_sent_zone_count}"
                    )

            # If we're behind schedule, skip waiting to catch up.
            if now < next_deadline:
                time.sleep(next_deadline - now)

        # Shutdown
        try:
            if self._driver is not None:
                self._driver.close()
        finally:
            self._driver = None

    def install_signal_handlers(self) -> None:
        """
        Install SIGINT/SIGTERM handlers to stop the loop.

        If you run inside a Qt application, you may prefer to stop via UI actions
        and not install these handlers.
        """

        def _handler(signum, _frame):
            self.stop()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)


def main() -> None:  # pragma: no cover
    cfg_mgr = ConfigManager()
    config = cfg_mgr.load()

    service = NanoleafSyncService(config=config)
    service.install_signal_handlers()
    service.start()
    # Wait for the service thread to exit.
    while service.is_running():
        time.sleep(0.25)


if __name__ == "__main__":  # pragma: no cover
    main()

