from __future__ import annotations

from typing import Any

from nanoleaf_sync.color.capture_metadata import CaptureMetadata, resolve_capture_metadata
from nanoleaf_sync.runtime.frame_context import (
    CaptureMethodConfidence,
    DisplaySourceContext,
    SourceConfidence,
    default_display_source_context,
)


def _parse_int_pair(value: object) -> tuple[int, int] | None:
    if isinstance(value, dict):
        x = value.get("x", value.get(0))
        y = value.get("y", value.get(1))
        if x is not None and y is not None:
            return int(x), int(y)
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return int(value[0]), int(value[1])
    return None


def _parse_size_pair(value: object) -> tuple[int, int] | None:
    if isinstance(value, dict):
        w = value.get("width", value.get("w"))
        h = value.get("height", value.get("h"))
        if w is not None and h is not None:
            return int(w), int(h)
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return int(value[0]), int(value[1])
    return None


def build_kwin_display_source_context(
    backend: object,
    *,
    frame_width: int,
    frame_height: int,
) -> DisplaySourceContext:
    params = getattr(backend, "params", None)
    monitor_id = str(getattr(params, "monitor_id", "") or "").strip() or None
    capture_path = str(getattr(backend, "last_capture_path", "") or "")
    capture_method = capture_path.split(":", 1)[-1] if capture_path else "kwin-dbus"
    hdr_diag = getattr(backend, "last_hdr_diagnostics", None) or {}
    metadata = resolve_capture_metadata(
        backend_metadata=hdr_diag if isinstance(hdr_diag, dict) else None,
        kwin_display_referred=bool(
            isinstance(hdr_diag, dict)
            and str(hdr_diag.get("source", "")).strip().lower() == "kwin display-referred"
        ),
    )
    if monitor_id:
        source_confidence: SourceConfidence = "explicit"
        method_confidence: CaptureMethodConfidence = "explicit-monitor"
        scale_confidence = "pixel-exact"
    else:
        source_confidence = "primary-default"
        method_confidence = "plasma-primary-empty-name"
        scale_confidence = "fallback"
    display_w = int(getattr(params, "width", frame_width) or frame_width)
    display_h = int(getattr(params, "height", frame_height) or frame_height)
    return DisplaySourceContext(
        backend="kwin-dbus",
        monitor_id=monitor_id,
        backend_source_id=monitor_id,
        pipewire_serial=None,
        compositor_position=None,
        compositor_size=None,
        stream_pixel_size=(max(1, int(frame_width)), max(1, int(frame_height))),
        display_pixel_size=(display_w, display_h),
        scale_x=float(display_w) / max(1.0, float(frame_width)),
        scale_y=float(display_h) / max(1.0, float(frame_height)),
        refresh_hz=None,
        hdr_metadata=metadata,
        source_confidence=source_confidence,
        capture_method=capture_method,
        capture_method_confidence=method_confidence,
        scale_confidence=scale_confidence,
    )


def build_portal_display_source_context(
    backend: object,
    *,
    frame_width: int,
    frame_height: int,
) -> DisplaySourceContext:
    stream_props = getattr(backend, "last_stream_properties", None) or {}
    if not isinstance(stream_props, dict):
        stream_props = {}
    node_id = stream_props.get("id")
    pipewire_serial = stream_props.get("pipewire-serial", stream_props.get("pipewire_serial"))
    position = _parse_int_pair(stream_props.get("position"))
    size = _parse_size_pair(stream_props.get("size"))
    source_type = stream_props.get("source_type")
    mapping_id = stream_props.get("mapping_id")
    backend_source_id = None
    if mapping_id is not None:
        backend_source_id = str(mapping_id)
    elif node_id is not None:
        backend_source_id = str(node_id)
    token_state = str(getattr(backend, "portal_restore_token_state", "") or "")
    token_loaded = bool(getattr(backend, "portal_restore_token_loaded", False))
    token_accepted = bool(getattr(backend, "portal_restore_token_accepted", False))
    if token_state == "restored_confirmed" or token_accepted:  # nosec B105
        source_confidence: SourceConfidence = "restored"
        method_confidence: CaptureMethodConfidence = "portal-restored"
    elif token_state in {"submitted", "refreshed"} or token_loaded:
        source_confidence = "restored"
        method_confidence = "portal-restored"
    else:
        source_confidence = "explicit"
        method_confidence = "portal-prompt"
    serial_int = int(pipewire_serial) if pipewire_serial is not None else None
    stream_size = (max(1, int(frame_width)), max(1, int(frame_height)))
    if size is not None and size != stream_size:
        scale_confidence = "compositor-layout"
    else:
        scale_confidence = "pixel-exact"
    display_size = stream_size
    return DisplaySourceContext(
        backend="xdg-portal",
        monitor_id=str(source_type) if source_type is not None else None,
        backend_source_id=backend_source_id,
        pipewire_serial=serial_int,
        compositor_position=position,
        compositor_size=size,
        stream_pixel_size=stream_size,
        display_pixel_size=display_size,
        scale_x=1.0,
        scale_y=1.0,
        refresh_hz=None,
        hdr_metadata=CaptureMetadata(source="xdg-portal"),
        source_confidence=source_confidence,
        capture_method=str(getattr(backend, "last_capture_path", "") or "xdg-portal"),
        capture_method_confidence=method_confidence,
        scale_confidence=scale_confidence,
    )


def build_drm_display_source_context(
    backend: object,
    *,
    frame_width: int,
    frame_height: int,
) -> DisplaySourceContext:
    drm_diag = getattr(backend, "last_drm_diagnostics", None) or {}
    if not isinstance(drm_diag, dict):
        drm_diag = {}
    hdr_diag = getattr(backend, "last_hdr_diagnostics", None) or {}
    metadata = resolve_capture_metadata(
        backend_metadata=hdr_diag if isinstance(hdr_diag, dict) else None,
    )
    crtc_id = drm_diag.get("crtc_id")
    fb_id = drm_diag.get("framebuffer_id")
    backend_source_id = None
    if crtc_id is not None and fb_id is not None:
        backend_source_id = f"crtc={crtc_id};fb={fb_id}"
    elif crtc_id is not None:
        backend_source_id = f"crtc={crtc_id}"
    connector_id = drm_diag.get("connector_id")
    connector_name = drm_diag.get("connector_name")
    if connector_id is not None:
        backend_source_id = f"connector={connector_id};{backend_source_id or ''}".rstrip(";")
    elif connector_name:
        backend_source_id = str(connector_name)
    return DisplaySourceContext(
        backend=str(getattr(backend, "name", "kmsgrab") or "kmsgrab"),
        monitor_id=str(connector_name) if connector_name else None,
        backend_source_id=backend_source_id,
        pipewire_serial=None,
        compositor_position=None,
        compositor_size=None,
        stream_pixel_size=(max(1, int(frame_width)), max(1, int(frame_height))),
        display_pixel_size=(
            int(drm_diag.get("width", frame_width) or frame_width),
            int(drm_diag.get("height", frame_height) or frame_height),
        ),
        scale_x=1.0,
        scale_y=1.0,
        refresh_hz=(
            float(drm_diag["refresh_hz"]) if drm_diag.get("refresh_hz") is not None else None
        ),
        hdr_metadata=metadata,
        source_confidence="fallback",
        capture_method=str(getattr(backend, "last_capture_path", "") or "drm-kms"),
        capture_method_confidence="legacy-fallback",
        scale_confidence="pixel-exact",
    )


def build_display_source_context(
    backend: object,
    *,
    frame_width: int,
    frame_height: int,
) -> DisplaySourceContext:
    name = str(getattr(backend, "name", "") or "unknown")
    if name == "kwin-dbus":
        return build_kwin_display_source_context(
            backend, frame_width=frame_width, frame_height=frame_height
        )
    if name == "xdg-portal":
        return build_portal_display_source_context(
            backend, frame_width=frame_width, frame_height=frame_height
        )
    if name in {"kmsgrab", "drm-kms"}:
        return build_drm_display_source_context(
            backend, frame_width=frame_width, frame_height=frame_height
        )
    return default_display_source_context(
        backend=name,
        width=frame_width,
        height=frame_height,
    )


def parse_portal_stream_properties(stream_entry: object) -> dict[str, Any]:
    props: dict[str, Any] = {}
    if not isinstance(stream_entry, (list, tuple)) or not stream_entry:
        return props
    node_id = stream_entry[0]
    props["id"] = int(node_id) if node_id is not None else None
    if len(stream_entry) < 2:
        return props
    raw_props = stream_entry[1]
    if isinstance(raw_props, dict):
        for key, value in raw_props.items():
            normalized_key = str(key)
            if hasattr(value, "value"):
                props[normalized_key] = value.value
            else:
                props[normalized_key] = value
    return props
