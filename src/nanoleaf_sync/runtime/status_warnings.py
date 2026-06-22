from __future__ import annotations

from typing import Any


def build_runtime_warnings(*, status: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    frame_ctx = status.get("latest_frame_context")
    source = frame_ctx.get("source") if isinstance(frame_ctx, dict) else None
    if isinstance(source, dict):
        confidence = str(source.get("source_confidence") or "")
        if confidence == "primary-default":
            warnings.append(
                "Capture monitor is unset; mirroring uses Plasma primary display heuristic."
            )
        scale_conf = str(source.get("scale_confidence") or "")
        if scale_conf == "compositor-layout":
            warnings.append(
                "Portal compositor layout size differs from stream pixels; "
                "sampling uses buffer size."
            )
    color_ctx = status.get("latest_color_context")
    if isinstance(color_ctx, dict):
        confidence = str(color_ctx.get("confidence") or "")
        if confidence in {"heuristic", "fallback", "unknown"}:
            warnings.append(f"HDR/colour metadata confidence is {confidence}.")
    identity = status.get("capture_source_identity")
    if isinstance(identity, dict) and int(identity.get("change_count") or 0) > 0:
        warnings.append("Capture source identity changed during this session.")
    hdr_path = status.get("hdr_colour_path")
    if isinstance(hdr_path, dict):
        metadata_source = str(hdr_path.get("capture_metadata_source") or "")
        if metadata_source in {"unknown", "kwin display-referred", "session fallback"}:
            warnings.append(f"HDR capture metadata source is {metadata_source}.")
    transport = status.get("usb_transport_profile")
    if isinstance(transport, dict):
        missed_rate = float(transport.get("missed_ack_rate") or 0.0)
        if missed_rate >= 0.25:
            warnings.append(
                f"USB ACK miss rate is high ({missed_rate:.0%}); output policy may degrade."
            )
    portal_restore = status.get("portal_restore_token_state")
    if portal_restore in {"reprompted_or_ignored", "failed"}:
        warnings.append(f"Portal screen restore state: {portal_restore}.")
    return warnings
