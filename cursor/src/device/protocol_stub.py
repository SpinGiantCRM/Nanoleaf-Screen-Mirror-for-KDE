from __future__ import annotations

from typing import List, Sequence

from .interfaces import RGBTuple


class NanoleafPCScreenMirrorProtocolStub:
    """Placeholder protocol packer for "PC Screen Mirror LS over USB"."""

    def __init__(self, *, report_size: int = 64) -> None:
        self.report_size = int(report_size)

    def build_hid_report(self, colors: Sequence[RGBTuple]) -> List[int]:
        report = [0x00] * self.report_size

        header_offset = 1
        if self.report_size >= 4:
            report[header_offset : header_offset + 3] = [0xAA, 0x55, 0x00]

        offset = header_offset + 3
        for r, g, b in colors:
            if offset + 3 > self.report_size:
                break
            report[offset] = int(max(0, min(255, r)))
            report[offset + 1] = int(max(0, min(255, g)))
            report[offset + 2] = int(max(0, min(255, b)))
            offset += 3

        return report
