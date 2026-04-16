from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, Tuple, runtime_checkable

RGBTuple = Tuple[int, int, int]


@dataclass(frozen=True)
class DriverCapabilities:
    name: str
    supports_streaming: bool = True
    max_zones: int = 0


@runtime_checkable
class DeviceDriver(Protocol):
    """Runtime contract for all device drivers used by the service."""

    def initialize(self) -> None: ...

    def send_frame(self, colors: Sequence[RGBTuple]) -> None: ...

    def close(self) -> None: ...
