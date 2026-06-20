from __future__ import annotations

import pytest

from nanoleaf_sync.capture.kmsgrab import validated_drm_card_path
from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.config.normalize import ALLOWED_NANOLEAF_USB_IDS, validate_config
from nanoleaf_sync.runtime.diagnostics_exports import _create_export_dir, _export_safe_status


def test_validated_drm_card_path_rejects_invalid_paths() -> None:
    with pytest.raises(Exception, match="Invalid DRM card path"):
        validated_drm_card_path("/etc/passwd")


def test_validated_drm_card_path_accepts_card0() -> None:
    assert validated_drm_card_path("/dev/dri/card0") == "/dev/dri/card0"


def test_normalize_config_clamps_non_allowlisted_usb_ids() -> None:
    cfg = AppConfig(device_vid=0x1234, device_pid=0x5678, allow_custom_device_ids=False)
    normalized = validate_config(cfg)
    assert normalized.device_vid == 0x37FA
    assert normalized.device_pid == 0x8202


def test_normalize_config_keeps_custom_usb_ids_when_enabled() -> None:
    cfg = AppConfig(device_vid=0x1234, device_pid=0x5678, allow_custom_device_ids=True)
    normalized = validate_config(cfg)
    assert normalized.device_vid == 0x1234
    assert normalized.device_pid == 0x5678


def test_allowed_nanoleaf_usb_ids_contains_defaults() -> None:
    assert 0x8201 in ALLOWED_NANOLEAF_USB_IDS[0x37FA]
    assert 0x8202 in ALLOWED_NANOLEAF_USB_IDS[0x37FA]


def test_create_export_dir_has_restrictive_permissions() -> None:
    path = _create_export_dir()
    try:
        mode = path.stat().st_mode & 0o777
        assert mode == 0o700
    finally:
        path.rmdir()


def test_export_safe_status_strips_frame_payload() -> None:
    safe = _export_safe_status({"running": True, "_latest_frame_rgb": object()})
    assert "_latest_frame_rgb" not in safe
    assert safe["running"] is True
