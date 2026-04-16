from __future__ import annotations

import logging
import signal
import threading
import time
from typing import List, Optional, Sequence, Tuple

from nanoleaf_sync.capture.factory import create_capture_backend
from nanoleaf_sync.processing.analyzer import zone_colors
from nanoleaf_sync.processing.zone_mapper import map_colors_to_device_zones
from nanoleaf_sync.config import AppConfig, ConfigManager, ZoneConfig
from nanoleaf_sync.device.interfaces import DeviceDriver
from nanoleaf_sync.device.nanoleaf_usb import MockNanoleafUSBDriver, NanoleafUSBDriver, NanoleafUSBIds


RGBTuple = Tuple[int, int, int]

logger = logging.getLogger(__name__)

# Default capture dimensions used when no monitor-size detection is available.
# Stored as a module constant so there is one obvious place to update once
# autodetection is implemented.
_DEFAULT_CAPTURE_WIDTH = 1920
_DEFAULT_CAPTURE_HEIGHT = 1080


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


def _zones_from_config(
    zones: Sequence[ZoneConfig], width: int, height: int
) -> List[Tuple[int, int, int, int]]:
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


def _resolve_capture_dims(config: AppConfig) -> Tuple[int, int]:
    """
    Return (width, height) for capture initialization.

    Currently falls back to the module-level defaults because monitor
    autodetection is not yet implemented.  Once a detection path exists,
    it should be wired in here so there is one authoritative source.
    """
    return _DEFAULT_CAPTURE_WIDTH, _DEFAULT_CAPTURE_HEIGHT


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
        self.frames_sent = 0
        self.last_frame_timestamp: Optional[float] = None
        self._last_reinit_ts = 0.0
        self._startup_complete = threading.Event()
        self._startup_succeeded = False

        # Dimensions resolved once at start and reused for recovery.
        # Stored so recovery uses the same geometry as the initial setup.
        self._capture_width, self._capture_height = _resolve_capture_dims(self.config)

    def start(self) -> bool:
        if self.is_running():
            return True
        self._stop_event.clear()
        self._startup_complete.clear()
        self._startup_succeeded = False
        self._thread = threading.Thread(
            target=self.run, name="nanoleaf-sync", daemon=True
        )
        self._thread.start()
        # Briefly wait for startup to either succeed or fail so callers (UI/tray)
        # can reflect the real runtime state instead of assuming success.
        self._startup_complete.wait(timeout=1.0)
        if self._startup_complete.is_set() and not self._startup_succeeded:
            self.join(timeout=0.2)
            return False
        return self.is_running()

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

        The 'capture_mode' field makes it explicit whether the active capture
        path is mock, a real backend, or a fallback stub — so degraded or
        placeholder paths are always visible.
        """

        capture_backend_name = (
            getattr(self._capture, "name", None) if self._capture is not None else None
        )
        capture_path = (
            getattr(self._capture, "last_capture_path", None)
            if self._capture is not None
            else None
        )

        # Classify capture mode explicitly so the UI can surface it clearly.
        if capture_backend_name == "mock":
            capture_mode = "mock"
        elif capture_backend_name in ("kwin-dbus",):
            capture_mode = "stub-fallback"
        elif capture_backend_name == "kmsgrab" and capture_path == "kwin-dbus":
            capture_mode = "stub-fallback"
        elif capture_backend_name == "replay":
            capture_mode = "replay"
        elif capture_backend_name == "kmsgrab":
            capture_mode = "real"
        else:
            capture_mode = "unknown"

        return {
            "running": self.is_running(),
            "last_error": self.last_error,
            "capture_backend": capture_backend_name,
            "capture_path": capture_path,
            "capture_mode": capture_mode,
            "capture_width": self._capture_width,
            "capture_height": self._capture_height,
            "consecutive_errors": self._consecutive_errors,
            "frames_sent": self.frames_sent,
            "last_frame_timestamp": self.last_frame_timestamp,
            "max_consecutive_errors": self.config.max_consecutive_errors,
            "reinit_backoff_ms": self.config.reinit_backoff_ms,
        }

    def _make_device_driver(self) -> DeviceDriver:
        ids = NanoleafUSBIds(vid=self.config.device_vid, pid=self.config.device_pid)
        if self.config.use_mock_device:
            return MockNanoleafUSBDriver(ids=ids)
        return NanoleafUSBDriver(ids=ids)

    def _close_backends(self) -> None:
        """
        Explicitly close both capture and device backends.

        Called on normal shutdown and before recovery reinit to avoid file
        descriptor or D-Bus resource leaks once real backends are in use.
        """
        if self._capture is not None:
            try:
                close_fn = getattr(self._capture, "close", None)
                if close_fn is not None:
                    close_fn()
            except Exception:
                pass

        if self._driver is not None:
            try:
                self._driver.close()
            except Exception:
                pass

    def _install_drivers(self) -> None:
        """
        Initialize capture and device backends using stored dimensions.

        Always uses self._capture_width / self._capture_height so recovery
        uses the same geometry as the initial setup.
        """
        width = self._capture_width
        height = self._capture_height

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
                replay_frames_path=getattr(self.config, "replay_frames_path", "")
                or None,
            )

        if self._driver_override is not None:
            self._driver = self._driver_override
        else:
            self._driver = self._make_device_driver()

        self._driver.initialize()

    def run(self) -> None:
        self._prev_smoothed_colors = []
        self._consecutive_errors = 0
        self.last_error = None
        self.frames_sent = 0
        self.last_frame_timestamp = None

        try:
            self._install_drivers()
        except Exception as e:
            self.last_error = str(e)
            self._startup_succeeded = False
            self._startup_complete.set()
            logger.exception("service startup failed")
            self._close_backends()
            self._capture = None
            self._driver = None
            return

        self._startup_succeeded = True
        self._startup_complete.set()

        fps = max(1, int(self.config.fps))
        interval_s = 1.0 / fps

        next_deadline = time.perf_counter()
        last_log = 0.0
        log_interval_s = float(getattr(self.config, "status_log_interval_s", 5.0))
        last_sent_zone_count = 0

        # Main loop
        while not self._stop_event.is_set():
            start = time.perf_counter()
            if start < next_deadline:
                time.sleep(min(0.002, next_deadline - start))

            try:
                # Step 1: capture
                frame = self._capture.capture()
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
                self.frames_sent += 1
                self.last_frame_timestamp = time.time()
                last_sent_zone_count = len(smoothed_colors)
            except Exception as e:
                self._consecutive_errors += 1
                self.last_error = str(e)
                logger.warning("frame processing failed", exc_info=self.config.verbose)
                if self.config.verbose:
                    print(f"[service] frame error #{self._consecutive_errors}: {e}")

                error_limit = max(
                    1, int(getattr(self.config, "max_consecutive_errors", 5))
                )
                backoff_s = max(
                    0.0, float(getattr(self.config, "reinit_backoff_ms", 500)) / 1000.0
                )

                # Attempt recovery with adaptive backoff and explicit threshold.
                if self._consecutive_errors >= error_limit:
                    now_ts = time.perf_counter()
                    if now_ts - self._last_reinit_ts >= backoff_s:
                        self._close_backends()
                        try:
                            self._install_drivers()
                            self._last_reinit_ts = now_ts
                        except Exception:
                            logger.exception("backend reinitialization failed")
                    self._consecutive_errors = 0

            # Step 6: maintain FPS / low latency
            next_deadline += interval_s
            now = time.perf_counter()
            if now - last_log > log_interval_s:
                last_log = now
                elapsed_ms = (now - start) * 1000.0
                logger.info(
                    "service_tick fps=%s elapsed_ms=%.2f zones=%s errors=%s",
                    fps,
                    elapsed_ms,
                    last_sent_zone_count,
                    self._consecutive_errors,
                )
                if self.config.verbose:
                    print(
                        f"[service] tick fps={fps} elapsed_ms={elapsed_ms:.2f} zones={last_sent_zone_count}"
                    )

            if now < next_deadline:
                time.sleep(next_deadline - now)

        # Shutdown: explicitly close both backends to release resources.
        self._close_backends()
        self._capture = None
        self._driver = None

    def install_signal_handlers(self) -> None:
        """
        Install SIGINT/SIGTERM handlers to stop the loop.
        """

        def _handler(signum, _frame):
            self.stop()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)


def main() -> None:  # pragma: no cover
    cfg_mgr = ConfigManager()
    config = cfg_mgr.load()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    service = NanoleafSyncService(config=config)
    service.install_signal_handlers()
    service.start()
    while service.is_running():
        time.sleep(0.25)


if __name__ == "__main__":  # pragma: no cover
    main()
