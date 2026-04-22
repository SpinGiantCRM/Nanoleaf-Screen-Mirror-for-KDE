"""Long-running service that wires capture, processing, and USB output.

This module owns startup/shutdown orchestration, capture dimension discovery,
backend construction, and status reporting consumed by tray and CLI tools.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional, Tuple

from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.capture.backend_normalization import normalize_capture_backend
from nanoleaf_sync.capture.dimensions import (
    DEFAULT_CAPTURE_HEIGHT as _DEFAULT_CAPTURE_HEIGHT,
    DEFAULT_CAPTURE_WIDTH as _DEFAULT_CAPTURE_WIDTH,
    detect_primary_screen_dims,
    resolve_capture_dims,
)
from nanoleaf_sync.capture.factory import create_capture_backend
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.device.interfaces import DeviceDriver, NanoleafUSBIds
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver
from nanoleaf_sync.runtime.startup import (
    RuntimeLifecycle,
    run_runtime_engine,
)
from nanoleaf_sync.runtime.state import RuntimeState


logger = logging.getLogger(__name__)
_AUTO_PROBE_WINNERS = {"kwin-dbus", "xdg-portal", "kmsgrab"}
_PROCESS_BOOT_PROBE_DONE = False
_PROCESS_BOOT_PROBE_LOCK = threading.Lock()
_AUTO_PROBE_ENV_VARS = (
    "NANOLEAF_DISABLE_CAPTURE_PROBE",
    "NANOLEAF_ENABLE_CAPTURE_PROBE",
    "NANOLEAF_DRM_CARD",
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
    "DESKTOP_SESSION",
    "KDE_FULL_SESSION",
    "KDE_SESSION_VERSION",
    "WAYLAND_DISPLAY",
    "DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "QT_SCALE_FACTOR",
    "GDK_SCALE",
)
__all__ = (
    "NanoleafSyncService",
    "_DEFAULT_CAPTURE_WIDTH",
    "_DEFAULT_CAPTURE_HEIGHT",
    "_detect_primary_screen_dims",
    "_resolve_capture_dims",
)

def _detect_primary_screen_dims(*, qt_widgets_module=None) -> Optional[Tuple[int, int]]:
    return detect_primary_screen_dims(qt_widgets_module=qt_widgets_module)


def _resolve_capture_dims(config: AppConfig) -> Tuple[int, int]:
    return resolve_capture_dims(config)


def _is_valid_auto_probe_winner(value: str | None) -> bool:
    return value in _AUTO_PROBE_WINNERS


def _build_auto_probe_signature(capture_width: int, capture_height: int) -> str:
    try:
        from nanoleaf_sync.capture import factory as capture_factory

        has_drm_device = bool(capture_factory._has_drm_device())  # noqa: SLF001
        kmsgrab_bindings = bool(capture_factory._kmsgrab_bindings_available())  # noqa: SLF001
    except Exception:
        has_drm_device = False
        kmsgrab_bindings = False

    dims = _detect_primary_screen_dims()
    scale = (os.environ.get("QT_SCALE_FACTOR") or os.environ.get("GDK_SCALE") or "").strip()
    payload = {
        "backends": {
            "kwin_dbus": True,
            "xdg_portal": bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")),
            "kmsgrab": has_drm_device and kmsgrab_bindings,
            "drm_device_present": has_drm_device,
            "kmsgrab_bindings": kmsgrab_bindings,
        },
        "session": {
            "type": os.environ.get("XDG_SESSION_TYPE", ""),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
            "desktop_session": os.environ.get("DESKTOP_SESSION", ""),
            "kde_full_session": os.environ.get("KDE_FULL_SESSION", ""),
            "kde_session_version": os.environ.get("KDE_SESSION_VERSION", ""),
            "wayland_display": os.environ.get("WAYLAND_DISPLAY", ""),
            "display": os.environ.get("DISPLAY", ""),
        },
        "display": {
            "primary_width": int(dims[0]) if dims else None,
            "primary_height": int(dims[1]) if dims else None,
            "capture_width": int(capture_width),
            "capture_height": int(capture_height),
            "scale_hint": scale,
        },
        "env": {name: os.environ.get(name, "") for name in _AUTO_PROBE_ENV_VARS},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class NanoleafSyncService:
    """Service orchestration around runtime startup/shutdown and per-frame engine loop."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        *,
        capture_backend_override: CaptureBackend | None = None,
        driver_override=None,
    ) -> None:
        self.config = config or AppConfig()

        self._driver: DeviceDriver | None = None
        self._capture: CaptureBackend | None = None
        self._capture_backend_override = capture_backend_override
        self._driver_override = driver_override

        self._runtime = RuntimeState()
        self._lifecycle = RuntimeLifecycle(state=self._runtime, runner=self._run_runtime)

        self._capture_width, self._capture_height = _resolve_capture_dims(self.config)
        self._cached_probe_winner: str | None = None
        self._selection_reason: str = "fallback"
        self._effective_capture_backend: str | None = None
        self._device_discovered = False
        self._device_model: str | None = None
        self._device_zone_count: int | None = None
        self._status_lock = threading.Lock()

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
        with self._status_lock:
            device_discovered = self._device_discovered
            device_model = self._device_model
            device_zone_count = self._device_zone_count
        capture_backend_name = (
            getattr(self._capture, "name", None) if self._capture is not None else None
        )
        capture_path = (
            getattr(self._capture, "last_capture_path", None)
            if self._capture is not None
            else None
        )

        status = self._runtime.status_snapshot(
            running=self.is_running(),
            capture_backend_name=capture_backend_name,
            capture_path=capture_path,
            capture_width=self._capture_width,
            capture_height=self._capture_height,
            max_consecutive_errors=self.config.max_consecutive_errors,
            reinit_backoff_ms=self.config.reinit_backoff_ms,
        )
        status["requested_capture_backend"] = self.config.prefer_backend
        status["selected_capture_backend"] = self._effective_capture_backend or self.config.auto_selected_backend or ""
        status["effective_capture_backend"] = self._effective_capture_backend or capture_backend_name
        status["selection_reason"] = self._selection_reason
        status["backend_unresolved_reason"] = (
            ""
            if bool(status["effective_capture_backend"])
            else (
                "Runtime has not started yet."
                if not self.is_running()
                else f"No concrete backend implementation resolved for policy '{self.config.prefer_backend}'."
            )
        )
        status["from_auto_probe"] = self._selection_reason in {"cached-probe", "fresh-probe"}
        status["auto_probe_policy"] = self.config.auto_probe_policy
        status["auto_probe_timestamp"] = self.config.auto_probe_timestamp or ""
        status["cached_probe_backend"] = self.config.auto_selected_backend or ""
        status["backend_selection_details"] = (
            f"policy={self.config.auto_probe_policy}, reason={self._selection_reason}, "
            f"cached={self.config.auto_selected_backend or 'none'}"
        )
        status["device_mode"] = "real-usb"
        status["device_discovered"] = device_discovered
        status["device_model"] = device_model
        status["device_zone_count"] = device_zone_count
        return status

    def _make_device_driver(self) -> DeviceDriver:
        ids = NanoleafUSBIds(vid=self.config.device_vid, pid=self.config.device_pid)
        if int(ids.vid) == 0 or int(ids.pid) == 0:
            raise ValueError(
                "Real device mode requires non-zero device_vid/device_pid. "
                "Configure Nanoleaf USB IDs (for example 0x37fa:0x8201 or 0x37fa:0x8202)."
            )
        return NanoleafUSBDriver(
            ids=ids,
            output_channel_order=self.config.output_channel_order,
        )

    def _clear_backends(self) -> None:
        self._capture = None
        self._driver = None
        with self._status_lock:
            self._device_discovered = False
            self._device_model = None
            self._device_zone_count = None

    def _close_backends(self) -> None:
        capture = self._capture
        try:
            if capture is not None:
                close_fn = getattr(capture, "close", None)
                if close_fn is not None:
                    close_fn()
        except Exception:
            pass
        finally:
            self._capture = None

        driver = self._driver
        try:
            if driver is not None:
                driver.close()
        except Exception:
            pass
        finally:
            self._driver = None

    def _install_drivers(self) -> None:
        global _PROCESS_BOOT_PROBE_DONE
        width = self._capture_width
        height = self._capture_height

        if self._capture_backend_override is not None:
            self._capture = self._capture_backend_override
            self._selection_reason = "explicit"
        else:
            normalized_preference = normalize_capture_backend(
                self.config.prefer_backend, default="auto"
            )
            signature = _build_auto_probe_signature(width, height)
            cached_winner = self._cached_probe_winner or self.config.auto_selected_backend
            should_probe = False
            policy = str(getattr(self.config, "auto_probe_policy", "on-change")).strip().lower()
            if normalized_preference == "auto":
                if policy == "first-run":
                    should_probe = not _is_valid_auto_probe_winner(cached_winner)
                elif policy == "each-boot":
                    with _PROCESS_BOOT_PROBE_LOCK:
                        should_probe = not _PROCESS_BOOT_PROBE_DONE
                        if should_probe:
                            _PROCESS_BOOT_PROBE_DONE = True
                else:
                    signature_changed = signature != str(
                        getattr(self.config, "auto_probe_signature", "") or ""
                    )
                    should_probe = signature_changed or not _is_valid_auto_probe_winner(cached_winner)

            selected_cache = None if should_probe else cached_winner
            self._capture = create_capture_backend(
                width=width,
                height=height,
                use_mock_capture=self.config.use_mock_capture,
                prefer_backend=self.config.prefer_backend,
                hdr_max_nits=self.config.hdr_max_nits,
                hdr_transfer=self.config.hdr_transfer,
                hdr_primaries=self.config.hdr_primaries,
                auto_probe_enabled=self.config.auto_probe_enabled,
                cached_probe_winner=selected_cache,
            )
            if normalized_preference != "auto":
                self._selection_reason = "explicit"
            elif _is_valid_auto_probe_winner(selected_cache):
                self._selection_reason = "cached-probe"
            elif should_probe:
                self._selection_reason = "fresh-probe"
            else:
                self._selection_reason = "fallback"
            if normalized_preference == "auto":
                winner = getattr(self._capture, "name", None)
                if _is_valid_auto_probe_winner(winner):
                    self._cached_probe_winner = winner
                    previous_winner = str(getattr(self.config, "auto_selected_backend", "") or "")
                    previous_signature = str(getattr(self.config, "auto_probe_signature", "") or "")
                    needs_write = (
                        should_probe
                        or previous_winner != winner
                        or previous_signature != signature
                    )
                    updated_config = replace(
                        self.config,
                        auto_selected_backend=winner,
                        auto_probe_signature=signature,
                    )
                    if needs_write:
                        updated_config = replace(
                            updated_config,
                            auto_probe_timestamp=datetime.now(timezone.utc).isoformat(),
                        )
                        if self._capture_backend_override is None and self._driver_override is None:
                            try:
                                ConfigManager().save(updated_config)
                            except Exception as exc:
                                logger.warning(
                                    "Failed to persist auto-probe cache metadata: %s",
                                    exc,
                                )
                    self.config = updated_config
                else:
                    self._selection_reason = "fallback"
        self._effective_capture_backend = getattr(self._capture, "name", None)

        if self._driver_override is not None:
            self._driver = self._driver_override
        else:
            self._driver = self._make_device_driver()

        self._driver.initialize()
        with self._status_lock:
            self._device_discovered = True
            self._device_model = getattr(self._driver, "model_number", None)
            self._device_zone_count = getattr(self._driver, "zone_count", None)

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
