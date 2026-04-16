from __future__ import annotations

from pathlib import Path

import numpy as np

from capture.factory import create_capture_backend


def test_capture_factory_replay_cycles_frames(tmp_path: Path) -> None:
    frames = np.array(
        [
            np.zeros((2, 3, 3), dtype=np.uint8),
            np.full((2, 3, 3), 127, dtype=np.uint8),
        ],
        dtype=np.uint8,
    )
    replay_file = tmp_path / "frames.npz"
    np.savez(replay_file, frames=frames)

    backend = create_capture_backend(
        width=3,
        height=2,
        use_mock_capture=False,
        prefer_backend="replay",
        allow_fallback=True,
        hdr_max_nits=1000.0,
        hdr_transfer="srgb",
        hdr_primaries="bt709",
        replay_frames_path=str(replay_file),
    )

    frame1 = backend.capture()
    frame2 = backend.capture()
    frame3 = backend.capture()

    assert np.array_equal(frame1, frames[0])
    assert np.array_equal(frame2, frames[1])
    assert np.array_equal(frame3, frames[0])
