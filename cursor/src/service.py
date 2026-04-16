from __future__ import annotations

import logging
import signal
import time
from typing import Optional, Tuple

from capture.factory import create_capture_backend
from config import AppConfig, ConfigManager
from device.interfaces import DeviceDriver
from device.nanoleaf_usb import MockNanoleafUSBDriver, NanoleafUSBDriver, NanoleafUSBIds
from runtime.startup import (
    RuntimeLifecycle,
    run_runtime_engine,
)
from runtime.state import RuntimeState


logger = logging.getLogger(__name__)

# Default capture dimensions used when no monitor-size detection is available.
_DEFAULT_CAPTURE_WIDTH = 1920
_DEFAULT_CAPTURE_HEIGHT = 1080


def _resolve_capture_dims(config: AppConfig) -> Tuple[int, int]:
    """
    Return (width, height) for capture initialization.

    Currently falls back to module-level defaults because monitor autodetection
    is not yet implemented.
    """
    return _DEFAULT_CAPTURE_WIDTH, _DEFAULT_CAPTURE_HEIGHT


class NanoleafSyncService:
    """Service orchestration around runtime startup/shutdown and per-frame engine loop."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        *,
        capture_backend_override=None,
        driver_override=None,
    ) -> None:
        self.config = config or AppConfig()

        self._driver = None
        self._capture = None
        self._capture_backend_override = capture_backend_override
        self._driver_override = driver_override

        self._runtime = RuntimeState()
        self._lifecycle = RuntimeLifecycle(state=self._runtime, runner=self._run_runtime)

        self._capture_width, self._capture_height = _resolve_capture_dims(self.config)

    @property
    def last_error(self) -> Optional[str]:
        return self._runtime.last_error

    @property
    def frames_sent(self) -> int:
        return self._runtime.frames_sent

    def start(self) -> bool:
        return self._lifecycle.start(startup_timeout_s=1.0)

    def stop(self) -> None:
        self._lifecycle.stop()

    def join(self, timeout: Optional[float] = None) -> None:
        self._lifecycle.join(timeout=timeout)

    def is_running(self) -> bool:
        return self._lifecycle.is_running()

    def get_status(self) -> dict:
        capture_backend_name = (
            getattr(self._capture, "name", None) if self._capture is not None else None
        )
        capture_path = (
            getattr(self._capture, "last_capture_path", None)
            if self._capture is not None
            else None
        )

        return self._runtime.status_snapshot(
            running=self.is_running(),
            capture_backend_name=capture_backend_name,
            capture_path=capture_path,
            capture_width=self._capture_width,
            capture_height=self._capture_height,
            max_consecutive_errors=self.config.max_consecutive_errors,
            reinit_backoff_ms=self.config.reinit_backoff_ms,
        )

    def _make_device_driver(self) -> DeviceDriver:
        ids = NanoleafUSBIds(vid=self.config.device_vid, pid=self.config.device_pid)
        if self.config.use_mock_device:
            return MockNanoleafUSBDriver(ids=ids)
        return NanoleafUSBDriver(ids=ids)

    def _clear_backends(self) -> None:
        self._capture = None
        self._driver = None

    def _close_backends(self) -> None:
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

    def _run_runtime(self) -> None:
        run_runtime_engine(
            config=self.config,
            state=self._runtime,
            get_capture=lambda: self._capture,
            get_driver=lambda: self._driver,
            install_drivers=self._install_drivers,
            close_backends=self._close_backends,
            clear_backends=self._clear_backends,
        )

    def install_signal_handlers(self) -> None:
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
