"""Frame-processing engine for the mirroring runtime loop.

Public API is re-exported from focused submodules for maintainability.
"""

from nanoleaf_sync.runtime.engine_frame import (
    FrameProcessingTimings,
    PendingFrame,
    PendingFrameSlot,
    _adaptive_one_euro_blend,
    _apply_neighbor_blend,
    _capture_backend_display_referred,
    _ensure_runtime_artifacts,
    _estimate_processing_staleness_ms,
    _frame_context_latency_labels,
    _gamut_init_from_config,
    _make_fps_governor,
    _mapping_signature,
    _no_pending_frame_rate_per_second,
    _reset_pipeline_state,
    _resolve_capture_frame_dimensions,
    _side_variance_diagnostics,
    _zone_sampling_diagnostic_fields,
    _zones_signature,
    compute_max_send_age_ms,
    evaluate_stale_output_drop,
    process_frame,
)
from nanoleaf_sync.runtime.engine_loop import _run_loop_pipeline, run_loop
from nanoleaf_sync.runtime.state import RuntimeState

__all__ = [
    "FrameProcessingTimings",
    "PendingFrame",
    "PendingFrameSlot",
    "RuntimeState",
    "_adaptive_one_euro_blend",
    "_apply_neighbor_blend",
    "_capture_backend_display_referred",
    "_ensure_runtime_artifacts",
    "_estimate_processing_staleness_ms",
    "_frame_context_latency_labels",
    "_gamut_init_from_config",
    "_make_fps_governor",
    "_mapping_signature",
    "_no_pending_frame_rate_per_second",
    "_reset_pipeline_state",
    "_resolve_capture_frame_dimensions",
    "_side_variance_diagnostics",
    "_zone_sampling_diagnostic_fields",
    "_zones_signature",
    "compute_max_send_age_ms",
    "evaluate_stale_output_drop",
    "process_frame",
    "run_loop",
    "_run_loop_pipeline",
]
