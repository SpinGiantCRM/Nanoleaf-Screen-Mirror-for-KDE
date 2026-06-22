from __future__ import annotations

import time

from nanoleaf_sync.config.store import ConfigManager
from nanoleaf_sync.runtime.output_session import OutputSessionController
from nanoleaf_sync.service import NanoleafSyncService


def _service_with_guard(session: OutputSessionController) -> tuple[NanoleafSyncService, int]:
    generation = session.begin_mirroring_generation()
    service = NanoleafSyncService(config=ConfigManager().load())
    service.bind_mirroring_generation(generation)
    service.set_output_session_guard(lambda gen=generation: session.can_mirroring_write(gen))
    return service, generation


def test_stop_start_requires_rebinding_output_guard() -> None:
    session = OutputSessionController()
    service, generation = _service_with_guard(session)

    assert service.start() is True
    time.sleep(1.5)
    assert service.is_running() is True
    assert int(service.get_status().get("frames_sent") or 0) >= 1
    service.stop(timeout=3.0)
    session.revoke_mirroring_generation(generation)

    stale_service, _stale_generation = service, generation
    assert stale_service.start() is True
    time.sleep(6.0)
    stale_status = stale_service.get_status()
    assert int(stale_status.get("output_owner_dropped_frames") or 0) > 0
    assert stale_status.get("first_frame_sent") is False
    stale_service.stop(timeout=3.0)

    rebound_service, rebound_generation = _service_with_guard(session)
    assert rebound_service.start() is True
    time.sleep(2.0)
    rebound_status = rebound_service.get_status()
    assert rebound_status.get("first_frame_sent") is True
    assert int(rebound_status.get("frames_sent") or 0) >= 1
    assert rebound_generation > generation
    rebound_service.stop(timeout=3.0)
