from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

ProbeStage = Literal["instantiate", "warmup", "capture", "close", "unknown"]
ProbeErrorKind = Literal["timeout", "backend-init", "capture-failed", "backend-close", "unknown"]
BackendFactory = Callable[[str, int, int], Any]


@dataclass(frozen=True, slots=True)
class ProbeError:
    kind: ProbeErrorKind
    stage: ProbeStage
    message: str


@dataclass(slots=True)
class CandidateProbeResult:
    candidate: str
    status: str = "untested"
    reason: str = ""
    attempted_captures: int = 0
    success_count: int = 0
    failure_count: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    errors: list[ProbeError] = field(default_factory=list)
    median_ms: float | None = None
    p95_ms: float | None = None
    jitter_ms: float | None = None
    score: float | None = None
    tentative: bool = False
    qualified: bool = False

    @property
    def error_messages(self) -> list[str]:
        return [error.message for error in self.errors]


@dataclass(frozen=True, slots=True)
class ProbeConfig:
    measure_iterations: int = 20
    min_success_ratio: float = 0.6
    min_confident_samples: int = 20
    quick_probe: bool = False
    allow_interactive: bool = False
    global_timeout_s: float = 8.0
    instantiate_timeout_s: float = 2.0
    warmup_timeout_s: float = 2.0
    capture_timeout_s: float = 1.0
    close_timeout_s: float = 0.5
    backend_factory: BackendFactory | None = None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    selected_backend: str | None
    candidates: list[CandidateProbeResult]
    started_monotonic_s: float
    elapsed_s: float
    timed_out: bool = False
