from __future__ import annotations

from pathlib import Path

from .kmsgrab import KMSGrabCapture
from .kwin_dbus import KWinDBusScreenshotCapture
from .mock_capture import MockScreenCapture
from .replay_capture import ReplayScreenCapture


def create_capture_backend(
    *,
    width: int,
    height: int,
    use_mock_capture: bool,
    prefer_backend: str,
    allow_fallback: bool,
    hdr_max_nits: float,
    hdr_transfer: str,
    hdr_primaries: str,
    replay_frames_path: str | None = None,
) -> object:
    """
    Create the capture backend used by the runtime service.

    This factory is the single source of truth for capture selection, so
    tests and the service cannot diverge.
    """

    if use_mock_capture:
        return MockScreenCapture(width=width, height=height)

    if prefer_backend == "replay":
        frames_path_raw = (replay_frames_path or "").strip()
        if not frames_path_raw:
            raise ValueError(
                "prefer_backend='replay' requires replay_frames_path to point to a .npz file"
            )
        frames_path = Path(frames_path_raw).expanduser()
        if not frames_path.exists():
            raise ValueError(
                f"prefer_backend='replay' configured but replay_frames_path does not exist: {frames_path}"
            )
        if frames_path.is_dir():
            raise ValueError(
                f"prefer_backend='replay' requires replay_frames_path to be a file, got directory: {frames_path}"
            )
        try:
            return ReplayScreenCapture(
                width=width,
                height=height,
                frames_path=str(frames_path),
            )
        except Exception as exc:
            raise ValueError(
                f"Failed to initialize replay capture from '{frames_path}': {exc}"
            ) from exc

    if prefer_backend in ("kwin-dbus", "kwin-dbus-screenshot"):
        return KWinDBusScreenshotCapture(width=width, height=height)

    # Default: kmsgrab-style backend with optional fallback.
    return KMSGrabCapture(
        width=width,
        height=height,
        hdr_max_nits=hdr_max_nits,
        hdr_transfer=hdr_transfer,
        hdr_primaries=hdr_primaries,
        allow_fallback=allow_fallback,
    )
