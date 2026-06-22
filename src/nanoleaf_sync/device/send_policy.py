from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LiveSendPolicy(StrEnum):
    RESPONSE_REQUIRED = "response_required"
    NONBLOCKING_DRAIN = "nonblocking_drain"
    WRITE_ONLY = "write_only"
    ACK_EVERY_N_FRAMES = "ack_every_n_frames"


@dataclass(frozen=True)
class LiveSendPolicyDecision:
    policy: LiveSendPolicy
    response_wait_skipped: bool
    transition_reason: str
    requires_frame_ack: bool


def select_live_send_policy(
    *,
    report_count: int,
    prefer_write_only_live_send: bool,
    enable_live_frame_write_optimization: bool,
    is_live_frame: bool,
    has_write_with_timing: bool,
    has_nonblocking_drain: bool,
    first_frame_after_reopen: bool,
    probed_report_size: int | None = None,
) -> LiveSendPolicyDecision:
    if not is_live_frame or not enable_live_frame_write_optimization:
        return LiveSendPolicyDecision(
            policy=LiveSendPolicy.RESPONSE_REQUIRED,
            response_wait_skipped=False,
            transition_reason="live optimization disabled or non-live command",
            requires_frame_ack=True,
        )
    multi_report = int(report_count) > 1
    if multi_report:
        if has_nonblocking_drain:
            return LiveSendPolicyDecision(
                policy=LiveSendPolicy.NONBLOCKING_DRAIN,
                response_wait_skipped=True,
                transition_reason="multi-report frame requires bounded drain",
                requires_frame_ack=True,
            )
        return LiveSendPolicyDecision(
            policy=LiveSendPolicy.RESPONSE_REQUIRED,
            response_wait_skipped=False,
            transition_reason="multi-report frame without drain path",
            requires_frame_ack=True,
        )
    effective_first_frame = bool(first_frame_after_reopen and probed_report_size is None)
    if effective_first_frame:
        return LiveSendPolicyDecision(
            policy=LiveSendPolicy.RESPONSE_REQUIRED,
            response_wait_skipped=False,
            transition_reason="first frame after transport open/reopen",
            requires_frame_ack=True,
        )
    if has_nonblocking_drain and probed_report_size is not None:
        return LiveSendPolicyDecision(
            policy=LiveSendPolicy.NONBLOCKING_DRAIN,
            response_wait_skipped=True,
            transition_reason="probed single-report path uses bounded drain",
            requires_frame_ack=False,
        )
    if prefer_write_only_live_send and has_write_with_timing:
        return LiveSendPolicyDecision(
            policy=LiveSendPolicy.WRITE_ONLY,
            response_wait_skipped=True,
            transition_reason="single-report proven live path",
            requires_frame_ack=False,
        )
    if has_nonblocking_drain:
        return LiveSendPolicyDecision(
            policy=LiveSendPolicy.NONBLOCKING_DRAIN,
            response_wait_skipped=True,
            transition_reason="single-report drain fallback",
            requires_frame_ack=False,
        )
    if has_write_with_timing:
        return LiveSendPolicyDecision(
            policy=LiveSendPolicy.WRITE_ONLY,
            response_wait_skipped=True,
            transition_reason="single-report write-only fallback",
            requires_frame_ack=False,
        )
    return LiveSendPolicyDecision(
        policy=LiveSendPolicy.RESPONSE_REQUIRED,
        response_wait_skipped=False,
        transition_reason="no optimized transport path available",
        requires_frame_ack=True,
    )
