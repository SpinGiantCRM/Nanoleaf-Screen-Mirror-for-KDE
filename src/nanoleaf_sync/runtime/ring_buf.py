"""Single-producer single-consumer ring buffer for the mirroring pipeline.

Payloads flow through two ring buffers:

* **Capture → Process**: non-blocking push; drops when full (logged at DEBUG).
* **Process → Send**: latest-preserving push; replaces stale queued work.

This design decouples the capture, processing, and HID-write stages so that
a slow device does not back-pressure the capture backend, while zone
processing never starves the HID writer.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Condition, Lock
from typing import Generic, TypeVar

import numpy as np

T = TypeVar("T")


class SPSCRingBuffer(Generic[T]):
    """Single-producer single-consumer ring buffer backed by ``deque``.

    The logical SPSC constraint is *not* enforced by the implementation;
    callers are responsible for ensuring only one thread calls push methods
    and only one thread calls pop methods.
    """

    def __init__(self, capacity: int = 2) -> None:
        self._deque: deque[T] = deque(maxlen=max(1, capacity))
        self._lock = Lock()
        self._not_empty = Condition(self._lock)
        self._not_full = Condition(self._lock)
        self._dropped_count: int = 0
        self._last_pop_coalesced: int = 0

    # ------------------------------------------------------------------
    # Push (producer) side
    # ------------------------------------------------------------------

    def try_push(self, item: T) -> bool:
        """Push *item* without blocking.

        Returns ``False`` when the buffer is full and *item* is discarded.
        """
        with self._lock:
            if len(self._deque) >= self._deque.maxlen:
                self._dropped_count += 1
                return False
            self._deque.append(item)
            self._not_empty.notify()
            return True

    def push(self, item: T, timeout: float = 0.01) -> bool:
        """Block until space is available or *timeout* seconds elapse.

        Returns ``False`` when the timeout expired without pushing.
        """
        with self._not_full:
            if not self._not_full.wait_for(
                lambda: len(self._deque) < self._deque.maxlen,
                timeout=max(0.0, float(timeout)),
            ):
                self._dropped_count += 1
                return False
            self._deque.append(item)
            self._not_empty.notify()
            return True

    def push_latest(self, item: T) -> bool:
        """Push *item*, replacing the oldest queued item when full.

        Returns ``True`` when an older item was replaced. This is intended for
        low-latency handoffs where stale work is worse than a skipped frame.
        """
        with self._lock:
            replaced = len(self._deque) >= self._deque.maxlen
            if replaced:
                self._deque.popleft()
                self._dropped_count += 1
            self._deque.append(item)
            self._not_empty.notify()
            return replaced

    # ------------------------------------------------------------------
    # Pop (consumer) side
    # ------------------------------------------------------------------

    def pop(self, timeout: float = 0.01) -> T | None:
        """Block until an item is available or *timeout* seconds elapse.

        Returns ``None`` when no item was available within the timeout.
        """
        with self._not_empty:
            if not self._not_empty.wait_for(
                lambda: len(self._deque) > 0,
                timeout=max(0.0, float(timeout)),
            ):
                return None
            item = self._deque.popleft()
            self._not_full.notify()
            return item

    def pop_latest(self, timeout: float = 0.01) -> T | None:
        """Return the newest queued item, discarding older entries."""
        with self._not_empty:
            if not self._not_empty.wait_for(
                lambda: len(self._deque) > 0,
                timeout=max(0.0, float(timeout)),
            ):
                self._last_pop_coalesced = 0
                return None

            coalesced = max(0, len(self._deque) - 1)
            item = self._deque.pop()
            self._deque.clear()
            self._last_pop_coalesced = coalesced
            self._not_full.notify()
            return item

    def try_pop(self) -> T | None:
        """Pop an item without blocking.  Returns ``None`` if empty."""
        with self._lock:
            if len(self._deque) == 0:
                return None
            item = self._deque.popleft()
            self._not_full.notify()
            return item

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def dropped_count(self) -> int:
        """Total number of items dropped due to a full buffer."""
        with self._lock:
            return self._dropped_count

    def reset_dropped(self) -> None:
        with self._lock:
            self._dropped_count = 0

    @property
    def last_pop_coalesced(self) -> int:
        return self._last_pop_coalesced

    @property
    def capacity(self) -> int:
        return self._deque.maxlen


# ---------------------------------------------------------------------------
# Pipeline payloads
# ---------------------------------------------------------------------------


@dataclass
class CapturePayload:
    """Payload flowing from the capture worker to the process worker."""

    captured_at: float
    frame: np.ndarray | None = None
    precomputed_zone_colors: np.ndarray | None = None
    frame_context: object | None = None


@dataclass
class ProcessedPayload:
    """Payload flowing from the process worker to the HID writer."""

    smoothed_colors: list
    captured_at: float
    zones_px: list
    device_zone_indices: np.ndarray
    sampled_zone_colors: np.ndarray
    pre_led_colors: np.ndarray
    final_zone_colors: np.ndarray
    processing_timings: object
    smooth_float_history: list = field(default_factory=list)
    sent_history: list = field(default_factory=list)
    frame: np.ndarray | None = None
    zone_diagnostics: list = field(default_factory=list)
    side_var: dict = field(default_factory=dict)
    frame_context: object | None = None
    color_context: object | None = None
