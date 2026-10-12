"""Explicit development-only SDR bridge; never searches for or enables native code.

Loading requires a caller-selected local extension path. No config, capture, HID
or calibration I/O. Immutable byte copies deliberately trade some speed for a
safe initial lifetime contract; benchmark the copies as part of every call.
"""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Callable, Sequence
from importlib.machinery import ExtensionFileLoader
from pathlib import Path
from typing import Any

import numpy as np

BoxSampler = Callable[
    [np.ndarray, Sequence[tuple[int, int, int, int]]],
    tuple[np.ndarray, np.ndarray] | None,
]
AdaptivePrepass = Callable[
    [np.ndarray, Sequence[tuple[int, int, int, int]]],
    tuple[np.ndarray, np.ndarray] | None,
]
_log = logging.getLogger(__name__)


class RustBoxSampler:
    def __init__(self, native: Any, *, compiler: str) -> None:
        self._native = native
        self.compiler = compiler
        self.disabled_reason: str | None = None
        self.successful_calls = 0
        self.adaptive_calls = 0
        self.adaptive_reference_zones = 0

    def __call__(
        self, image: np.ndarray, zones: Sequence[tuple[int, int, int, int]]
    ) -> tuple[np.ndarray, np.ndarray] | None:
        if self.disabled_reason is not None:
            return None
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            return None
        height, width, _ = image.shape
        try:
            # Handles padded, reversed and channel-strided arrays safely. Cost is timed.
            pixels = image.tobytes(order="C")
            rgb, variance = self._native.sample(pixels, width, height, list(zones), "srgb")
            if len(rgb) != len(zones) * 3 or len(variance) != len(zones) * 4:
                raise ValueError("Rust sampler output length mismatch")
            colors = np.frombuffer(rgb, dtype=np.uint8).reshape(len(zones), 3).copy()
            variances = np.frombuffer(variance, dtype="<f4").astype(np.float32, copy=True)
            if not np.isfinite(variances).all() or (variances < 0).any():
                raise ValueError("Invalid Rust sampler variance")
        except Exception as exc:
            self.disabled_reason = f"{type(exc).__name__}: {exc}"
            _log.warning(
                "Disabling experimental Rust sampler; using Python: %s", self.disabled_reason
            )
            return None
        self.successful_calls += 1
        return colors, variances

    def adaptive_prepass(
        self, image: np.ndarray, zones: Sequence[tuple[int, int, int, int]]
    ) -> tuple[np.ndarray, np.ndarray] | None:
        if self.disabled_reason is not None:
            return None
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            return None
        height, width, _ = image.shape
        try:
            decisions, rgb = self._native.adaptive_prepass(
                image.tobytes(order="C"), width, height, list(zones), "srgb"
            )
            if len(decisions) != len(zones) or len(rgb) != len(zones) * 3:
                raise ValueError("Rust adaptive output length mismatch")
            statuses = np.frombuffer(decisions, dtype=np.uint8).copy()
            if (statuses > 2).any():
                raise ValueError("Invalid Rust adaptive decision")
            colors = np.frombuffer(rgb, dtype=np.uint8).reshape(len(zones), 3).copy()
        except Exception as exc:
            self.disabled_reason = f"{type(exc).__name__}: {exc}"
            _log.warning(
                "Disabling experimental Rust adaptive prepass; using Python: %s",
                self.disabled_reason,
            )
            return None
        self.adaptive_calls += 1
        self.adaptive_reference_zones += int(np.count_nonzero(statuses == 2))
        return statuses, colors


def load_rust_box_sampler(path: Path) -> RustBoxSampler:
    """Load only an explicitly trusted development extension, with ABI validation."""
    spec = importlib.util.spec_from_file_location("_nanoleaf_core", path.resolve(strict=True))
    if spec is None or not isinstance(spec.loader, ExtensionFileLoader):
        raise ImportError("Not a Python native extension")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if getattr(module, "ABI_VERSION", None) != 1:
        raise ImportError("Unsupported Nanoleaf sampler ABI")
    return RustBoxSampler(module.BoxSampler(), compiler=str(module.COMPILER))
