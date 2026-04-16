from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


RGBTuple = Tuple[int, int, int]


@dataclass
class RuntimeState:
    stop_event: threading.Event = field(default_factory=threading.Event)
    startup_complete: threading.Event = field(default_factory=threading.Event)
    startup_succeeded: bool = False

    prev_smoothed_colors: List[RGBTuple] = field(default_factory=list)

    consecutive_errors: int = 0
    last_error: Optional[str] = None
    frames_sent: int = 0
    last_frame_timestamp: Optional[float] = None
    last_reinit_ts: float = 0.0

    def reset_for_start(self) -> None:
        self.prev_smoothed_colors = []
        self.consecutive_errors = 0
        self.last_error = None
        self.frames_sent = 0
        self.last_frame_timestamp = None

    def mark_startup(self, succeeded: bool) -> None:
        self.startup_succeeded = succeeded
        self.startup_complete.set()

    def record_success(self) -> None:
        self.consecutive_errors = 0
        self.last_error = None
        self.frames_sent += 1
        self.last_frame_timestamp = time.time()

    def record_error(self, error: Exception) -> int:
        self.consecutive_errors += 1
        self.last_error = str(error)
        return self.consecutive_errors
