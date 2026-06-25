"""Runtime loop orchestration for the mirroring pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable

from nanoleaf_sync.config.model import AppConfig
from nanoleaf_sync.runtime.engine_frame import _gamut_init_from_config, _make_fps_governor
from nanoleaf_sync.runtime.engine_loop_context import LoopPipelineContext
from nanoleaf_sync.runtime.engine_loop_supervisor import run_loop_supervisor
from nanoleaf_sync.runtime.state import RuntimeState

logger = logging.getLogger(__name__)


def _run_loop_pipeline(
    *,
    config: AppConfig,
    state: RuntimeState,
    get_capture,
    get_driver,
    install_drivers,
    close_backends,
    can_mirroring_write: Callable[[], bool] | None = None,
) -> None:
    _gamut_init_from_config(config)
    governor = _make_fps_governor(config)
    state.target_fps = governor.target_fps
    ctx = LoopPipelineContext(
        config=config,
        state=state,
        get_capture=get_capture,
        get_driver=get_driver,
        install_drivers=install_drivers,
        close_backends=close_backends,
        can_mirroring_write=can_mirroring_write,
        governor=governor,
        log_interval_s=float(getattr(config, "status_log_interval_s", 5.0)),
        error_limit=max(1, int(getattr(config, "max_consecutive_errors", 5))),
        startup_frame_timeout_s=max(0.1, float(getattr(config, "startup_frame_timeout_s", 5.0))),
    )
    run_loop_supervisor(ctx)


def run_loop(
    *,
    config: AppConfig,
    state: RuntimeState,
    get_capture,
    get_driver,
    install_drivers,
    close_backends,
    use_legacy_pipeline: bool = False,
    can_mirroring_write: Callable[[], bool] | None = None,
) -> None:
    """Entry point for the mirroring 3-stage pipeline runtime loop."""
    if use_legacy_pipeline:
        logger.warning(
            "use_legacy_pipeline is deprecated and ignored; the 3-stage pipeline is always used."
        )
    _run_loop_pipeline(
        config=config,
        state=state,
        get_capture=get_capture,
        get_driver=get_driver,
        install_drivers=install_drivers,
        close_backends=close_backends,
        can_mirroring_write=can_mirroring_write,
    )
