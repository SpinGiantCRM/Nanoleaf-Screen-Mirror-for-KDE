from __future__ import annotations

import argparse

from nanoleaf_sync.capture.factory import create_capture_backend
from nanoleaf_sync.capture.dimensions import resolve_capture_dims
from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.device.interfaces import NanoleafUSBIds
from nanoleaf_sync.device.usb_driver import NanoleafUSBDriver


DEFAULT_SMOKE_WIDTH = 320
DEFAULT_SMOKE_HEIGHT = 180


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
    width, height = resolve_capture_dims(cfg)
    if width <= 0 or height <= 0:
        width, height = DEFAULT_SMOKE_WIDTH, DEFAULT_SMOKE_HEIGHT

    capture = create_capture_backend(
        width=width,
        height=height,
        use_mock_capture=cfg.use_mock_capture,
        prefer_backend=cfg.prefer_backend,
        hdr_max_nits=cfg.hdr_max_nits,
        hdr_transfer=cfg.hdr_transfer,
        hdr_primaries=cfg.hdr_primaries,
    )
    frame = capture.capture()
    print(f"capture ok: frame shape={frame.shape}")

    driver = NanoleafUSBDriver(ids=NanoleafUSBIds(vid=cfg.device_vid, pid=cfg.device_pid))

    try:
        driver.initialize()
        zones = getattr(driver, "zone_count", None)
        model = getattr(driver, "model_number", None)
        print(f"device init ok: model={model} zones={zones}")

        if args.send_test_frame:
            zone_count = int(zones or 8)
            colors = [(8, 0, 0)] * zone_count
            colors[max(0, zone_count // 3 - 1) : max(1, zone_count // 3 + 1)] = [(0, 8, 0)] * 2
            colors[max(0, (2 * zone_count) // 3 - 1) : max(1, (2 * zone_count) // 3 + 1)] = [(0, 0, 8)] * 2
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
