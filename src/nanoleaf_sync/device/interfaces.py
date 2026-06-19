from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from nanoleaf_sync.color._types import RGBTuple


@dataclass(frozen=True)
class DriverCapabilities:
    name: str
    supports_streaming: bool = True
    max_zones: int = 0


@dataclass(frozen=True)
class NanoleafUSBIds:
    vid: int
    pid: int


@runtime_checkable
class DeviceDriver(Protocol):
    """Runtime contract for all device drivers used by the service."""

    def initialize(self) -> None: ...

    def send_frame(self, colors: Sequence[RGBTuple]) -> None: ...

    def close(self) -> None: ...
