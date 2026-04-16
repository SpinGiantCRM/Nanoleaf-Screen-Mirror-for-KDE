from __future__ import annotations

import logging
from typing import Optional, Sequence

from .interfaces import DeviceDriver, DriverCapabilities, RGBTuple

logger = logging.getLogger(__name__)


class MockNanoleafUSBDriver(DeviceDriver):
    """Mock driver for development/testing without real Nanoleaf hardware."""

    capabilities = DriverCapabilities(name="mock-nanoleaf-usb")

    def __init__(self, *, report_size: int = 64) -> None:
        self.report_size = report_size
        self.last_colors: Optional[Sequence[RGBTuple]] = None
        self._initialized = False
        self._frames_sent = 0

    def initialize(self) -> None:
        self._initialized = True

    def send_frame(self, colors: Sequence[RGBTuple]) -> None:
        if not self._initialized:
            raise RuntimeError("Mock driver not initialized. Call initialize() first.")
        self.last_colors = list(colors)
        self._frames_sent += 1
        if logger.isEnabledFor(logging.DEBUG) and (
            self._frames_sent == 1 or self._frames_sent % 60 == 0
        ):
            sample = self.last_colors[: min(3, len(self.last_colors))]
            logger.debug(
                "[mock-usb] frame zones=%s sample=%s frame=%s",
                len(self.last_colors),
                sample,
                self._frames_sent,
            )

    def close(self) -> None:
        self._initialized = False
