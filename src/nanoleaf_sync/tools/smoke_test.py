from __future__ import annotations

import argparse
import os

from nanoleaf_sync.capture.backend_selection import (
    AUTO_BACKEND,
    AUTO_PROBE_CANDIDATES,
    normalize_backend_preference,
)
from nanoleaf_sync.capture.factory import auto_probe_effective_state, create_capture_backend
from nanoleaf_sync.capture.dimensions import resolve_capture_dims
from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.device.interfaces import NanoleafUSBIds
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver
from nanoleaf_sync.runtime.errors import translate_runtime_error


DEFAULT_SMOKE_WIDTH = 320
DEFAULT_SMOKE_HEIGHT = 180


def _effective_runtime_zone_count(*, configured: int, detected: int | None) -> int | None:
    configured_count = int(configured or 0)
    if configured_count > 0:
        return configured_count
    detected_count = int(detected or 0)
    if detected_count > 0:
        return detected_count
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual smoke test for nanoleaf-kde-sync")
    parser.add_argument(
        "--send-test-frame",
        action="store_true",
        help="Send a temporary low-brightness RGB test frame to the active device backend.",
    )
    args = parser.parse_args(argv)

    cfg = ConfigManager().load()

    print("== nanoleaf-kde-sync smoke test ==")
    print(f"capture mode: {'mock' if cfg.use_mock_capture else cfg.prefer_backend}")
    print("device mode: real-usb")
    print(
        "probe config: "
        f"configured_enabled={cfg.auto_probe_enabled} policy={cfg.auto_probe_policy} "
        f"cached_winner={cfg.auto_selected_backend or 'none'} "
        f"signature={cfg.auto_probe_signature or 'none'} "
        f"timestamp={cfg.auto_probe_timestamp or 'none'}"
    )
    effective_probe_enabled, effective_probe_reason = auto_probe_effective_state(cfg.auto_probe_enabled)
    print(
        "probe effective: "
        f"enabled={effective_probe_enabled} reason={effective_probe_reason}"
    )
    width, height = resolve_capture_dims(cfg)
    if width <= 0 or height <= 0:
        width, height = DEFAULT_SMOKE_WIDTH, DEFAULT_SMOKE_HEIGHT

    if int(cfg.device_vid) == 0 or int(cfg.device_pid) == 0:
        print(
            "device config error: VID/PID not configured "
            "(set device_vid/device_pid in config before running smoke test)."
        )
        return 1

    capture = create_capture_backend(
        width=width,
        height=height,
        use_mock_capture=cfg.use_mock_capture,
        prefer_backend=cfg.prefer_backend,
        hdr_max_nits=cfg.hdr_max_nits,
        hdr_transfer=cfg.hdr_transfer,
        hdr_primaries=cfg.hdr_primaries,
        auto_probe_enabled=cfg.auto_probe_enabled,
        cached_probe_winner=cfg.auto_selected_backend or None,
    )
    effective_backend = getattr(capture, "name", "unknown")
    requested_backend = normalize_backend_preference(cfg.prefer_backend)
    cached_probe_winner = cfg.auto_selected_backend or None
    if requested_backend != AUTO_BACKEND:
        selection_reason = "explicit"
    elif cached_probe_winner and cached_probe_winner == effective_backend:
        selection_reason = "cached-probe"
    elif effective_backend in AUTO_PROBE_CANDIDATES:
        selection_reason = "fresh-probe"
    else:
        selection_reason = "fallback"
    print(
        "backend decision: "
        f"requested={cfg.prefer_backend} effective={effective_backend} selection_reason={selection_reason}"
    )

    try:
        frame = capture.capture()
    except Exception as exc:
        translated = translate_runtime_error(exc)
        print(f"capture failed: kind={translated.kind}")
        print(f"capture error: {translated.summary}")
        print(f"guidance: {translated.guidance}")
        if translated.kind == "kwin-authorization":
            desktop_startup = (os.environ.get("DESKTOP_STARTUP_ID") or "unset").strip() or "unset"
            activation_token = (os.environ.get("XDG_ACTIVATION_TOKEN") or "unset").strip() or "unset"
            print(
                "context warning: shell-run smoke tests may lack KDE launcher policy unless launched from "
                "an authorized desktop entry."
            )
            print(
                "effective activation context: "
                f"DESKTOP_STARTUP_ID={desktop_startup} XDG_ACTIVATION_TOKEN={activation_token}"
            )
        raise SystemExit(1) from exc
    print(f"capture ok: frame shape={frame.shape}")

    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(vid=cfg.device_vid, pid=cfg.device_pid))

    try:
        driver.initialize()
        zones = getattr(driver, "zone_count", None)
        detected_zones = getattr(driver, "reported_zone_count", zones)
        model = getattr(driver, "model_number", None)
        configured_zones = int(getattr(cfg, "device_zone_count", 0) or 0)
        calibration_zones = int(getattr(getattr(cfg, "calibration", None), "device_zone_count", 0) or 0)
        effective_zones = _effective_runtime_zone_count(configured=configured_zones, detected=detected_zones)
        print(f"device init ok: model={model} zones={zones}")
        print(
            "zone-count diagnostics: "
            f"detected={int(detected_zones or 0) or 'unknown'} "
            f"configured={configured_zones or 'auto'} "
            f"effective_runtime={effective_zones or 'unknown'} "
            f"nested_calibration={calibration_zones or 'auto'}"
        )

        if args.send_test_frame:
            zone_count = int(effective_zones or zones or 8)
            colors = [(8, 0, 0)] * zone_count
            colors[max(0, zone_count // 3 - 1) : max(1, zone_count // 3 + 1)] = [(0, 8, 0)] * 2
            colors[max(0, (2 * zone_count) // 3 - 1) : max(1, (2 * zone_count) // 3 + 1)] = [
                (0, 0, 8)
            ] * 2
            driver.send_frame(colors)
            print("test frame sent (low brightness).")
        else:
            print("test frame not sent (use --send-test-frame to send one frame).")
    finally:
        try:
            driver.close()
        except Exception:
            pass
        try:
            close_fn = getattr(capture, "close", None)
            if close_fn is not None:
                close_fn()
        except Exception:
            pass

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
