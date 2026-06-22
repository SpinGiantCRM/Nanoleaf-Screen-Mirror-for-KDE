from __future__ import annotations

from nanoleaf_sync.device.send_policy import (
    LiveSendPolicy,
    LiveSendPolicyDecision,
    apply_periodic_ack_check,
)


def test_periodic_ack_skips_response_required_policy() -> None:
    decision = LiveSendPolicyDecision(
        policy=LiveSendPolicy.RESPONSE_REQUIRED,
        response_wait_skipped=False,
        transition_reason="baseline",
        requires_frame_ack=True,
    )
    assert apply_periodic_ack_check(decision, live_frame_index=30).policy == (
        LiveSendPolicy.RESPONSE_REQUIRED
    )
