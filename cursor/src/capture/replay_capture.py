from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np


@dataclass(frozen=True)
class ReplayCaptureParams:
    width: int
    height: int
    frames_path: Path


class ReplayScreenCapture:
    """Capture backend that replays RGB frames from a NumPy archive.

    Expected file format:
    - `.npz` with key `frames`
    - array shape `(N, H, W, 3)`, dtype convertible to uint8
    """

    name = "replay"

    def __init__(self, width: int, height: int, *, frames_path: str) -> None:
        self.last_capture_path: str | None = None
        self.params = ReplayCaptureParams(
            width=width,
            height=height,
            frames_path=Path(frames_path).expanduser(),
        )
        self._frames: List[np.ndarray] = self._load_frames(self.params.frames_path)
        self._idx = 0

    def _load_frames(self, path: Path) -> List[np.ndarray]:
        if not path.exists():
            raise FileNotFoundError(f"Replay frames file not found: {path}")

        with np.load(str(path), allow_pickle=False) as archive:
            if "frames" not in archive:
                raise ValueError("Replay archive must contain a 'frames' array")
            frames = archive["frames"]

        if frames.ndim != 4 or frames.shape[-1] != 3:
            raise ValueError(
                f"Expected frames shape (N,H,W,3), got: {getattr(frames, 'shape', None)}"
            )

        out: List[np.ndarray] = []
        for frame in frames:
            normalized = np.asarray(frame, dtype=np.uint8)
            if (
                normalized.shape[0] != self.params.height
                or normalized.shape[1] != self.params.width
            ):
                resized = np.zeros(
                    (self.params.height, self.params.width, 3), dtype=np.uint8
                )
                h = min(self.params.height, normalized.shape[0])
                w = min(self.params.width, normalized.shape[1])
                resized[:h, :w, :] = normalized[:h, :w, :]
                normalized = resized
            out.append(normalized)

        if not out:
            raise ValueError("Replay archive contained no frames")

        return out

    def capture(self) -> np.ndarray:
        frame = self._frames[self._idx]
        self._idx = (self._idx + 1) % len(self._frames)
        return frame
