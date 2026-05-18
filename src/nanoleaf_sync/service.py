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
from nanoleaf_sync.capture.factory import last_auto_probe_report
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.device.interfaces import DeviceDriver, NanoleafUSBIds
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver
from nanoleaf_sync.runtime.startup import (
    RuntimeLifecycle,
    run_runtime_engine,
)
from nanoleaf_sync.runtime.state import RuntimeState
from nanoleaf_sync.runtime.compositor import effective_sdr_boost
from nanoleaf_sync.runtime.diagnostics_exports import default_kde_display_metadata


logger = logging.getLogger(__name__)
_AUTO_PROBE_WINNERS = {"kwin-dbus", "xdg-portal", "kmsgrab"}
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

        has_drm_device = bool(capture_factory.has_drm_device())
        kmsgrab_bindings = bool(capture_factory.kmsgrab_bindings_available())
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

    _PROCESS_BOOT_PROBE_LOCK = threading.Lock()
    _PROCESS_BOOT_PROBE_STATE = "pending"

    @classmethod
    def _reset_process_boot_probe_state(cls) -> None:
        with cls._PROCESS_BOOT_PROBE_LOCK:
            cls._PROCESS_BOOT_PROBE_STATE = "pending"

    @classmethod
    def _begin_each_boot_probe(cls) -> bool:
        with cls._PROCESS_BOOT_PROBE_LOCK:
            if cls._PROCESS_BOOT_PROBE_STATE == "pending":
                cls._PROCESS_BOOT_PROBE_STATE = "in-progress"
                return True
            return False

    @classmethod
    def _finish_each_boot_probe(cls, *, success: bool) -> None:
        with cls._PROCESS_BOOT_PROBE_LOCK:
            cls._PROCESS_BOOT_PROBE_STATE = "complete" if success else "pending"

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
        self._lifecycle = RuntimeLifecycle(
            state=self._runtime,
            runner=self._run_runtime,
        )

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

    def stop(self, timeout: Optional[float] = 1.5) -> bool:
        join_timeout = max(0.0, float(timeout)) if timeout is not None else None
        return self._lifecycle.stop(join_timeout=join_timeout)

    def join(self, timeout: Optional[float] = None) -> None:
        self._lifecycle.join(timeout=timeout)

    def is_running(self) -> bool:
        return self._lifecycle.is_running()

    def get_status(self) -> dict:
        with self._status_lock:
            device_discovered = self._device_discovered
            device_model = self._device_model
            detected_device_zone_count = self._device_zone_count
        configured_device_zone_count = int(getattr(self.config, "device_zone_count", 0) or 0)
        calibration_device_zone_count = int(
            getattr(getattr(self.config, "calibration", None), "device_zone_count", 0) or 0
        )
        effective_runtime_zone_count = configured_device_zone_count if configured_device_zone_count > 0 else None
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
        lifecycle_state = self._lifecycle.startup_state()
        startup_state = lifecycle_state
        if lifecycle_state in {"starting", "running"}:
            backend_hint = str(status.get("effective_capture_backend") or status.get("selected_capture_backend") or "")
            if backend_hint == "xdg-portal" and int(status.get("frames_sent") or 0) <= 0:
                startup_state = "waiting_for_screen_selection"
        status["startup_state"] = startup_state
        status["lifecycle_state"] = str(status.get("lifecycle_state") or lifecycle_state)
        status["start_failure_reason"] = str(status.get("start_failure_reason") or "")
        status["backend_retest_blocked"] = lifecycle_state in {"starting", "running", "stopping"}
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
        status["backend_probe_attempts"] = last_auto_probe_report()
        measurement = status.get("latency_measurement")
        if isinstance(measurement, dict):
            labels = measurement.setdefault("labels", {})
            selected_backend = str(status.get("selected_capture_backend") or status.get("effective_capture_backend") or "")
            for row in status["backend_probe_attempts"]:
                if str(row.get("backend", "")) != selected_backend:
                    continue
                median_ms = row.get("median_ms")
                if median_ms is not None:
                    labels["benchmark_capture_ms"] = f"{float(median_ms):.2f}"
                break
        status["device_mode"] = "real-usb"
        status["device_discovered"] = device_discovered
        status["device_model"] = device_model
        # Backward-compatible alias retained for existing UI/tests.
        status["device_zone_count"] = detected_device_zone_count
        status["detected_device_zone_count"] = detected_device_zone_count
        status["configured_device_zone_count"] = configured_device_zone_count
        status["effective_runtime_zone_count"] = effective_runtime_zone_count
        status["calibration_device_zone_count"] = calibration_device_zone_count
        status["source_zone_count"] = len(self._runtime.latest_zones_px)
        status["source_zone_side_counts"] = tuple(int(i) for i in self._runtime.latest_zone_side_counts)
        status["zone_sampling_stride"] = int(getattr(self.config, "zone_sampling_stride", 1))
        status["zone_sampling_engine"] = str(getattr(self.config, "zone_sampling_engine", "auto"))
        status["edge_locality"] = str(getattr(self.config, "edge_locality", "balanced"))
        status["light_spread"] = str(getattr(self.config, "light_spread", "balanced"))
        status["display_preset"] = str(getattr(self.config, "display_preset", "hdr"))
        status["edge_sampling_thickness"] = self._runtime.latest_edge_sampling_thickness
        status["zone_diagnostics_preview"] = self._runtime.latest_zone_diagnostics[:8]
        status["side_variance_diagnostics"] = self._runtime.latest_side_variance_diagnostics
        status["_latest_zone_diagnostics"] = self._runtime.latest_zone_diagnostics
        status["_latest_frame_rgb"] = self._runtime.latest_frame_rgb
        status["_latest_zones_px"] = self._runtime.latest_zones_px
        status["_latest_zone_side_counts"] = self._runtime.latest_zone_side_counts
        status.update(default_kde_display_metadata())
        detected_display = detect_primary_screen_dims()
        if detected_display is not None:
            status["kde_display_width"] = int(detected_display[0])
            status["kde_display_height"] = int(detected_display[1])
        capture_hdr = getattr(self._capture, "last_hdr_diagnostics", {}) if self._capture is not None else {}
        tone_mapping_applied = bool(capture_hdr.get("tone_mapping_applied", False))
        metadata_source = str(capture_hdr.get("metadata_source", "unknown"))
        status["hdr_colour_path"] = {
            "display_preset": str(getattr(self.config, "display_preset", "hdr")),
            "compositor_hdr_mode": bool(getattr(self.config, "compositor_hdr_mode", False)),
            "sdr_boost_nits": float(getattr(self.config, "sdr_boost_nits", 80.0)),
            "effective_sdr_boost_scalar": float(
                effective_sdr_boost(sdr_boost_nits=float(getattr(self.config, "sdr_boost_nits", 80.0)))
            ),
            "hdr_max_nits": float(capture_hdr.get("hdr_max_nits", getattr(self.config, "hdr_max_nits", 1000.0))),
            "hdr_transfer": str(capture_hdr.get("input_transfer", getattr(self.config, "hdr_transfer", "srgb"))),
            "hdr_primaries": str(capture_hdr.get("input_primaries", getattr(self.config, "hdr_primaries", "bt709"))),
            "capture_metadata_source": metadata_source,
            "tone_mapping_applied": tone_mapping_applied,
            "sdr_compensation_applied": bool(getattr(self.config, "compositor_hdr_mode", False))
            and abs(effective_sdr_boost(sdr_boost_nits=float(getattr(self.config, "sdr_boost_nits", 80.0))) - 1.0) > 1e-6,
            "assumption": str(capture_hdr.get("assumption", "unknown")),
            "warnings": [
                "HDR preset active but capture metadata unavailable; using user preset assumptions."
            ]
            if str(getattr(self.config, "display_preset", "hdr")).strip().lower() == "hdr" and metadata_source == "unknown"
            else [],
        }
        return status

    def capture_one_diagnostic_frame(self) -> dict[str, object]:
        from nanoleaf_sync.runtime.engine import process_frame
        from nanoleaf_sync.runtime.processing import zones_from_config
        from nanoleaf_sync.runtime.zone_derivation import derive_source_zone_artifacts

        if self.is_running():
            return {"ok": False, "message": "Mirroring is already running; stop mirroring before one-shot diagnostic capture."}
        capture = self._capture
        created_capture = False
        try:
            if capture is None:
                if self._capture_backend_override is not None:
                    capture = self._capture_backend_override
                else:
                    capture = create_capture_backend(
                        width=int(self._capture_width),
                        height=int(self._capture_height),
                        use_mock_capture=bool(getattr(self.config, "use_mock_capture", False)),
                        prefer_backend=normalize_capture_backend(self.config.prefer_backend, default="auto"),
                        hdr_transfer=self.config.hdr_transfer,
                        hdr_primaries=self.config.hdr_primaries,
                        hdr_max_nits=self.config.hdr_max_nits,
                        auto_probe_enabled=getattr(self.config, "auto_probe_enabled", None),
                        cached_probe_winner=self._cached_probe_winner or self.config.auto_selected_backend,
                    )
                    created_capture = True
                init = getattr(capture, "initialize", None)
                if callable(init) and not init():
                    return {"ok": False, "message": "Capture backend failed to initialize for one-shot diagnostics."}
            frame = capture.capture()
            if frame is None:
                return {"ok": False, "message": "Capture backend returned no frame for one-shot diagnostics."}
            img_h, img_w, _ = frame.shape
            artifacts = derive_source_zone_artifacts(
                config=self.config,
                detected_device_zone_count=self._device_zone_count,
                frame_width=img_w,
                frame_height=img_h,
            )
            zones_px = zones_from_config(artifacts.zones, img_w, img_h)
            device_zone_indices = list(range(len(zones_px)))
            processed = process_frame(
                frame=frame,
                prev_smoothed_colors=[],
                zones_px=zones_px,
                device_zone_indices=device_zone_indices,
                brightness=self.config.brightness,
                smoothing=self.config.smoothing,
                smoothing_speed=self.config.smoothing_speed,
                zone_sampling_stride=self.config.zone_sampling_stride,
                zone_sampling_engine=getattr(self.config, "zone_sampling_engine", "auto"),
                led_gamma=self.config.led_gamma,
                motion_preset=getattr(self.config, "motion_preset", "responsive"),
                color_style=getattr(self.config, "color_style", "ambient"),
                edge_locality=getattr(self.config, "edge_locality", "balanced"),
                compositor_hdr_mode=getattr(self.config, "compositor_hdr_mode", False),
                sdr_boost_nits=getattr(self.config, "sdr_boost_nits", 80.0),
                hdr_max_nits=getattr(self.config, "hdr_max_nits", 1000.0),
                return_diagnostics=True,
            )
            _, sampled_zone_colors, pre_led_colors, final_zone_colors, _timings = processed
            self._runtime.latest_frame_rgb = frame
            self._runtime.last_frame_width = int(img_w)
            self._runtime.last_frame_height = int(img_h)
            self._runtime.latest_zones_px = list(zones_px)
            self._runtime.latest_zone_side_counts = tuple(int(i) for i in (artifacts.side_counts or (0, 0, 0, 0)))
            self._runtime.latest_edge_sampling_thickness = artifacts.edge_sampling_thickness
            rows: list[dict[str, object]] = []
            for zone_index, rect in enumerate(zones_px):
                sampled_rgb = tuple(int(c) for c in sampled_zone_colors[zone_index].tolist())
                pre_led_rgb = tuple(int(c) for c in pre_led_colors[zone_index].tolist())
                final_rgb = tuple(int(c) for c in final_zone_colors[zone_index].tolist())
                top, right, bottom, left = self._runtime.latest_zone_side_counts
                if zone_index < top:
                    side = "top"
                elif zone_index < top + right:
                    side = "right"
                elif zone_index < top + right + bottom:
                    side = "bottom"
                elif zone_index < top + right + bottom + left:
                    side = "left"
                else:
                    side = "unknown"
                rows.append(
                    {
                        "zone_index": zone_index,
                        "side": side,
                        "pixel_rect": rect,
                        "sampled_rgb": sampled_rgb,
                        "output_rgb_before_led_calibration": pre_led_rgb,
                        "final_output_rgb": final_rgb,
                        "mapped_physical_led_index": zone_index,
                    }
                )
            self._runtime.latest_zone_diagnostics = rows
            return {"ok": True, "message": f"Captured one diagnostic frame ({img_w}x{img_h}) with {len(rows)} zones."}
        except Exception as exc:
            return {"ok": False, "message": f"One-shot diagnostic capture failed: {exc}"}
        finally:
            if created_capture:
                try:
                    close_fn = getattr(capture, "close", None)
                    if callable(close_fn):
                        close_fn()
                except Exception:
                    pass

    def _make_device_driver(self, *, enable_live_frame_write_optimization: bool = True) -> DeviceDriver:
        ids = NanoleafUSBIds(vid=self.config.device_vid, pid=self.config.device_pid)
        if int(ids.vid) == 0 or int(ids.pid) == 0:
            raise ValueError(
                "Real device mode requires non-zero device_vid/device_pid. "
                "Configure Nanoleaf USB IDs (for example 0x37fa:0x8201 or 0x37fa:0x8202)."
            )
        return NanoleafUSBDriver(
            ids=ids,
            output_channel_order=self.config.output_channel_order,
            configured_zone_count=int(getattr(self.config, "device_zone_count", 0) or 0),
            enable_live_frame_write_optimization=enable_live_frame_write_optimization,
        )

    def _clear_backends(self) -> None:
        self._capture = None
        self._driver = None
        with self._status_lock:
            self._device_discovered = False
            self._device_model = None
            self._device_zone_count = None

    def _send_stop_black_frame(self) -> None:
        if not self._runtime.driver_ready:
            return
        driver = self._driver
        if driver is None:
            return
        try:
            zone_count = int(getattr(driver, "zone_count", 0) or 0)
            if zone_count <= 0:
                zone_count = int(getattr(driver, "reported_zone_count", 0) or 0)
            if zone_count <= 0:
                zone_count = int(getattr(self.config, "device_zone_count", 0) or 0)
            if zone_count <= 0:
                return
            driver.send_frame([(0, 0, 0)] * zone_count)
        except Exception:
            logger.debug("Unable to send final stop frame.", exc_info=True)

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
        width = self._capture_width
        height = self._capture_height
        claimed_each_boot_probe = False

        try:
            self._runtime.capture_backend_ready = False
            self._runtime.driver_ready = False
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
                        claimed_each_boot_probe = self._begin_each_boot_probe()
                        should_probe = claimed_each_boot_probe
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
            self._runtime.capture_backend_ready = self._capture is not None

            if self._driver_override is not None:
                self._driver = self._driver_override
            else:
                self._driver = self._make_device_driver()

            self._driver.initialize()
            self._runtime.driver_ready = True
            with self._status_lock:
                self._device_discovered = True
                self._device_model = getattr(self._driver, "model_number", None)
                self._device_zone_count = getattr(self._driver, "zone_count", None)
            if claimed_each_boot_probe:
                self._finish_each_boot_probe(success=True)
        except Exception as exc:
            self._runtime.start_failure_reason = str(exc)
            self._runtime.capture_backend_ready = self._capture is not None
            self._runtime.driver_ready = False
            if claimed_each_boot_probe:
                self._finish_each_boot_probe(success=False)
            raise

    def _run_runtime(self) -> None:
        run_runtime_engine(
            config=self.config,
            state=self._runtime,
            get_capture=lambda: self._capture,
            get_driver=lambda: self._driver,
            install_drivers=self._install_drivers,
            close_backends=self._close_backends,
            clear_backends=self._clear_backends,
            send_final_frame=self._send_stop_black_frame,
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
