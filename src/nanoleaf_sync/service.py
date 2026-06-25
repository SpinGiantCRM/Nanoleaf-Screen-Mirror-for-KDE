"""Long-running service that wires capture, processing, and USB output.

This module owns startup/shutdown orchestration, capture dimension discovery,
backend construction, and status reporting consumed by tray and CLI tools.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from nanoleaf_sync.capture.backend_normalization import normalize_capture_backend
from nanoleaf_sync.capture.dimensions import (
    DEFAULT_CAPTURE_HEIGHT as _DEFAULT_CAPTURE_HEIGHT,
)
from nanoleaf_sync.capture.dimensions import (
    DEFAULT_CAPTURE_WIDTH as _DEFAULT_CAPTURE_WIDTH,
)
from nanoleaf_sync.capture.dimensions import (
    detect_primary_screen_dims,
    resolve_capture_dims,
)
from nanoleaf_sync.capture.factory import (
    cached_probe_winner_is_viable,
    create_capture_backend,
    last_auto_probe_report,
    reset_cached_probe_winner,
)
from nanoleaf_sync.capture.interfaces import CaptureBackend
from nanoleaf_sync.capture.kwin_dbus import is_kwin_invalid_screen_error
from nanoleaf_sync.compat.version_snapshot import (
    check_for_upgrade,
    update_snapshot,
    upgrade_notification_message,
)
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.normalize import preferred_send_policy_from_config
from nanoleaf_sync.config.presets import effective_drm_zone_patch_capture, is_four_d_sync
from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.device.interfaces import DeviceDriver, NanoleafUSBIds
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver
from nanoleaf_sync.runtime.calibration_resolver import (
    evaluate_device_zone_authority,
    resolve_calibration_mapping_from_config,
)
from nanoleaf_sync.runtime.compositor import effective_sdr_boost
from nanoleaf_sync.runtime.diagnostics_exports import default_kde_display_metadata
from nanoleaf_sync.runtime.startup import (
    RuntimeLifecycle,
    run_runtime_engine,
)
from nanoleaf_sync.runtime.state import RuntimeState

logger = logging.getLogger(__name__)
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


def _detect_primary_screen_dims(*, qt_widgets_module=None) -> tuple[int, int] | None:
    return detect_primary_screen_dims(qt_widgets_module=qt_widgets_module)


def _resolve_capture_dims(config: AppConfig) -> tuple[int, int]:
    return resolve_capture_dims(config)


def _is_valid_auto_probe_winner(value: str | None) -> bool:
    return cached_probe_winner_is_viable(value)


def _build_auto_probe_signature(
    capture_width: int,
    capture_height: int,
    *,
    capture_monitor: str = "",
) -> str:
    try:
        from nanoleaf_sync.capture import factory as capture_factory

        has_drm_device = bool(capture_factory.has_drm_device())
        kmsgrab_bindings = bool(capture_factory.kmsgrab_bindings_available())
    except Exception:
        logger.debug("Unable to probe DRM/kmsgrab capability", exc_info=True)
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
            "capture_monitor": str(capture_monitor or "").strip(),
            "scale_hint": scale,
        },
        "env": {name: os.environ.get(name, "") for name in _AUTO_PROBE_ENV_VARS},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class NanoleafSyncService:
    """Service orchestration around runtime startup/shutdown and per-frame engine loop."""

    _PROCESS_BOOT_PROBE_LOCK = threading.RLock()
    _PROCESS_BOOT_PROBE_STATE = "pending"

    @staticmethod
    def reset_boot_probe_state() -> None:
        NanoleafSyncService._reset_process_boot_probe_state()

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
        config: AppConfig | None = None,
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
        self._kmsgrab_fallback_streak = 0
        self._probe_heal_last_frames = 0
        self._kwin_invalid_screen_invalidation_done = False
        self._device_discovered = False
        self._device_model: str | None = None
        self._device_zone_count: int | None = None
        self._status_lock = threading.Lock()
        self._can_mirroring_write: Callable[[], bool] | None = None
        self._mirroring_generation = 0
        self._kde_upgrade_report = self._check_kde_upgrade_on_startup()

    def set_output_session_guard(self, fn: Callable[[], bool] | None) -> None:
        self._can_mirroring_write = fn

    def bind_mirroring_generation(self, generation: int) -> None:
        self._mirroring_generation = int(generation)

    @property
    def mirroring_generation(self) -> int:
        return self._mirroring_generation

    @property
    def kde_upgrade_notice(self) -> str | None:
        return upgrade_notification_message(self._kde_upgrade_report)

    @property
    def kde_upgrade_report(self) -> dict:
        return dict(self._kde_upgrade_report)

    @staticmethod
    def _check_kde_upgrade_on_startup() -> dict:
        report = check_for_upgrade()
        update_snapshot()
        return report

    @property
    def last_error(self) -> str | None:
        return self._runtime.last_error

    @property
    def frames_sent(self) -> int:
        return self._runtime.frames_sent

    def start(self) -> bool:
        startup_timeout_s = max(
            0.5,
            float(getattr(self.config, "startup_frame_timeout_s", 5.0)),
        )
        return self._lifecycle.start(startup_timeout_s=startup_timeout_s)

    def stop(self, timeout: float | None = 1.5) -> bool:
        join_timeout = max(0.0, float(timeout)) if timeout is not None else None
        return self._lifecycle.stop(join_timeout=join_timeout)

    def join(self, timeout: float | None = None) -> None:
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
        effective_runtime_zone_count = (
            configured_device_zone_count if configured_device_zone_count > 0 else None
        )
        capture_backend_name = (
            getattr(self._capture, "name", None) if self._capture is not None else None
        )
        capture_path = (
            getattr(self._capture, "last_capture_path", None) if self._capture is not None else None
        )
        active_capture = self._capture
        if active_capture is None and self._capture_backend_override is not None:
            active_capture = self._capture_backend_override
            capture_backend_name = getattr(active_capture, "name", None)
            capture_path = getattr(active_capture, "last_capture_path", None)

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
        status["selected_capture_backend"] = (
            self._effective_capture_backend or self.config.auto_selected_backend or ""
        )
        status["effective_capture_backend"] = (
            self._effective_capture_backend or capture_backend_name
        )
        lifecycle_state = self._lifecycle.startup_state()
        startup_state = lifecycle_state
        if lifecycle_state in {"starting", "running"}:
            backend_hint = str(
                status.get("effective_capture_backend")
                or status.get("selected_capture_backend")
                or ""
            )
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
                else (
                    f"No concrete backend implementation resolved for policy "
                    f"'{self.config.prefer_backend}'."
                )
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
            selected_backend = str(
                status.get("selected_capture_backend")
                or status.get("effective_capture_backend")
                or ""
            )
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
        zone_authority = evaluate_device_zone_authority(
            config=self.config,
            detected_device_zone_count=detected_device_zone_count,
        )
        status["device_zone_count_source"] = (
            self._runtime.device_zone_count_source or zone_authority.device_zone_count_source
        )
        status["effective_device_zone_count"] = (
            self._runtime.effective_device_zone_count or zone_authority.effective_device_zone_count
        )
        status["device_zone_count_mismatch"] = bool(
            self._runtime.device_zone_count_mismatch or zone_authority.device_zone_count_mismatch
        )
        status["mapping_repair_required"] = bool(
            self._runtime.mapping_repair_required or zone_authority.mapping_repair_required
        )
        status["device_zone_override_active"] = bool(
            self._runtime.device_zone_override_active or zone_authority.override_active
        )
        status["source_zone_count"] = len(self._runtime.latest_zones_px)
        status["source_zone_side_counts"] = tuple(
            int(i) for i in self._runtime.latest_zone_side_counts
        )
        status["zone_sampling_stride"] = int(getattr(self.config, "zone_sampling_stride", 1))
        status["zone_sampling_engine"] = str(getattr(self.config, "zone_sampling_engine", "auto"))
        status["edge_locality"] = str(getattr(self.config, "edge_locality", "balanced"))
        status["light_spread"] = str(getattr(self.config, "light_spread", "balanced"))
        status["display_preset"] = str(getattr(self.config, "display_preset", "hdr"))
        status["edge_sampling_thickness"] = self._runtime.latest_edge_sampling_thickness
        status["zone_diagnostics_preview"] = self._runtime.latest_zone_diagnostics[:8]
        status["zone_diagnostics"] = list(self._runtime.latest_zone_diagnostics)
        status["side_variance_diagnostics"] = self._runtime.latest_side_variance_diagnostics
        status["_latest_zone_diagnostics"] = self._runtime.latest_zone_diagnostics
        status["_latest_frame_rgb"] = self._runtime.latest_frame_rgb
        status["_latest_zones_px"] = self._runtime.latest_zones_px
        status["_latest_zone_side_counts"] = self._runtime.latest_zone_side_counts
        status.update(default_kde_display_metadata())
        status["kde_upgrade_report"] = self._kde_upgrade_report
        status["kde_upgrade_notice"] = self.kde_upgrade_notice or ""
        self._maybe_heal_stale_probe_cache()
        self._maybe_invalidate_kwin_probe_cache_for_invalid_screen()
        detected_display = detect_primary_screen_dims()
        if detected_display is not None:
            status["kde_display_width"] = int(detected_display[0])
            status["kde_display_height"] = int(detected_display[1])
        capture_hdr = (
            getattr(active_capture, "last_hdr_diagnostics", {})
            if active_capture is not None
            else {}
        )
        tone_mapping_applied = bool(capture_hdr.get("tone_mapping_applied", False))
        effective_backend = str(
            status.get("effective_capture_backend") or capture_backend_name or ""
        )
        is_kwin_backend = effective_backend == "kwin-dbus"
        is_portal_backend = effective_backend == "xdg-portal"
        color_ctx_snapshot = status.get("latest_color_context")
        color_ctx_dict = color_ctx_snapshot if isinstance(color_ctx_snapshot, dict) else {}
        frame_ctx_snapshot = status.get("latest_frame_context")
        frame_source = (
            frame_ctx_snapshot.get("source")
            if isinstance(frame_ctx_snapshot, dict)
            and isinstance(frame_ctx_snapshot.get("source"), dict)
            else {}
        )
        color_backend = str(
            color_ctx_dict.get("backend")
            or frame_source.get("backend")
            or effective_backend
            or "unknown"
        )
        color_transfer = str(
            color_ctx_dict.get("transfer")
            or capture_hdr.get("input_transfer")
            or getattr(self.config, "hdr_transfer", AppConfig.hdr_transfer)
        )
        color_primaries = str(
            color_ctx_dict.get("primaries")
            or capture_hdr.get("input_primaries")
            or getattr(self.config, "hdr_primaries", AppConfig.hdr_primaries)
        )
        color_source = str(
            color_ctx_dict.get("source")
            or capture_hdr.get("metadata_source")
            or capture_hdr.get("source")
            or ("kwin display-referred" if is_kwin_backend else "unknown")
        )
        if is_portal_backend and color_source == "unknown":
            color_source = "xdg-portal display-referred"
        display_referred = bool(color_ctx_dict.get("display_referred", False))
        if not display_referred and is_kwin_backend:
            display_referred = True
        if (
            not display_referred
            and is_portal_backend
            and color_source == "xdg-portal display-referred"
        ):
            display_referred = True
        skip_display_gamut = bool(
            color_ctx_dict.get("skip_display_gamut_adaptation", False)
            or status.get("skip_display_gamut_adaptation", False)
        )
        if display_referred and not color_ctx_dict:
            color_transfer = "srgb"
            color_primaries = "bt709"
            skip_display_gamut = True
        elif display_referred and not skip_display_gamut:
            skip_display_gamut = True
        portal_frame_diag: dict[str, object] = {}
        if is_portal_backend and active_capture is not None:
            raw_diag = getattr(active_capture, "_last_frame_diag", None)
            if isinstance(raw_diag, dict):
                portal_frame_diag = raw_diag
        metadata_source = color_source
        compositor_hdr_mode = bool(getattr(self.config, "compositor_hdr_mode", False))
        effective_sdr_boost_compensation = compositor_hdr_mode and not display_referred
        if self.is_running():
            effective_sdr_boost_compensation = bool(self._runtime.sdr_boost_compensation_enabled)
        display_preset = str(getattr(self.config, "display_preset", "hdr")).strip().lower()
        hdr_notes: list[str] = []
        hdr_warnings: list[str] = []
        if is_kwin_backend and display_preset == "hdr":
            hdr_notes.append(
                "KWin ScreenShot2 captures are display-referred SDR; using safe sRGB defaults."
            )
        elif is_portal_backend and display_preset == "hdr":
            hdr_notes.append(
                "XDG portal PipeWire captures are display-referred SDR; using safe sRGB defaults."
            )
        if is_kwin_backend and compositor_hdr_mode:
            hdr_warnings.append("Screen capture via Screenshot2 cannot preserve HDR color accuracy")
        elif display_preset == "hdr" and metadata_source == "unknown":
            hdr_warnings.append(
                "HDR preset active but capture metadata unavailable; using user preset assumptions."
            )
        status["hdr_colour_path"] = {
            "backend": color_backend,
            "transfer": color_transfer,
            "primaries": color_primaries,
            "source": color_source,
            "display_referred": display_referred,
            "skip_display_gamut_adaptation": skip_display_gamut,
            "sdr_boost_compensation_enabled": effective_sdr_boost_compensation,
            "portal_negotiated_format": portal_frame_diag.get("format"),
            "portal_stride": portal_frame_diag.get("stride"),
            "portal_caps": portal_frame_diag.get("caps"),
            "display_preset": str(getattr(self.config, "display_preset", "hdr")),
            "compositor_hdr_mode": compositor_hdr_mode,
            "sdr_boost_nits": float(getattr(self.config, "sdr_boost_nits", 80.0)),
            "effective_sdr_boost_scalar": float(
                effective_sdr_boost(
                    sdr_boost_nits=float(getattr(self.config, "sdr_boost_nits", 80.0))
                )
            ),
            "hdr_max_nits": float(
                capture_hdr.get("hdr_max_nits", getattr(self.config, "hdr_max_nits", 1000.0))
            ),
            "hdr_transfer": color_transfer,
            "hdr_primaries": color_primaries,
            "capture_metadata_source": metadata_source,
            "tone_mapping_applied": tone_mapping_applied,
            "sdr_compensation_applied": compositor_hdr_mode
            and effective_sdr_boost_compensation
            and abs(
                effective_sdr_boost(
                    sdr_boost_nits=float(getattr(self.config, "sdr_boost_nits", 80.0))
                )
                - 1.0
            )
            > 1e-6,
            "sdr_compensation_suppressed_for_hdr": compositor_hdr_mode
            and not effective_sdr_boost_compensation,
            "assumption": str(capture_hdr.get("assumption", "unknown")),
            "notes": hdr_notes,
            "warnings": hdr_warnings,
        }
        latest_color_context = status.get("latest_color_context")
        if isinstance(latest_color_context, dict):
            latest_color_context = {
                **latest_color_context,
                "backend": color_backend,
                "sdr_boost_compensation_enabled": effective_sdr_boost_compensation,
                "portal_negotiated_format": portal_frame_diag.get("format"),
                "portal_stride": portal_frame_diag.get("stride"),
                "portal_caps": portal_frame_diag.get("caps"),
            }
            status["latest_color_context"] = latest_color_context
        from nanoleaf_sync.runtime.colour_path_diagnostics import build_capture_colour_diagnostics

        status["capture_colour_diagnostics"] = build_capture_colour_diagnostics(
            status=status,
            hdr_colour_path=status["hdr_colour_path"],
            capture=active_capture,
        )
        status["hid_live_send_policy"] = str(
            getattr(self._driver, "last_live_send_policy", "") or ""
        )
        status["stale_output_drop_rate_per_second"] = float(
            self._runtime.stale_drop_rate_per_second()
        )
        if startup_state == "waiting_for_screen_selection":
            if self._runtime.portal_selection_started_at is None:
                self._runtime.portal_selection_started_at = time.perf_counter()
            elapsed = max(
                0.0,
                time.perf_counter() - float(self._runtime.portal_selection_started_at),
            )
            status["portal_selection_elapsed_s"] = elapsed
        else:
            self._runtime.portal_selection_started_at = None
            status["portal_selection_elapsed_s"] = 0.0
        if self._driver is not None:
            from nanoleaf_sync.device.transport_profiler import build_usb_transport_profile

            status["usb_transport_profile"] = build_usb_transport_profile(self._driver).as_dict()
        if self._capture is not None:
            status["portal_restore_token_state"] = str(
                getattr(self._capture, "portal_restore_token_state", "") or ""
            )
            kwin_diag = getattr(self._capture, "last_capture_diagnostics", None)
            if isinstance(kwin_diag, dict) and kwin_diag:
                status["kwin_capture_diagnostics"] = dict(kwin_diag)
        status["capture_monitor"] = str(getattr(self.config, "capture_monitor", "") or "")
        from nanoleaf_sync.runtime.status_warnings import build_runtime_warnings

        status["runtime_warnings"] = build_runtime_warnings(status=status)
        from nanoleaf_sync.runtime.mirroring_confidence import compute_mirroring_confidence

        status["mirroring_confidence"] = compute_mirroring_confidence(status)
        return status

    def capture_one_diagnostic_frame(self) -> dict[str, object]:
        from nanoleaf_sync.runtime.engine import process_frame
        from nanoleaf_sync.runtime.processing import zones_from_config
        from nanoleaf_sync.runtime.zone_derivation import derive_source_zone_artifacts

        if self.is_running():
            return {
                "ok": False,
                "message": (
                    "Mirroring is already running; stop mirroring before "
                    "one-shot diagnostic capture."
                ),
            }
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
                        prefer_backend=normalize_capture_backend(
                            self.config.prefer_backend, default="auto"
                        ),
                        hdr_transfer=self.config.hdr_transfer,
                        hdr_primaries=self.config.hdr_primaries,
                        hdr_max_nits=self.config.hdr_max_nits,
                        auto_probe_enabled=getattr(self.config, "auto_probe_enabled", None),
                        cached_probe_winner=self._cached_probe_winner
                        or self.config.auto_selected_backend,
                        drm_zone_patch_capture=effective_drm_zone_patch_capture(
                            drm_zone_patch_capture=bool(
                                getattr(self.config, "drm_zone_patch_capture", False)
                            ),
                            sync_mode=str(getattr(self.config, "sync_mode", "standard")),
                        ),
                        capture_monitor=str(getattr(self.config, "capture_monitor", "") or ""),
                    )
                    created_capture = True
                init = getattr(capture, "initialize", None)
                if callable(init) and not init():
                    return {
                        "ok": False,
                        "message": "Capture backend failed to initialize for one-shot diagnostics.",
                    }
            frame = capture.capture()
            if frame is None:
                return {
                    "ok": False,
                    "message": "Capture backend returned no frame for one-shot diagnostics.",
                }
            img_h, img_w, _ = frame.shape
            artifacts = derive_source_zone_artifacts(
                config=self.config,
                detected_device_zone_count=self._device_zone_count,
                frame_width=img_w,
                frame_height=img_h,
            )
            zones_px = zones_from_config(artifacts.zones, img_w, img_h)
            mapping_snapshot = resolve_calibration_mapping_from_config(
                config=self.config,
                source_zone_count=len(zones_px),
                detected_device_zone_count=self._device_zone_count,
                source_side_counts=artifacts.side_counts,
            )
            device_zone_indices = list(mapping_snapshot.device_to_source_indices)
            if not device_zone_indices:
                target_count = max(
                    1,
                    int(getattr(self.config, "device_zone_count", 0) or len(zones_px)),
                )
                source_count = len(zones_px)
                if source_count > 0:
                    device_zone_indices = [
                        int((idx * source_count) // target_count) for idx in range(target_count)
                    ]
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
                build_zone_diagnostics=True,
            )
            (
                _,
                sampled_zone_colors,
                pre_led_colors,
                final_zone_colors,
                processing_timings,
                _,
                _,
            ) = processed
            self._runtime.latest_frame_rgb = frame
            self._runtime.last_frame_width = int(img_w)
            self._runtime.last_frame_height = int(img_h)
            self._runtime.latest_zones_px = list(zones_px)
            self._runtime.latest_zone_side_counts = tuple(
                int(i) for i in (artifacts.side_counts or (0, 0, 0, 0))
            )  # type: ignore[assignment]
            self._runtime.latest_edge_sampling_thickness = artifacts.edge_sampling_thickness
            from nanoleaf_sync.runtime.colour_path_diagnostics import (
                build_zone_colour_path_row,
                resolve_mapped_led_index,
                resolve_zone_side,
            )
            from nanoleaf_sync.runtime.engine import _zone_sampling_diagnostic_fields

            device_indices = list(device_zone_indices)
            rows: list[dict[str, object]] = []
            for zone_index, rect in enumerate(zones_px):
                sampled_rgb = tuple(int(c) for c in sampled_zone_colors[zone_index].tolist())  # type: ignore[union-attr]
                mapped_led_index = resolve_mapped_led_index(zone_index, device_indices)
                if mapped_led_index is None:
                    pre_led_rgb = sampled_rgb
                    final_rgb = sampled_rgb
                else:
                    pre_led_rgb = tuple(
                        int(c)
                        for c in pre_led_colors[mapped_led_index].tolist()  # type: ignore[union-attr]
                    )
                    final_rgb = tuple(
                        int(c)
                        for c in final_zone_colors[mapped_led_index].tolist()  # type: ignore[union-attr]
                    )
                rows.append(
                    build_zone_colour_path_row(
                        zone_index=zone_index,
                        rect=rect,
                        side=resolve_zone_side(
                            zone_index,
                            self._runtime.latest_zone_side_counts,
                        ),
                        sampled_rgb=sampled_rgb,
                        mapped_led_index=mapped_led_index,
                        pre_led_rgb=pre_led_rgb,
                        final_rgb=final_rgb,
                        proc_timings=processing_timings,
                        sampling_fields=_zone_sampling_diagnostic_fields(
                            zone_index=zone_index,
                            default_rect=rect,
                            proc_timings=processing_timings,
                        ),
                        color_style=str(getattr(self.config, "color_style", "ambient")),
                    )
                )
            self._runtime.latest_zone_diagnostics = rows
            return {
                "ok": True,
                "message": (
                    f"Captured one diagnostic frame ({img_w}x{img_h}) with {len(rows)} zones."
                ),
            }
        except Exception as exc:
            return {"ok": False, "message": f"One-shot diagnostic capture failed: {exc}"}
        finally:
            if created_capture:
                try:
                    close_fn = getattr(capture, "close", None)
                    if callable(close_fn):
                        close_fn()
                except Exception:
                    logger.warning("Error closing diagnostic capture backend", exc_info=True)

    def forget_portal_restore_token(self) -> dict[str, object]:
        from nanoleaf_sync.tools.portal_tools import forget_portal_restore_token

        return forget_portal_restore_token()

    def run_colour_path_probe(self, *, zone_index: int = 0) -> dict[str, object]:
        from nanoleaf_sync.tools.colour_path_probe import compare_colour_path_stages

        zone_diag = list(getattr(self._runtime, "latest_zone_diagnostics", None) or [])
        if not zone_diag:
            capture = self.capture_one_diagnostic_frame()
            if not capture.get("ok"):
                return capture
            zone_diag = list(getattr(self._runtime, "latest_zone_diagnostics", None) or [])
        if not zone_diag:
            return {"ok": False, "message": "No zone diagnostics are available yet."}
        if zone_index < 0 or zone_index >= len(zone_diag):
            return {
                "ok": False,
                "message": f"Zone index {zone_index} is out of range (0–{len(zone_diag) - 1}).",
            }
        row = zone_diag[zone_index]
        sampled = tuple(int(v) for v in row.get("sampled_rgb", (0, 0, 0)))  # type: ignore[arg-type]
        pre_led = tuple(int(v) for v in row.get("output_rgb_before_led_calibration", sampled))  # type: ignore[arg-type]
        final = tuple(int(v) for v in row.get("final_output_rgb", pre_led))  # type: ignore[arg-type]
        comparison = compare_colour_path_stages(
            captured_rgb=sampled,
            staged_outputs={
                "sampled_zone": sampled,
                "before_style_mapping": tuple(
                    int(v)
                    for v in row.get("output_rgb_before_style_mapping", sampled)  # type: ignore[arg-type]
                ),
                "after_style_mapping": tuple(
                    int(v)
                    for v in row.get("output_rgb_after_style_mapping", sampled)  # type: ignore[arg-type]
                ),
                "after_light_spread": tuple(
                    int(v)
                    for v in row.get("output_rgb_after_light_spread", pre_led)  # type: ignore[arg-type]
                ),
                "after_smoothing": tuple(
                    int(v)
                    for v in row.get("output_rgb_after_smoothing", pre_led)  # type: ignore[arg-type]
                ),
                "after_led_calibration": tuple(
                    int(v)
                    for v in row.get("output_rgb_after_led_calibration", pre_led)  # type: ignore[arg-type]
                ),
                "pre_led_calibration": pre_led,
                "final_output": final,
            },
        )
        return {
            "ok": True,
            "zone_index": zone_index,
            "side": str(row.get("side", "")),
            "comparison": comparison,
            "message": f"Compared colour path for zone {zone_index}.",
        }

    def run_flicker_lab(self, *, scenario_key: str = "all") -> dict[str, object]:
        from nanoleaf_sync.tools.flicker_lab import run_flicker_lab

        return run_flicker_lab(config=self.config, scenario_key=str(scenario_key or "all"))

    def request_portal_pick_color(self) -> dict[str, object]:
        from nanoleaf_sync.tools.portal_tools import request_portal_pick_color

        return request_portal_pick_color()

    def export_diagnostic_bundle(self, output_path: str) -> dict[str, object]:
        from pathlib import Path

        from nanoleaf_sync.tools.diagnostic_bundle import create_diagnostic_bundle

        try:
            bundle = create_diagnostic_bundle(
                Path(output_path),
                runtime_status=self.get_status(),
            )
            return {
                "ok": True,
                "path": str(bundle),
                "message": f"Saved diagnostic bundle to {bundle}",
            }
        except Exception as exc:
            return {"ok": False, "message": f"Could not create diagnostic bundle: {exc}"}

    def export_colour_debug_snapshot(self, output_path: str) -> dict[str, object]:
        from pathlib import Path

        from nanoleaf_sync.runtime.colour_path_diagnostics import write_colour_debug_snapshot

        try:
            frame = getattr(self._runtime, "latest_frame_rgb", None)
            return write_colour_debug_snapshot(
                Path(output_path),
                config=self.config,
                status=self.get_status(),
                frame=frame,
                capture=self._capture,
            )
        except Exception as exc:
            return {"ok": False, "message": f"Could not export colour debug snapshot: {exc}"}

    def make_device_driver(
        self,
        *,
        enable_live_frame_write_optimization: bool = True,
        allow_live_zone_padding: bool = False,
    ) -> DeviceDriver:
        ids = NanoleafUSBIds(vid=self.config.device_vid, pid=self.config.device_pid)
        if int(ids.vid) == 0 or int(ids.pid) == 0:
            raise ValueError(
                "Real device mode requires non-zero device_vid/device_pid. "
                "Configure Nanoleaf USB IDs (for example 0x37fa:0x8201 or 0x37fa:0x8202)."
            )
        from nanoleaf_sync.config.normalize import ALLOWED_NANOLEAF_USB_IDS

        allowed_pids = ALLOWED_NANOLEAF_USB_IDS.get(int(ids.vid))
        if not allowed_pids or int(ids.pid) not in allowed_pids:
            if getattr(self.config, "allow_custom_device_ids", False):
                logger.warning(
                    "Opening custom USB device IDs vid=0x%04x pid=0x%04x",
                    int(ids.vid),
                    int(ids.pid),
                )
            else:
                logger.warning(
                    "Non-default USB device IDs without allow_custom_device_ids; "
                    "opening vid=0x%04x pid=0x%04x (normalization should clamp).",
                    int(ids.vid),
                    int(ids.pid),
                )
        send_policy = preferred_send_policy_from_config(self.config)
        prefer_mailbox = send_policy == "mailbox"
        prefer_write_only = (
            is_four_d_sync(str(getattr(self.config, "sync_mode", "standard")))
            or send_policy == "write_only"
        )
        return NanoleafUSBDriver(
            ids=ids,
            output_channel_order=self.config.output_channel_order,
            configured_zone_count=int(getattr(self.config, "device_zone_count", 0) or 0),
            enable_live_frame_write_optimization=bool(enable_live_frame_write_optimization),
            prefer_write_only_live_send=prefer_write_only,
            prefer_mailbox_live_send=prefer_mailbox,
            auto_turn_on=bool(getattr(self.config, "auto_turn_on", True)),
            allow_live_zone_padding=allow_live_zone_padding,
        )

    def _clear_backends(self) -> None:
        self._capture = None
        self._driver = None
        with self._status_lock:
            self._device_discovered = False
            self._device_model = None
            self._device_zone_count = None

    def _resolve_shutdown_zone_count(self, driver: object) -> int:
        zone_count = int(getattr(driver, "zone_count", 0) or 0)
        if zone_count <= 0:
            zone_count = int(getattr(driver, "reported_zone_count", 0) or 0)
        if zone_count <= 0:
            zone_count = int(getattr(self.config, "device_zone_count", 0) or 0)
        return max(0, zone_count)

    @staticmethod
    def _driver_is_initialized(driver: object) -> bool:
        if bool(getattr(driver, "_initialized", False)):
            return True
        return bool(getattr(driver, "initialized", False))

    def _send_shutdown_black_frame(self, *, require_driver_ready: bool) -> bool:
        if require_driver_ready and not self._runtime.driver_ready:
            return False
        with self._status_lock:
            driver = self._driver
        if driver is None:
            return False
        try:
            if not self._driver_is_initialized(driver):
                initialize = getattr(driver, "initialize", None)
                if not callable(initialize):
                    return False
                initialize()
            zone_count = self._resolve_shutdown_zone_count(driver)
            if zone_count <= 0:
                return False
            driver.send_frame([(0, 0, 0)] * zone_count)
            return True
        except Exception:
            logger.debug(
                "Unable to send shutdown black frame (expected if already off)",
                exc_info=True,
            )
            return False

    def _should_attempt_ephemeral_shutdown_driver(self) -> bool:
        if self._capture_backend_override is not None or self._driver_override is not None:
            return False
        if bool(getattr(self.config, "use_mock_capture", True)):
            return False
        return (
            int(getattr(self.config, "device_vid", 0) or 0) > 0
            and int(getattr(self.config, "device_pid", 0) or 0) > 0
        )

    def _send_ephemeral_shutdown_black_frame(self) -> bool:
        if not self._should_attempt_ephemeral_shutdown_driver():
            return False
        driver = None
        try:
            driver = self.make_device_driver(
                enable_live_frame_write_optimization=False,
                allow_live_zone_padding=True,
            )
            driver.initialize()
            zone_count = self._resolve_shutdown_zone_count(driver)
            if zone_count <= 0:
                return False
            driver.send_frame([(0, 0, 0)] * zone_count)
            return True
        except Exception:
            logger.debug(
                "Unable to send ephemeral shutdown black frame",
                exc_info=True,
            )
            return False
        finally:
            if driver is not None:
                with contextlib.suppress(Exception):
                    driver.close()

    def turn_off_lights(self) -> bool:
        if self._send_shutdown_black_frame(require_driver_ready=False):
            return True
        return self._send_ephemeral_shutdown_black_frame()

    def _send_stop_black_frame(self) -> None:
        self._send_shutdown_black_frame(require_driver_ready=True)

    def _close_backends(self) -> None:
        capture = self._capture
        try:
            if capture is not None:
                close_fn = getattr(capture, "close", None)
                if close_fn is not None:
                    close_fn()
        except Exception:
            logger.warning(
                "Error closing capture backend '%s'",
                getattr(capture, "name", repr(capture)),
                exc_info=True,
            )
        finally:
            self._capture = None

        with self._status_lock:
            driver = self._driver
            try:
                if driver is not None:
                    driver.close()
            except Exception:
                logger.warning("Error closing device driver", exc_info=True)
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
                signature = _build_auto_probe_signature(
                    width,
                    height,
                    capture_monitor=str(getattr(self.config, "capture_monitor", "") or ""),
                )
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
                        should_probe = signature_changed or not _is_valid_auto_probe_winner(
                            cached_winner
                        )

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
                    drm_zone_patch_capture=effective_drm_zone_patch_capture(
                        drm_zone_patch_capture=bool(
                            getattr(self.config, "drm_zone_patch_capture", False)
                        ),
                        sync_mode=str(getattr(self.config, "sync_mode", "standard")),
                    ),
                    capture_monitor=str(getattr(self.config, "capture_monitor", "") or ""),
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
                        previous_winner = str(
                            getattr(self.config, "auto_selected_backend", "") or ""
                        )
                        previous_signature = str(
                            getattr(self.config, "auto_probe_signature", "") or ""
                        )
                        needs_write = (
                            should_probe
                            or previous_winner != winner
                            or previous_signature != signature
                        )
                        updated_config = replace(
                            self.config,
                            auto_selected_backend=winner or "",
                            auto_probe_signature=signature,
                        )
                        if needs_write:
                            updated_config = replace(
                                updated_config,
                                auto_probe_timestamp=datetime.now(UTC).isoformat(),
                            )
                            if (
                                self._capture_backend_override is None
                                and self._driver_override is None
                            ):
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
                self._driver = self.make_device_driver()

            self._driver.initialize()
            reported_zone_count = getattr(self._driver, "reported_zone_count", None)
            if reported_zone_count is None:
                reported_zone_count = getattr(self._driver, "zone_count", None)
            zone_authority = evaluate_device_zone_authority(
                config=self.config,
                detected_device_zone_count=reported_zone_count,
            )
            if zone_authority.blocked:
                self._runtime.mark_device_zone_mismatch(
                    zone_authority.message,
                    authority=zone_authority,
                )
                raise RuntimeError(zone_authority.message)
            if zone_authority.override_active and zone_authority.message:
                logger.warning(zone_authority.message)
            self._runtime.driver_ready = True
            with self._status_lock:
                self._device_discovered = True
                self._device_model = getattr(self._driver, "model_number", None)
                self._device_zone_count = reported_zone_count
                self._runtime.device_zone_count_source = zone_authority.device_zone_count_source
                self._runtime.configured_device_zone_count = (
                    zone_authority.configured_device_zone_count
                )
                self._runtime.detected_device_zone_count = zone_authority.detected_device_zone_count
                self._runtime.effective_device_zone_count = (
                    zone_authority.effective_device_zone_count
                )
                self._runtime.device_zone_count_mismatch = zone_authority.device_zone_count_mismatch
                self._runtime.mapping_repair_required = zone_authority.mapping_repair_required
                self._runtime.device_zone_override_active = zone_authority.override_active
            if claimed_each_boot_probe:
                self._finish_each_boot_probe(success=True)
        except Exception as exc:
            self._runtime.start_failure_reason = str(exc)
            self._runtime.capture_backend_ready = self._capture is not None
            self._runtime.driver_ready = False
            if claimed_each_boot_probe:
                self._finish_each_boot_probe(success=False)
            raise

    def _maybe_heal_stale_probe_cache(self) -> None:
        if normalize_capture_backend(self.config.prefer_backend, default="auto") != "auto":
            return
        if str(getattr(self.config, "auto_selected_backend", "") or "") != "kmsgrab":
            return
        if self._capture is None or getattr(self._capture, "name", None) != "kmsgrab":
            return
        capture_path = getattr(self._capture, "last_capture_path", None)
        if capture_path != "kwin-dbus":
            self._kmsgrab_fallback_streak = 0
            return
        frames_sent = int(self._runtime.frames_sent or 0)
        if frames_sent <= self._probe_heal_last_frames:
            return
        self._probe_heal_last_frames = frames_sent
        self._kmsgrab_fallback_streak += 1
        if self._kmsgrab_fallback_streak < 3:
            return
        if self._capture_backend_override is not None:
            return

        signature = _build_auto_probe_signature(
            self._capture_width,
            self._capture_height,
            capture_monitor=str(getattr(self.config, "capture_monitor", "") or ""),
        )
        healed_winner = "kwin-dbus"
        updated_config = replace(
            self.config,
            auto_selected_backend=healed_winner,
            auto_probe_signature=signature,
            auto_probe_timestamp=datetime.now(UTC).isoformat(),
        )
        try:
            ConfigManager().save(updated_config)
        except Exception as exc:
            logger.warning("Failed to persist healed auto-probe cache metadata: %s", exc)
            return
        self.config = updated_config
        self._cached_probe_winner = healed_winner
        self._selection_reason = "cached-probe"
        self._kmsgrab_fallback_streak = 0
        logger.info(
            "Healed stale kmsgrab auto-probe cache; persisted winner=%s after runtime fallback",
            healed_winner,
        )

    def _maybe_invalidate_kwin_probe_cache_for_invalid_screen(self) -> None:
        if self._kwin_invalid_screen_invalidation_done:
            return
        if normalize_capture_backend(self.config.prefer_backend, default="auto") != "auto":
            return
        if str(getattr(self.config, "auto_selected_backend", "") or "") != "kwin-dbus":
            return
        if self._capture is not None and getattr(self._capture, "name", None) != "kwin-dbus":
            return
        if int(self._runtime.consecutive_errors or 0) < 3:
            return
        last_error = str(self._runtime.last_error or "")
        if not is_kwin_invalid_screen_error(last_error):
            return
        if self._capture_backend_override is not None:
            return

        self._kwin_invalid_screen_invalidation_done = True
        reset_cached_probe_winner()
        self._cached_probe_winner = None
        updated_config = replace(
            self.config,
            auto_selected_backend="",
            auto_probe_signature="",
            auto_probe_timestamp=datetime.now(UTC).isoformat(),
        )
        try:
            ConfigManager().save(updated_config)
        except Exception as exc:
            logger.warning("Failed to persist invalidated kwin-dbus auto-probe cache: %s", exc)
            return
        self.config = updated_config
        self._selection_reason = "fallback"
        logger.warning(
            "Invalidated cached kwin-dbus auto-probe winner after repeated InvalidScreen "
            "runtime failures; fresh probe will run on next install."
        )

    def _get_capture_backend(self) -> object | None:
        with self._status_lock:
            return self._capture

    def _get_driver_backend(self) -> object | None:
        with self._status_lock:
            return self._driver

    def _run_runtime(self) -> None:
        run_runtime_engine(
            config=self.config,
            state=self._runtime,
            get_capture=self._get_capture_backend,
            get_driver=self._get_driver_backend,
            install_drivers=self._install_drivers,
            close_backends=self._close_backends,
            clear_backends=self._clear_backends,
            send_final_frame=self._send_stop_black_frame,
            can_mirroring_write=self._can_mirroring_write,
        )

    def install_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            stop_result = self.stop(timeout=5.0)
            if not stop_result:
                self.turn_off_lights()
                logger.warning(
                    "Signal %d handler: clean shutdown timed out; forcing exit",
                    signum,
                )
                os._exit(1)

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)


def main() -> None:  # pragma: no cover
    from nanoleaf_sync.capture._drm_helper_bridge import _helper_binary_path
    from nanoleaf_sync.tools.setcap_helper import ensure_helper_caps

    cfg_mgr = ConfigManager()
    config = cfg_mgr.load()
    ensure_helper_caps(_helper_binary_path(), show_dialog=False)

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
