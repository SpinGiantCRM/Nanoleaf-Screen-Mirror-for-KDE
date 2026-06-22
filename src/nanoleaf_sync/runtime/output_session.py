from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class OutputSessionSnapshot:
    owner: str
    previous_mirroring_active: bool
    mirroring_generation: int


class OutputSessionController:
    """Single-writer guard for strip output paths."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner = "mirroring"
        self._previous_mirroring_active = False
        self._mirroring_generation = 0

    def begin_mirroring_generation(self) -> int:
        with self._lock:
            self._mirroring_generation += 1
            return self._mirroring_generation

    def revoke_mirroring_generation(self, generation: int) -> None:
        with self._lock:
            if int(generation) == self._mirroring_generation:
                self._mirroring_generation += 1

    def current_mirroring_generation(self) -> int:
        with self._lock:
            return self._mirroring_generation

    def acquire(self, owner: str, *, mirroring_active: bool) -> OutputSessionSnapshot:
        normalized = str(owner or "").strip().lower() or "manual-preview"
        with self._lock:
            self._previous_mirroring_active = bool(mirroring_active)
            self._owner = normalized
            return OutputSessionSnapshot(
                owner=self._owner,
                previous_mirroring_active=self._previous_mirroring_active,
                mirroring_generation=self._mirroring_generation,
            )

    def release(self, owner: str) -> bool:
        normalized = str(owner or "").strip().lower()
        with self._lock:
            if self._owner != normalized:
                return False
            self._owner = "mirroring"
            return True

    def can_mirroring_write(self, generation: int | None = None) -> bool:
        with self._lock:
            if self._owner != "mirroring":
                return False
            if generation is None:
                return True
            return int(generation) == self._mirroring_generation

    def current_owner(self) -> str:
        with self._lock:
            return self._owner
