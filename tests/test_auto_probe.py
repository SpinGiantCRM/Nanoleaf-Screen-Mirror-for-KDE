from __future__ import annotations

import time

from nanoleaf_sync.capture.auto_probe import ProbeConfig, probe_backends


class _FakeBackend:
    def __init__(self, delays: list[float], failures: set[int] | None = None) -> None:
        self._delays = delays
        self._failures = failures or set()
        self._calls = 0
        self.closed = False

    def capture(self):
        delay = self._delays[min(self._calls, len(self._delays) - 1)]
        time.sleep(delay)
        call_index = self._calls
        self._calls += 1
        if call_index in self._failures:
            raise RuntimeError(f"capture failed at {call_index}")
        return object()

    def close(self) -> None:
        self.closed = True


def test_probe_backends_prefers_faster_qualified_candidate() -> None:
    backends: dict[str, _FakeBackend] = {}

    def _factory(candidate: str, _width: int, _height: int):
        if candidate == "slow":
            backends[candidate] = _FakeBackend([0.005])
        else:
            backends[candidate] = _FakeBackend([0.001])
        return backends[candidate]

    result = probe_backends(
        32,
        18,
        ["slow", "fast"],
        ProbeConfig(backend_factory=_factory, measure_iterations=3),
    )

    assert result.selected_backend == "fast"
    assert [entry.candidate for entry in result.candidates] == ["fast", "slow"]
    assert all(entry.qualified for entry in result.candidates)
    assert backends["slow"].closed
    assert backends["fast"].closed


def test_probe_backends_enforces_success_threshold_before_latency() -> None:
    def _factory(candidate: str, _width: int, _height: int):
        if candidate == "flaky":
            # warm-up succeeds, then two failures in measured captures.
            return _FakeBackend([0.001], failures={1, 2})
        return _FakeBackend([0.003])

    result = probe_backends(
        32,
        18,
        ["flaky", "stable"],
        ProbeConfig(backend_factory=_factory, measure_iterations=3, min_success_ratio=0.75),
    )

    assert result.selected_backend == "stable"
    assert result.candidates[0].candidate == "stable"
    assert result.candidates[1].candidate == "flaky"
    assert result.candidates[1].qualified is False


def test_probe_backends_capture_timeout_is_reported() -> None:
    def _factory(_candidate: str, _width: int, _height: int):
        return _FakeBackend([0.05])

    result = probe_backends(
        32,
        18,
        ["timeout-backend"],
        ProbeConfig(
            backend_factory=_factory,
            measure_iterations=3,
            warmup_timeout_s=0.01,
            capture_timeout_s=0.01,
            global_timeout_s=0.5,
        ),
    )

    candidate = result.candidates[0]
    assert result.selected_backend is None
    assert candidate.failure_count >= 1
    assert any("timed out" in message for message in candidate.error_messages)
    assert any(error.kind == "timeout" for error in candidate.errors)


def test_probe_backends_tie_breaks_by_candidate_name() -> None:
    def _factory(_candidate: str, _width: int, _height: int):
        return _FakeBackend([0.001])

    result = probe_backends(
        32,
        18,
        ["zeta", "alpha"],
        ProbeConfig(backend_factory=_factory, measure_iterations=3),
    )

    assert result.selected_backend == "alpha"
    assert [entry.candidate for entry in result.candidates] == ["alpha", "zeta"]


def test_probe_backends_records_instantiate_failures() -> None:
    def _factory(candidate: str, _width: int, _height: int):
        if candidate == "broken":
            raise RuntimeError("backend init exploded")
        return _FakeBackend([0.003])

    result = probe_backends(
        32,
        18,
        ["broken", "stable"],
        ProbeConfig(backend_factory=_factory, measure_iterations=3),
    )

    broken = next(item for item in result.candidates if item.candidate == "broken")
    assert any(error.kind == "backend-init" for error in broken.errors)
    assert broken.qualified is False
