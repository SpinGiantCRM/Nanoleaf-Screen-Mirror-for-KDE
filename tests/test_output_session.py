from nanoleaf_sync.runtime.output_session import OutputSessionController


def test_output_session_enforces_single_owner() -> None:
    controller = OutputSessionController()
    assert controller.can_mirroring_write() is True
    snapshot = controller.acquire("setup", mirroring_active=True)
    assert snapshot.owner == "setup"
    assert snapshot.previous_mirroring_active is True
    assert controller.can_mirroring_write() is False
    assert controller.release("calibration") is False
    assert controller.release("setup") is True
    assert controller.can_mirroring_write() is True
