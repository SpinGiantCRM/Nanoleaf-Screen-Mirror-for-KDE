from __future__ import annotations

import os


def _env_enabled(name: str, *, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


NANOLEAF_ENABLE_WAVELET_ENV = "NANOLEAF_ENABLE_WAVELET"
NANOLEAF_ENABLE_MOTION_GOV_ENV = "NANOLEAF_ENABLE_MOTION_GOV"
NANOLEAF_ENABLE_GUIDED_CALIB_ENV = "NANOLEAF_ENABLE_GUIDED_CALIB"
NANOLEAF_ENABLE_VULKAN_SAMPLER_ENV = "NANOLEAF_ENABLE_VULKAN_SAMPLER"
NANOLEAF_ENABLE_MAILBOX_SEND_ENV = "NANOLEAF_ENABLE_MAILBOX_SEND"


def wavelet_sampling_enabled() -> bool:
    return _env_enabled(NANOLEAF_ENABLE_WAVELET_ENV)


def motion_governor_enabled() -> bool:
    return _env_enabled(NANOLEAF_ENABLE_MOTION_GOV_ENV)


def guided_calibration_enabled() -> bool:
    return _env_enabled(NANOLEAF_ENABLE_GUIDED_CALIB_ENV)


def vulkan_sampler_enabled() -> bool:
    return _env_enabled(NANOLEAF_ENABLE_VULKAN_SAMPLER_ENV)


def mailbox_send_enabled() -> bool:
    return _env_enabled(NANOLEAF_ENABLE_MAILBOX_SEND_ENV)
