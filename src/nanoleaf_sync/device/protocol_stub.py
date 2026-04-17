from __future__ import annotations

from typing import List, Sequence

import numpy as np

from nanoleaf_sync.device.interfaces import RGBTuple


class NanoleafPCScreenMirrorProtocolStub:
    """Placeholder protocol packer for "PC Screen Mirror LS over USB"."""

    def __init__(self, *, report_size: int = 64) -> None:
        self.report_size = int(report_size)

    def build_hid_report(self, colors: Sequence[RGBTuple]) -> List[int]:
        report = bytearray(self.report_size)

        header_offset = 1
        if self.report_size >= 4:
            report[header_offset : header_offset + 3] = b"\xAA\x55\x00"

        offset = header_offset + 3
        capacity = max(0, self.report_size - offset)
        if capacity and colors:
            payload = np.asarray(colors, dtype=np.uint8).reshape(-1)
            usable = min(capacity, payload.size)
            report[offset : offset + usable] = payload[:usable].tobytes()

        return list(report)
