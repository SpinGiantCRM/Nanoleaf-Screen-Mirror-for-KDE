from __future__ import annotations

import os
from unittest.mock import patch

import numpy as np

from nanoleaf_sync.capture.vulkan_sampler import VulkanZoneSampler


def test_vulkan_probe_disabled_by_env(monkeypatch) -> None:
    monkeypatch.setenv("NANOLEAF_ENABLE_VULKAN_SAMPLER", "0")
    from importlib import reload

    import nanoleaf_sync.runtime.novel_features as novel

    reload(novel)
    import nanoleaf_sync.capture.vulkan_sampler as vs

    reload(vs)
    status = vs.VulkanZoneSampler.probe()
    assert status.available is False
    assert status.reason == "disabled_by_env"


def test_vulkan_try_create_falls_back_without_fd() -> None:
    sampler = VulkanZoneSampler.try_create(width=1920, height=1080, dma_buf_fd=-1)
    assert sampler is None


@patch("nanoleaf_sync.capture._vulkan_loader.vulkan_available", return_value=True)
@patch("nanoleaf_sync.capture._vulkan_loader.import_dma_buf_image", return_value=True)
@patch(
    "nanoleaf_sync.capture._vulkan_loader.dispatch_zone_sampler",
    return_value=np.array([[255, 0, 0]], dtype=np.uint8),
)
def test_vulkan_import_and_dispatch(_dispatch, _import, _available, monkeypatch) -> None:
    monkeypatch.setenv("NANOLEAF_ENABLE_VULKAN_SAMPLER", "1")
    os.environ["NANOLEAF_VULKAN_FORCE_AVAILABLE"] = "1"
    sampler = VulkanZoneSampler.try_create(width=100, height=50, dma_buf_fd=42)
    assert sampler is not None
    colors = sampler.sample_zone_rects([(0, 0, 10, 10)])
    assert colors.shape == (1, 3)
    assert int(colors[0, 0]) == 255
    sampler.close()


def test_vulkan_falls_back_when_init_fails(monkeypatch) -> None:
    monkeypatch.setenv("NANOLEAF_ENABLE_VULKAN_SAMPLER", "1")
    with patch("nanoleaf_sync.capture._vulkan_loader.vulkan_available", return_value=False):
        sampler = VulkanZoneSampler.try_create(width=100, height=50, dma_buf_fd=3)
    assert sampler is None
